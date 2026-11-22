import threading
from datetime import datetime
import pytest
from src.controllers.db_controller import DBController, GoBDError
from src.models.database import DatabaseManager
from src.utils import paths
from src.utils.backup import create_backup, restore_backup
from src.utils.einvoice_parser import parse_einvoice_xml, read_einvoice, to_html
from receipts import RECEIPT

UBL = """<?xml version="1.0"?><Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
<cbc:CustomizationID>urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0</cbc:CustomizationID><cbc:ID>L-4711</cbc:ID><cbc:IssueDate>2026-09-15</cbc:IssueDate><cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
<cac:AccountingSupplierParty><cac:Party><cac:PartyLegalEntity><cbc:RegistrationName>Lieferant &amp; Co KG</cbc:RegistrationName></cac:PartyLegalEntity></cac:Party></cac:AccountingSupplierParty>
<cac:LegalMonetaryTotal><cbc:TaxExclusiveAmount currencyID="EUR">100.00</cbc:TaxExclusiveAmount><cbc:TaxInclusiveAmount currencyID="EUR">119.00</cbc:TaxInclusiveAmount><cbc:PayableAmount currencyID="EUR">119.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
<cac:InvoiceLine><cbc:InvoicedQuantity unitCode="C62">2</cbc:InvoicedQuantity><cbc:LineExtensionAmount currencyID="EUR">100.00</cbc:LineExtensionAmount><cac:Item><cbc:Name>Schrauben</cbc:Name></cac:Item><cac:Price><cbc:PriceAmount currencyID="EUR">50.00</cbc:PriceAmount></cac:Price></cac:InvoiceLine></Invoice>"""


def test_cashbook_rules(controller, tmp_path):
    c = controller
    c.add_cashbook_entry(datetime(2026, 10, 1), 500, "Einlage", "A", "Einnahme", 19, attachment_source=RECEIPT)
    receipt = tmp_path / "beleg.pdf"
    receipt.write_bytes(b"%PDF-1.4 test")
    entry = c.add_cashbook_entry(datetime(2026, 10, 2), 20, "Porto", "A", "Barentnahme Firma", 19, attachment_source=str(receipt))
    assert c.get_cashbook_entry(entry).attachment_hash
    with pytest.raises(ValueError):
        c.add_cashbook_entry(datetime(2026, 10, 2), 9999, "x", "A", "Barentnahme Privat", 19)
    assert c.finalize_cashbook() == 2
    c.storno_cashbook_entry(entry)
    assert c.get_cashbook_balance() == 500
    with pytest.raises(GoBDError):
        c.storno_cashbook_entry(entry)
    assert c.verify_integrity() == []


def test_incoming_xrechnung_ubl(controller, tmp_path):
    path = tmp_path / "lieferant.xml"
    path.write_text(UBL, encoding="utf-8")
    data = read_einvoice(str(path))
    assert data.format == "XRechnung (UBL)" and data.seller_name == "Lieferant & Co KG" and data.payable_amount == 119.0
    assert "Lieferant &amp; Co KG" in to_html(data)
    invoice_id = controller.add_incoming_invoice("Lieferant", datetime(2026, 9, 15), 119.0, "Schrauben", str(path), einvoice_format=data.format)
    assert controller.get_incoming_invoice(invoice_id).file_hash
    controller.cancel_incoming_invoice(invoice_id)
    assert controller.get_incoming_invoices("Lieferant", include_cancelled=False) == []


def test_xml_external_entities_are_not_resolved():
    xml = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/hosts">]><Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"><cbc:ID>&e;</cbc:ID></Invoice>'
    data = parse_einvoice_xml(xml)
    assert data is None or "localhost" not in data.number


def test_background_save_backup_and_restore(controller, tmp_path):
    c = controller
    c.add_customer(company_name="Gespeichert")
    backup = str(tmp_path / "b.backup")
    create_backup(c.db.snapshot(), backup, {})
    c.close()
    reopened = DBController(DatabaseManager(paths.DB_PATH, paths.KEY_PATH))
    assert [x.company_name for x in reopened.get_customers()] == ["Gespeichert"]
    reopened.add_customer(company_name="Nach dem Backup")
    restore_backup(reopened.db, backup, {})
    reopened.close()
    restored = DBController(DatabaseManager(paths.DB_PATH, paths.KEY_PATH))
    assert [x.company_name for x in restored.get_customers()] == ["Gespeichert"]
    restored.close()


def test_integrity_check_in_background(controller):
    done, result = threading.Event(), []
    controller.verify_integrity_async(lambda problems: (result.append(problems), done.set()), check_files=True)
    assert done.wait(30) and result == [[]]


def test_nested_session_is_refused(controller):
    from src.models.database import Customer
    with controller.get_session() as session:
        session.add(Customer(company_name="x"))
        session.flush()
        with pytest.raises(RuntimeError):
            controller.get_session()
        session.rollback()


