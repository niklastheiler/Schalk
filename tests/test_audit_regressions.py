"""
Regression tests for the findings of the acceptance audit (docs/AUDIT.md): payments, status rules,
tamper detection of the history and of number sequences, durability of sealed data, restore checks.
"""
import os
import sqlite3
from datetime import datetime, timedelta, timezone
import pytest
from src.controllers.db_controller import GoBDError
from src.models.database import FILE_MAGIC, DatabaseManager
from src.utils import paths
from src.utils.key_store import load_key
from cryptography.fernet import Fernet

DAY = datetime(2026, 10, 1, tzinfo=timezone.utc)
ITEM = [{"title": "Leistung", "quantity": 1, "unit_price": 100.0, "tax_percent": 19.0}] # 119,00 € gross


def _customer(c):
    return c.add_customer(company_name="Kunde AG", address="Weg 2", postal_code="20095", city="Hamburg")


def _issued(c) -> int:
    return c.create_invoice(_customer(c), DAY, DAY, ITEM, status="Offen")


def _stored_db(c) -> sqlite3.Connection:
    """The database exactly as it is on disk (decrypted), not the in-memory state."""
    with open(paths.DB_PATH, "rb") as f:
        data = f.read()
    conn = sqlite3.connect(":memory:")
    conn.deserialize(Fernet(load_key(paths.KEY_PATH)).decrypt(data[len(FILE_MAGIC):]))
    return conn


# --- Payments ---
def test_payment_settles_the_whole_invoice_with_its_date(controller, seller):
    c = controller
    today = datetime.now(timezone.utc)
    invoice_id = c.create_invoice(_customer(c), today, today, ITEM, status="Offen") # not yet due
    c.record_payment(invoice_id, datetime(2026, 11, 20))
    invoice = c.get_invoice_header(invoice_id)
    assert invoice.status == "Bezahlt" and c.outstanding_amount(invoice) == 0 and invoice.paid_at == datetime(2026, 11, 20)
    assert [p.amount for p in c.get_payments(invoice_id)] == [119.0]
    with pytest.raises(ValueError, match="bereits bezahlt"):
        c.record_payment(invoice_id, datetime(2026, 11, 21))
    assert c.verify_integrity() == []


def test_there_is_no_partly_paid_status(controller, seller):
    c = controller
    invoice_id = _issued(c)
    assert "Teilbezahlt" not in c.next_invoice_statuses(c.get_invoice_header(invoice_id))
    ok, _ = c.update_invoice_status(invoice_id, "Teilbezahlt")
    assert not ok


def test_returned_payment_reopens_and_becomes_overdue(controller, seller):
    c = controller
    invoice_id = _issued(c) # dated 01.10.2026, due 15.10.2026: overdue by now
    c.update_invoice_status(invoice_id, "Bezahlt")
    assert c.get_invoice_header(invoice_id).status == "Bezahlt"
    ok, _ = c.update_invoice_status(invoice_id, "Offen") # e.g. returned direct debit
    invoice = c.get_invoice_header(invoice_id)
    assert ok and invoice.paid_amount == 0 and invoice.status == "Überfällig" and invoice.paid_at is None
    # Payments are never deleted: the return is a negative entry
    assert [p.amount for p in c.get_payments(invoice_id)] == [119.0, -119.0]


def test_payments_only_for_issued_invoices(controller, seller):
    c = controller
    draft = c.create_invoice(_customer(c), DAY, DAY, ITEM)
    with pytest.raises(GoBDError):
        c.record_payment(draft, datetime(2026, 10, 2))
    invoice_id = _issued(c)
    with pytest.raises(ValueError, match="Zukunft"):
        c.record_payment(invoice_id, datetime.now() + timedelta(days=2))
    with pytest.raises(ValueError, match="keine Zahlung"):
        c.reverse_payment(invoice_id, datetime(2026, 10, 2))
    c.cancel_invoice(invoice_id)
    with pytest.raises(GoBDError):
        c.record_payment(invoice_id, datetime(2026, 10, 2))


def test_legacy_partly_paid_invoices_are_open_again(controller, seller):
    c = controller
    invoice_id = _issued(c)
    c.db.memory_conn.execute("UPDATE invoices SET status = 'Teilbezahlt' WHERE id = ?", (invoice_id,))
    c.db.memory_conn.commit()
    c._reload("invoices")
    c._migrate_partly_paid()
    c.refresh_overdue()
    assert c.get_invoice_header(invoice_id).status == "Überfällig"


