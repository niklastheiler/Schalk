"""Cashbook: amount, description and type (income/expense) from an attached receipt."""
import shutil
from datetime import date, datetime, timezone
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from src.utils.receipt_recognition import EXPENSE, INCOME, recognize_receipt

DAY = datetime(2026, 11, 3, tzinfo=timezone.utc)
ITEM = [{"title": "Beratung", "quantity": 2, "unit_price": 50.0, "tax_percent": 19.0}] # 119,00 €


def _own_invoice(c):
    customer_id = c.add_customer(company_name="Bäckerei Korn", address="Weg 2", postal_code="20095", city="Hamburg")
    return c.get_invoice(c.create_invoice(customer_id, DAY, DAY, ITEM, status="Offen"))


def _receipt(path, lines):
    pdf = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    for line in lines:
        pdf.drawString(60, y, line)
        y -= 18
    pdf.save()
    return str(path)


def test_archived_own_invoice_is_income(controller, seller, tmp_path):
    invoice = _own_invoice(controller)
    copy = tmp_path / "Rechnung.pdf"
    shutil.copyfile(invoice.pdf_path, copy) # as saved with "PDF speichern"
    guess = recognize_receipt(controller, str(copy))
    assert (guess.entry_type, guess.amount, guess.invoice_id) == (INCOME, 119.0, invoice.id)
    assert guess.description == f"Rechnung {invoice.invoice_number} – Bäckerei Korn"
    assert guess.receipt_date is None # income keeps the date of the cash payment


def test_own_invoice_recognised_by_number_and_name_in_the_text(controller, seller, tmp_path):
    invoice = _own_invoice(controller)
    path = _receipt(tmp_path / "scan.pdf", [seller["company_name"], f"Rechnung Nr. {invoice.invoice_number}", "Gesamtbetrag 119,00 EUR"])
    guess = recognize_receipt(controller, path)
    assert guess.entry_type == INCOME and guess.amount == 119.0 # the whole invoice


def test_foreign_receipt_is_an_expense(controller, seller, tmp_path):
    invoice = _own_invoice(controller)
    # Same number as an own invoice, but from another company: not own
    path = _receipt(tmp_path / "bon.pdf", ["Bürobedarf Schmidt GmbH", "Hafenstr. 3, 20457 Hamburg",
                                           f"Beleg-Nr. {invoice.invoice_number}", "Datum 02.11.2026", "Summe 23,80 EUR"])
    guess = recognize_receipt(controller, path)
    assert (guess.entry_type, guess.amount, guess.receipt_date) == (EXPENSE, 23.80, date(2026, 11, 2))
    assert guess.description == f"Bürobedarf Schmidt GmbH {invoice.invoice_number}"


def test_attaching_fills_the_cashbook_form(controller, seller, tmp_path, monkeypatch, qapp):
    from PySide6.QtWidgets import QFileDialog
    from src.views.cashbook_interface import CashbookInterface
    invoice = _own_invoice(controller)
    page = CashbookInterface(controller)
    monkeypatch.setattr("src.utils.paths.downloads_dir", lambda: str(tmp_path))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (invoice.pdf_path, "")))
    page.typeCombo.setCurrentText(EXPENSE)
    page.attach_file()
    assert page.typeCombo.currentText() == INCOME
    assert page.amountEdit.text() == "119,00" and page.descEdit.text().startswith(f"Rechnung {invoice.invoice_number}")

    # A shop receipt: expense; what the user already typed stays
    page.reset_form()
    page.descEdit.setText("Druckerpapier")
    bon = _receipt(tmp_path / "bon.pdf", ["Bürobedarf Schmidt GmbH", "Datum 02.11.2026", "Summe 23,80 EUR"])
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (bon, "")))
    page.attach_file()
    assert (page.typeCombo.currentText(), page.amountEdit.text(), page.descEdit.text()) == (EXPENSE, "23,80", "Druckerpapier")
    assert page.datePicker.date.toPython() == date(2026, 11, 2)
