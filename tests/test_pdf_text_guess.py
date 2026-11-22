"""Supplier, number, date and amount from the text of PDF invoices without structured data, and the upload dialog."""
from datetime import date, datetime, timezone
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from src.utils.pdf_text_guess import guess_amount, guess_date, guess_from_pdf, guess_number, guess_supplier

OWN = ["Test & Söhne GmbH", "Max Muster"]


def _pdf(path, lines, author=None):
    """A simple one-page PDF with the given lines from top to bottom."""
    c = canvas.Canvas(str(path), pagesize=A4)
    if author:
        c.setAuthor(author)
    y = 800
    for line in lines:
        c.drawString(60, y, line)
        y -= 18
    c.save()
    return str(path)


def test_din_5008_invoice_of_another_program(controller, tmp_path):
    """Invoice as Schalk itself renders it (sender line, label above the value), received from a supplier."""
    from src.utils.pdf_generator import PDFGenerator
    c = controller
    c.set_settings({"company_name": "Holzbau Meier GmbH", "address": "Sägewerkstr. 7", "postal_code": "83022",
                    "city": "Rosenheim", "tax_id": "12/345/67890", "vat_id": "DE100000008"})
    customer_id = c.add_customer(company_name="Test & Söhne GmbH", address="Hauptstr. 1", postal_code="10115", city="Berlin")
    day = datetime(2026, 11, 3, tzinfo=timezone.utc)
    invoice_id = c.create_invoice(customer_id, day, day, [{"title": "Bretter", "quantity": 3, "unit_price": 410.0, "tax_percent": 19.0}],
                                  status="Offen")
    invoice = c.get_invoice(invoice_id)
    path = tmp_path / "meier.pdf"
    PDFGenerator(c).generate_invoice_pdf(invoice, str(path))
    guess = guess_from_pdf(str(path), OWN)
    assert guess.supplier == "Holzbau Meier GmbH"
    assert guess.number == invoice.invoice_number
    assert guess.invoice_date == date(2026, 11, 3)
    assert guess.amount == 1463.70 # the gross amount, not "Summe netto" that comes first


def test_simple_layout_with_labels_on_one_line(tmp_path):
    path = _pdf(tmp_path / "schulz.pdf", [
        "Elektro Schulz e.K.", "Lindenweg 4, 50667 Köln",
        "Test & Söhne GmbH", "Hauptstr. 1", "10115 Berlin",
        "Rechnung Nr. 2026-0815", "Datum: 05.11.2026", "Leistungsdatum: 30.10.2026",
        "Summe netto 100,00 EUR", "zzgl. 19 % MwSt. 19,00 EUR", "Gesamtbetrag: 119,00 EUR",
    ])
    guess = guess_from_pdf(path, OWN)
    assert (guess.supplier, guess.number, guess.invoice_date, guess.amount) == ("Elektro Schulz e.K.", "2026-0815", date(2026, 11, 5), 119.0)


def test_english_layout_and_author_from_the_properties(tmp_path):
    path = _pdf(tmp_path / "acme.pdf", [
        "To: Test & Söhne GmbH", "Invoice No.: INV-77/2026", "Invoice date: 2026-11-04",
        "Subtotal 1,037.44", "Total amount 1,234.56 EUR",
    ], author="Acme Cloud Services")
    guess = guess_from_pdf(path, OWN)
    assert (guess.supplier, guess.number, guess.invoice_date, guess.amount) == ("Acme Cloud Services", "INV-77/2026", date(2026, 11, 4), 1234.56)


def test_pieces():
    assert guess_number("Bitte unter Angabe der Rechnungsnummer überweisen.\nRechnungsnummer: R-4711") == "R-4711"
    assert guess_number("Rechnung\nohne Nummer") == ""
    assert guess_date("Datum 4. November 2026") == date(2026, 11, 4)
    assert guess_date("Rechnungsdatum 01.02.26") == date(2026, 2, 1)
    assert guess_amount("Zwischensumme 10,00 €\nZu zahlender Betrag 11,90 €") == 11.90
    assert guess_amount("Gesamtbetrag 1 234,50 €") == 1234.50
    # The own address block (with legal form) is not the supplier; a table row is no sender line
    assert guess_supplier("Test & Söhne GmbH\nHauptstr. 1\n1 | Bretter | 3 Stück | 12345 Teile\nMöbel Krause GmbH & Co. KG", OWN) \
        == "Möbel Krause GmbH & Co. KG"


def test_unreadable_pdf_gives_empty_suggestion(tmp_path):
    path = tmp_path / "kaputt.pdf"
    path.write_bytes(b"%PDF-1.4 kein echtes PDF")
    guess = guess_from_pdf(str(path), OWN)
    assert (guess.supplier, guess.number, guess.invoice_date, guess.amount) == ("", "", None, 0.0)


def test_upload_fills_in_the_dialog(controller, seller, tmp_path, monkeypatch, qapp):
    from PySide6.QtWidgets import QFileDialog
    from src.views.incoming_invoice_interface import IncomingInvoiceDialog, IncomingInvoiceInterface
    path = _pdf(tmp_path / "schulz.pdf", ["Elektro Schulz e.K.", "Rechnung Nr. 2026-0815", "Datum: 05.11.2026",
                                          "Gesamtbetrag: 119,00 EUR"])
    shown = {}

    def accept(dialog):
        shown.update(dialog.get_data())
        return 1
    monkeypatch.setattr(IncomingInvoiceDialog, "exec", accept)
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: ([path], "")))
    monkeypatch.setattr("src.utils.paths.downloads_dir", lambda: str(tmp_path))
    page = IncomingInvoiceInterface(controller, "Lieferant")
    page.upload()
    assert shown["supplier_name"] == "Elektro Schulz e.K." and shown["invoice_number"] == "2026-0815"
    assert shown["date"] == datetime(2026, 11, 5) and shown["amount"] == 119.0
    assert shown["description"] == "Elektro Schulz e.K. 2026-0815"
    stored = controller.get_incoming_invoices("Lieferant")[0]
    assert (stored.supplier_name, stored.invoice_number, stored.amount) == ("Elektro Schulz e.K.", "2026-0815", 119.0)