def test_manipulated_paid_amount_is_detected(controller, seller):
    c = controller
    invoice_id = _issued(c)
    c.record_payment(invoice_id, datetime(2026, 10, 10))
    c.db.memory_conn.execute("UPDATE invoices SET paid_amount = 100 WHERE id = ?", (invoice_id,))
    c.db.memory_conn.commit()
    assert any("bezahlte Betrag" in p for p in c.verify_integrity(check_files=False))


# --- Status and date rules ---
def test_new_invoices_cannot_skip_the_process(controller, seller):
    c = controller
    for status in ("Bezahlt", "Storniert", "Teilbezahlt", "Überfällig", "Unsinn"):
        with pytest.raises(ValueError):
            c.create_invoice(_customer(c), DAY, DAY, ITEM, status=status)
    draft = c.create_invoice(_customer(c), DAY, DAY, ITEM)
    with pytest.raises(ValueError):
        c.update_invoice(draft, c.get_invoice(draft).customer_id, DAY, DAY, ITEM, status="Storniert")
    assert c.get_invoice(draft).status == "Entwurf"


def test_invoice_dated_in_the_future_is_not_finalized(controller, seller):
    c = controller
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    invoice_id = c.create_invoice(_customer(c), tomorrow, DAY, ITEM)
    ok, message = c.update_invoice_status(invoice_id, "Offen")
    assert not ok and "Zukunft" in message


# --- Tamper detection ---
def test_history_is_hash_chained(controller, seller):
    c = controller
    invoice_id = _issued(c)
    assert c.verify_integrity(check_files=False) == []
    c.db.memory_conn.execute("UPDATE document_history SET user = 'Jemand' WHERE document_id = ?", (invoice_id,))
    c.db.memory_conn.commit()
    assert any(p.startswith("Verlauf") for p in c.verify_integrity(check_files=False))


def test_deleted_history_entry_is_detected(controller, seller):
    c = controller
    _issued(c)
    _issued(c)
    c.db.memory_conn.execute("DELETE FROM document_history WHERE id = (SELECT min(id) + 1 FROM document_history)")
    c.db.memory_conn.commit()
    assert any(p.startswith("Verlauf") for p in c.verify_integrity(check_files=False))


def test_master_data_changes_are_logged(controller, seller):
    c = controller
    customer_id = _customer(c)
    c.update_customer(customer_id, city="Bremen")
    c.set_settings({"iban": "DE89370400440532013000"})
    customer_log = [h.action for h in c.get_document_history("Customer", customer_id)]
    assert customer_log[0] == "Angelegt" and "city: Hamburg -> Bremen" in customer_log[1]
    settings_log = [h.action for h in c.get_document_history("Settings", 0)]
    assert any(a.startswith("iban: DE02120300000000202051 -> DE89370400440532013000") for a in settings_log)
    assert c.verify_integrity(check_files=False) == []


def test_missing_invoice_number_is_detected(controller, seller):
    c = controller
    ids = [_issued(c) for _ in range(3)]
    middle = c.get_invoice_header(ids[1]).invoice_number
    # Removing an issued invoice by hand (and repairing the hash chain would not help either)
    c.db.memory_conn.execute("DELETE FROM invoice_items WHERE invoice_id = ?", (ids[1],))
    c.db.memory_conn.execute("DELETE FROM invoices WHERE id = ?", (ids[1],))
    c.db.memory_conn.commit()
    problems = c.verify_integrity(check_files=False)
    assert any("Rechnungsnummern" in p and str(int(middle[-3:])) in p for p in problems)


def test_number_gap_ranges():
    from src.controllers.db_controller import INVOICE_NUMBER_PATTERN, DBController, _ranges
    gaps = DBController._gaps(["RE202601001", "RE202602004", "RE202603007", "RE202501001", "ALT-1"], INVOICE_NUMBER_PATTERN)
    assert gaps == {"2026": [2, 3, 5, 6]}
    assert _ranges([2, 3, 5, 6]) == "2–3, 5–6"


def test_legacy_history_is_sealed_once(controller, seller):
    c = controller
    _issued(c)
    c.db.memory_conn.execute("UPDATE document_history SET hash_chain = NULL")
    c.db.memory_conn.commit()
    c._seal_legacy_history()
    assert c.verify_integrity(check_files=False) == []


