import csv
import io
import zipfile
from datetime import datetime, timezone
from lxml import etree
from src.utils.gobd_export import TABLES, export_gobd

DAY = datetime(2026, 10, 1, tzinfo=timezone.utc)
ITEMS = [{"title": "Beratung; \"intensiv\"\nzweite Zeile", "quantity": 1.5, "unit": "Stunde", "unit_price": 80.0, "tax_percent": 19.0},
         {"title": "Buch", "quantity": 1, "unit_price": 20.0, "tax_percent": 7.0}]


def _read(zipf, name):
    return list(csv.reader(io.StringIO(zipf.read(name).decode("utf-8")), delimiter=";"))


def _data(controller, tmp_path):
    c = controller
    customer_id = c.add_customer(company_name="Kunde AG", address="Weg 2", postal_code="20095", city="Hamburg")
    invoice_id = c.create_invoice(customer_id, DAY, DAY, ITEMS, status="Offen")
    c.create_invoice(customer_id, DAY, DAY, ITEMS) # draft: not exported
    c.record_payment(invoice_id, 50.0, datetime(2026, 10, 5))
    receipt = tmp_path / "beleg.pdf"
    receipt.write_bytes(b"%PDF-1.4 Beleg")
    c.add_cashbook_entry(datetime(2026, 10, 2), 100.0, "Bareinnahme", "", "Einnahme", 19.0, str(receipt))
    c.finalize_cashbook()
    return invoice_id


def test_export_contains_all_tables_and_documents(controller, seller, tmp_path):
    invoice_id = _data(controller, tmp_path)
    target = tmp_path / "export.zip"
    counts = export_gobd(controller, str(target), 2026)
    assert counts["Rechnungen"] == 1 and counts["Rechnungspositionen"] == 2 and counts["Zahlungen"] == 1
    assert counts["Kassenbuch"] == 1 and counts["Belege"] == 2 # invoice PDF and receipt
    with zipfile.ZipFile(target) as zipf:
        names = set(zipf.namelist())
        assert {t.file for t in TABLES} | {"index.xml", "LIESMICH.txt"} <= names
        invoices = _read(zipf, "rechnungen.csv")
        header, row = invoices
        invoice = controller.get_invoice(invoice_id)
        values = dict(zip(header, row))
        assert values["rechnungsnummer"] == invoice.invoice_number and values["rechnungsdatum"] == "01.10.2026"
        assert values["brutto"] == f"{invoice.gross_amount:.2f}".replace(".", ",") and values["bezahlt"] == "50,00"
        # The archived PDF is in the export, byte for byte, and its hash is listed
        assert zipf.read(f"belege/{values['pdf_datei']}") == open(invoice.pdf_path, "rb").read()
        items = _read(zipf, "rechnungspositionen.csv")
        assert items[1][2] == 'Beratung; "intensiv" zweite Zeile' and items[1][4] == "1,5000"
        # Every row has as many fields as the header (separators and quotes inside texts are escaped)
        for table in TABLES:
            rows = _read(zipf, table.file)
            assert all(len(r) == len(table.columns) for r in rows), table.file


def test_index_xml_follows_the_description_standard(controller, seller, tmp_path):
    _data(controller, tmp_path)
    target = tmp_path / "export.zip"
    export_gobd(controller, str(target), None, include_documents=False)
    with zipfile.ZipFile(target) as zipf:
        assert not any(n.startswith("belege/") for n in zipf.namelist())
        root = etree.fromstring(zipf.read("index.xml"), etree.XMLParser(load_dtd=False, no_network=True))
        assert root.getroottree().docinfo.system_url == "gdpdu-01-08-2002.dtd"
        tables = root.findall("Media/Table")
        assert [t.findtext("URL") for t in tables] == [t.file for t in TABLES]
        order = ["URL", "Name", "Description", "Validity", "UTF8", "DecimalSymbol", "DigitGroupingSymbol", "Range", "VariableLength"]
        for element, table in zip(tables, TABLES):
            tags = [child.tag for child in element]
            assert tags == [t for t in order if t in tags] # sequence required by the DTD
            columns = element.findall("VariableLength/VariablePrimaryKey") + element.findall("VariableLength/VariableColumn")
            assert [c.findtext("Name") for c in columns] == [c.name for c in table.columns]
            # Column names in the CSV header match the description
            assert _read(zipf, table.file)[0] == [c.name for c in table.columns]


def test_years_are_filtered(controller, seller, tmp_path):
    _data(controller, tmp_path)
    target = tmp_path / "export.zip"
    counts = export_gobd(controller, str(target), 2025, include_documents=False)
    assert counts["Rechnungen"] == counts["Kassenbuch"] == counts["Zahlungen"] == 0
    assert counts["Verlauf"] > 0 and counts["Kunden"] == 1 # master data and history are always complete


def test_export_from_the_settings(controller, seller, tmp_path, monkeypatch, qapp):
    from PySide6.QtWidgets import QFileDialog
    from qfluentwidgets import MessageBoxBase
    from src.views.settings_interface import SettingsInterface
    _data(controller, tmp_path)
    target = tmp_path / "aus_einstellungen.zip"
    monkeypatch.setattr(MessageBoxBase, "exec", lambda self: 1)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), "")))
    settings = SettingsInterface(controller)
    settings.export_gobd()
    assert zipfile.is_zipfile(target)
    log = [h.action for h in controller.get_document_history("Export", 0)]
    assert log and log[0].startswith("GoBD-Datenexport (2026)")
