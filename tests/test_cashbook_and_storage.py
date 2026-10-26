import threading
from datetime import datetime
import pytest
from src.controllers.db_controller import DBController, GoBDError
from src.models.database import DatabaseManager, WrongPasswordError
from src.utils import paths
from src.utils.backup import create_backup, restore_backup
from src.utils.einvoice_parser import parse_einvoice_xml, read_einvoice, to_html

UBL = """<?xml version="1.0"?><Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
<cbc:CustomizationID>urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0</cbc:CustomizationID><cbc:ID>L-4711</cbc:ID><cbc:IssueDate>2026-09-15</cbc:IssueDate><cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
<cac:AccountingSupplierParty><cac:Party><cac:PartyLegalEntity><cbc:RegistrationName>Lieferant &amp; Co KG</cbc:RegistrationName></cac:PartyLegalEntity></cac:Party></cac:AccountingSupplierParty>
<cac:LegalMonetaryTotal><cbc:TaxExclusiveAmount currencyID="EUR">100.00</cbc:TaxExclusiveAmount><cbc:TaxInclusiveAmount currencyID="EUR">119.00</cbc:TaxInclusiveAmount><cbc:PayableAmount currencyID="EUR">119.00</cbc:PayableAmount></cac:LegalMonetaryTotal>
<cac:InvoiceLine><cbc:InvoicedQuantity unitCode="C62">2</cbc:InvoicedQuantity><cbc:LineExtensionAmount currencyID="EUR">100.00</cbc:LineExtensionAmount><cac:Item><cbc:Name>Schrauben</cbc:Name></cac:Item><cac:Price><cbc:PriceAmount currencyID="EUR">50.00</cbc:PriceAmount></cac:Price></cac:InvoiceLine></Invoice>"""


def test_cashbook_rules(controller, tmp_path):
    c = controller
    c.add_cashbook_entry(datetime(2026, 10, 1), 500, "Einlage", "A", "Einnahme", 19)
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
    create_backup(c.db, backup, "geheim123", {})
    c.close()
    reopened = DBController(DatabaseManager(paths.DB_PATH, paths.KEY_PATH))
    assert [x.company_name for x in reopened.get_customers()] == ["Gespeichert"]
    with pytest.raises(WrongPasswordError):
        restore_backup(reopened.db, backup, "falsch", {})
    reopened.add_customer(company_name="Nach dem Backup")
    restore_backup(reopened.db, backup, "geheim123", {})
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