def test_archived_files_are_found_after_a_restore_on_another_pc(controller, seller, data_dir, monkeypatch, tmp_path):
    # The database keeps absolute paths; on another PC or Windows account the data folder is elsewhere
    import shutil
    from datetime import timezone
    from src.utils.archive import remove_tree
    c = controller
    receipt = tmp_path / "beleg.pdf"
    receipt.write_bytes(b"%PDF-1.4 Beleg")
    c.add_cashbook_entry(datetime(2026, 10, 1), 50, "Einlage", "A", "Einnahme", 19, attachment_source=str(receipt))
    c.finalize_cashbook()
    customer_id = c.add_customer(company_name="Kunde AG", address="Weg 2", postal_code="20095", city="Hamburg")
    day = datetime(2026, 10, 1, tzinfo=timezone.utc)
    invoice_id = c.create_invoice(customer_id, day, day, [{"title": "X", "quantity": 1, "unit_price": 10.0, "tax_percent": 19.0}], status="Offen")
    old_pdf = c.get_invoice(invoice_id).pdf_path

    new_dir = tmp_path / "Anderer Benutzer" / "Schalk"
    shutil.copytree(data_dir / "app_data", new_dir / "app_data")
    shutil.copytree(data_dir / "assets", new_dir / "assets")
    remove_tree(str(data_dir / "app_data"))
    remove_tree(str(data_dir / "assets"))
    monkeypatch.setattr(paths, "DATA_DIR", str(new_dir))

    assert c.verify_integrity(check_files=True) == []
    pdf = c.get_archived_invoice_pdf(c.get_invoice(invoice_id))
    assert pdf != old_pdf and pdf.startswith(str(new_dir))
    assert paths.resolve(str(data_dir / "app_data" / "fehlt.pdf")) == str(data_dir / "app_data" / "fehlt.pdf")


def test_archived_names_are_short_unique_and_typed(tmp_path):
    import os
    from src.utils.archive import archive_file
    # Long enough to be shortened, short enough for the temp folder of the Windows test runner
    source = tmp_path / ("Rechnung " + "x" * 140 + ".bat")
    source.write_bytes(b"%PDF-1.4 getarnt")
    first, _ = archive_file(str(source), str(tmp_path / "archiv"), extension=".pdf")
    second, _ = archive_file(str(source), str(tmp_path / "archiv"), extension=".pdf")
    for path in (first, second):
        name = os.path.basename(path)
        assert name.endswith(".pdf") and ".bat" not in name and len(name) < 120
    assert first != second


def test_incoming_duplicates_are_found(controller, tmp_path):
    c = controller
    path = tmp_path / "lieferant.xml"
    path.write_text(UBL, encoding="utf-8")
    assert c.find_duplicate_incoming(str(path)) is None
    invoice_id = c.add_incoming_invoice("Lieferant", datetime(2026, 9, 15), 119.0, "Schrauben", str(path),
                                        einvoice_format="XRechnung (UBL)", invoice_number="L-4711", supplier_name="Lieferant & Co KG")
    assert c.get_incoming_invoice(invoice_id).file_path.endswith(".xml")
    assert c.find_duplicate_incoming(str(path)).id == invoice_id
    # Same supplier and number, but a different file (e.g. the PDF of the same invoice)
    other = tmp_path / "scan.pdf"
    other.write_bytes(b"%PDF-1.4 Scan")
    assert c.find_duplicate_incoming(str(other), "lieferant & co kg", "L-4711").id == invoice_id
    assert c.find_duplicate_incoming(str(other), "Anderer", "L-4711") is None
    c.cancel_incoming_invoice(invoice_id)
    assert c.find_duplicate_incoming(str(path)) is None


def test_columns_of_newer_versions_are_added(controller):
    # A database of an older version lacks columns added later; they are added on opening
    c = controller
    c.add_customer(company_name="Alt")
    c.db.memory_conn.execute("ALTER TABLE customers DROP COLUMN buyer_reference")
    c.db.memory_conn.commit()
    c.close()
    reopened = DBController(DatabaseManager(paths.DB_PATH, paths.KEY_PATH))
    reopened.update_customer(reopened.get_customers()[0].id, buyer_reference="04011000-12345-34")
    assert reopened.get_customers()[0].buyer_reference == "04011000-12345-34"
    reopened.close()


def test_unreadable_key_is_reported_clearly(controller):
    from src.models.database import KeyMissingError
    controller.add_customer(company_name="x")
    controller.close()

    class OtherWindowsUser:
        @staticmethod
        def load_key(path):
            raise OSError("Schlüssel nicht gültig")
    with pytest.raises(KeyMissingError, match="anderen Benutzerkonto"):
        DatabaseManager(paths.DB_PATH, paths.KEY_PATH, key_store=OtherWindowsUser)


def test_broken_database_is_set_aside_not_deleted(data_dir):
    from src.main import set_aside_database
    (data_dir / "schalk.enc.db").write_bytes(b"defekt")
    (data_dir / "schalk.key").write_bytes(b"key")
    renamed = set_aside_database()
    assert len(renamed) == 2 and not (data_dir / "schalk.enc.db").exists()
    assert sorted(open(p, "rb").read() for p in renamed) == [b"defekt", b"key"]


def test_temp_documents_get_new_names_and_are_cleaned(monkeypatch, tmp_path):
    import os
    monkeypatch.setattr(paths, "TEMP_DOCUMENTS_DIR", str(tmp_path / "Schalk"))
    first, second = paths.temp_document("Angebot_A1.pdf"), paths.temp_document("Angebot_A1.pdf")
    assert first != second and first.endswith(".pdf")
    open(first, "wb").close()
    paths.clean_temp_documents()
    assert os.listdir(tmp_path / "Schalk") == []


def test_self_test_of_the_built_program(data_dir, qapp):
    # The release workflow runs Schalk.exe --selbsttest; here the same check runs from the source
    from src import selftest
    assert selftest.run() == 0, open(selftest.REPORT, encoding="utf-8").read()