# --- Durability ---
def test_finalized_invoice_is_on_disk_immediately(controller, seller):
    c = controller
    invoice_id = _issued(c)
    number = c.get_invoice_header(invoice_id).invoice_number
    # No flush or close: what a crash right now would leave behind
    row = _stored_db(c).execute("SELECT invoice_number, hash_chain FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
    assert row[0] == number and row[1]


# --- Restore ---
def test_restore_rejects_foreign_or_damaged_databases(controller):
    foreign = sqlite3.connect(":memory:")
    foreign.execute("CREATE TABLE t (x)")
    with pytest.raises(ValueError, match="keine Schalk-Datenbank"):
        controller.db.restore_database(foreign.serialize())
    data = bytearray(controller.db.snapshot())
    page_size = int.from_bytes(data[16:18], "big")
    for page in range(1, len(data) // page_size): # every b-tree page after the first
        data[page * page_size:page * page_size + 64] = b"\xff" * 64
    with pytest.raises(ValueError):
        controller.db.restore_database(bytes(data))
    assert not controller.db._restored


def test_database_manager_reopens_with_history_chain(controller, seller):
    c = controller
    _issued(c)
    c.close()
    from src.controllers.db_controller import DBController
    reopened = DBController(DatabaseManager(paths.DB_PATH, paths.KEY_PATH))
    try:
        assert reopened.verify_integrity() == []
    finally:
        reopened.close()
    assert os.path.isfile(paths.DB_PATH)


# --- Received e-invoices ---
def _xrechnung(c, tmp_path) -> bytes:
    from src.utils.invoice_documents import export_xrechnung
    customer_id = c.add_customer(company_name="Kunde AG", address="Weg 2", postal_code="20095", city="Hamburg",
                                 email="rechnung@kunde.de")
    invoice_id = c.create_invoice(customer_id, DAY, DAY, ITEM, status="Offen")
    target = tmp_path / "x.xml"
    export_xrechnung(c, c.get_invoice(invoice_id), str(target))
    return target.read_bytes()


def test_received_einvoice_is_checked_against_the_rules(controller, seller, tmp_path):
    from src.utils.einvoice_parser import parse_einvoice_xml
    from src.utils.einvoice_validation import check_received
    xml = _xrechnung(controller, tmp_path)
    assert check_received(parse_einvoice_xml(xml)) == []
    # Tax total no longer matches the tax breakdown (BR-CO-14)
    import re
    broken = re.sub(rb'(<ram:TaxTotalAmount currencyID="EUR">)19.00<', rb'\g<1>18.00<', xml)
    assert broken != xml
    notes = check_received(parse_einvoice_xml(broken))
    assert notes and all(n.startswith("Regelverstoß") for n in notes)


def test_minimum_profile_is_no_einvoice(controller, seller, tmp_path):
    from src.utils.einvoice_parser import parse_einvoice_xml
    from src.utils.einvoice_validation import check_received
    xml = _xrechnung(controller, tmp_path).replace(
        b"urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0", b"urn:factur-x.eu:1p0:minimum")
    notes = check_received(parse_einvoice_xml(xml))
    assert len(notes) == 1 and "MINIMUM" in notes[0] and "§ 14 UStG" in notes[0]


def test_document_type_declarations_are_refused():
    from src.utils.einvoice_parser import parse_einvoice_xml
    bomb = (b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
            b'<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" '
            b'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"><cbc:ID>&b;</cbc:ID></Invoice>')
    assert parse_einvoice_xml(bomb) is None


def test_oversized_files_are_not_read(tmp_path, monkeypatch):
    from src.utils import einvoice_parser
    path = tmp_path / "gross.xml"
    path.write_bytes(b"<x/>" * 10)
    monkeypatch.setattr(einvoice_parser, "MAX_FILE_SIZE", 10)
    with pytest.raises(ValueError, match="größer"):
        einvoice_parser.read_einvoice(str(path))


def test_check_of_received_invoice_is_logged(controller, seller, tmp_path):
    path = tmp_path / "lieferant.xml"
    path.write_bytes(_xrechnung(controller, tmp_path))
    invoice_id = controller.add_incoming_invoice("Lieferant", DAY, 119.0, "Test", str(path), einvoice_format="XRechnung (CII)",
                                                 check_result="E-Rechnung geprüft (EN 16931): keine Beanstandungen")
    actions = [h.action for h in controller.get_document_history("IncomingInvoice", invoice_id)]
    assert actions == ["Created", "E-Rechnung geprüft (EN 16931): keine Beanstandungen"]
    with pytest.raises(ValueError):
        controller.add_incoming_invoice("Lieferant", DAY, float("inf"), "Test", str(path), einvoice_format="XRechnung (CII)")


def test_payment_dialog_and_paid_column(controller, seller, qapp, monkeypatch):
    from PySide6.QtCore import QDate
    from qfluentwidgets import MessageBoxBase
    from src.views.invoice_interface import InvoiceInterface

    def run(dialog):
        dialog.datePicker.setDate(QDate(2026, 11, 18)) # money came in earlier
        return 1
    monkeypatch.setattr(MessageBoxBase, "exec", run)
    today = datetime.now(timezone.utc)
    invoice_id = controller.create_invoice(_customer(controller), today, today, ITEM, status="Offen")
    interface = InvoiceInterface(controller)
    page = interface.list_page
    page.refresh()
    titles = [col.title for col in page.model.columns]
    assert titles.index("Bezahlt am") == titles.index("Fällig am") + 1
    assert "Teilbezahlt" not in controller.next_invoice_statuses(controller.get_invoice_header(invoice_id))
    interface.change_status(invoice_id, "Bezahlt")
    invoice = controller.get_invoice_header(invoice_id)
    assert invoice.status == "Bezahlt" and invoice.paid_at == datetime(2026, 11, 18)
    page.refresh()
    assert page.model.text(0, titles.index("Bezahlt am")) == "18.11.2026"


def test_sent_reminder_is_archived(controller, seller, tmp_path):
    c = controller
    invoice_id = _issued(c)
    sent = tmp_path / "mahnung.pdf"
    from src.utils.pdf_generator import PDFGenerator
    PDFGenerator(c).generate_reminder_pdf(c.get_invoice(invoice_id), str(sent), 1)
    c.record_reminder(invoice_id, 1, document=str(sent))
    archived = os.listdir(paths.REMINDER_ARCHIVE_DIR)
    assert len(archived) == 1 and open(os.path.join(paths.REMINDER_ARCHIVE_DIR, archived[0]), "rb").read() == sent.read_bytes()
    assert any(archived[0] in h.action for h in c.get_document_history("Invoice", invoice_id))


def test_invoice_without_amount_due_can_be_marked_paid(controller, seller):
    c = controller
    invoice_id = c.create_invoice(_customer(c), DAY, DAY, ITEM, credit_amount=100.0, status="Offen")
    assert c.get_invoice_header(invoice_id).gross_amount == 0
    ok, message = c.update_invoice_status(invoice_id, "Bezahlt")
    assert ok, message
    assert c.get_invoice_header(invoice_id).status == "Bezahlt" and c.get_payments(invoice_id) == []


def test_database_of_version_1_3_is_upgraded(controller, seller):
    """A database written by 1.3.x (no payments, no history chain, no new index) opens and checks out clean."""
    c = controller
    invoice_id = _issued(c)
    c.update_invoice_status(invoice_id, "Bezahlt")
    conn = c.db.memory_conn
    conn.execute("DROP TABLE payments")
    conn.execute("DROP INDEX ix_invoices_finalized")
    conn.execute("ALTER TABLE invoices DROP COLUMN paid_amount")
    conn.execute("ALTER TABLE document_history DROP COLUMN hash_chain")
    conn.commit()
    c.db.save()
    c.close()
    from src.controllers.db_controller import DBController
    upgraded = DBController(DatabaseManager(paths.DB_PATH, paths.KEY_PATH))
    try:
        assert upgraded.verify_integrity(check_files=False) == []
        invoice = upgraded.get_invoice_header(invoice_id)
        assert invoice.status == "Bezahlt" and not invoice.paid_amount
        # Marked as paid before payments existed: can be reopened without a payment
        assert upgraded.update_invoice_status(invoice_id, "Offen")[0]
        assert upgraded.get_payments(invoice_id) == []
        assert upgraded.verify_integrity(check_files=False) == []
    finally:
        upgraded.close()
