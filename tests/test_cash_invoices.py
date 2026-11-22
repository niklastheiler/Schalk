"""Cash income for own invoices (drop-down, payment on finalizing), receipt by type, quotes without archiving, closing."""
from datetime import datetime, timezone
import pytest
from qfluentwidgets import RoundMenu
from src.controllers.db_controller import GoBDError

ITEM = [{"title": "Leistung", "quantity": 1, "unit_price": 100.0, "tax_percent": 19.0}] # 119,00 €


def _this_month_invoice(c, status="Offen"):
    today = datetime.now(timezone.utc)
    customer_id = c.add_customer(company_name="Bäckerei Korn", address="Weg 2", postal_code="20095", city="Hamburg")
    return c.create_invoice(customer_id, today, today, ITEM, status=status)


def test_cash_income_pays_the_invoice_when_finalized(controller, seller):
    c = controller
    invoice_id = _this_month_invoice(c)
    assert [i.id for i in c.cash_invoices()] == [invoice_id]
    with pytest.raises(ValueError, match="offenen Betrag"):
        c.add_cashbook_entry(datetime.now(), 50.0, "Teil", "A", "Einnahme", 19, invoice_id=invoice_id)
    with pytest.raises(ValueError, match="Einnahme"):
        c.add_cashbook_entry(datetime.now(), 119.0, "x", "A", "Barentnahme Firma", 19, invoice_id=invoice_id)
    entry_id = c.add_cashbook_entry(datetime.now(), 119.0, "Rechnung bar", "A", "Einnahme", 19, invoice_id=invoice_id)
    with pytest.raises(ValueError, match="schon einen Kassenbuch-Entwurf"):
        c.add_cashbook_entry(datetime.now(), 119.0, "doppelt", "A", "Einnahme", 19, invoice_id=invoice_id)
    assert c.get_invoice_header(invoice_id).status == "Offen" # a draft is no payment yet

    c.finalize_cashbook()
    invoice = c.get_invoice_header(invoice_id)
    assert invoice.status == "Bezahlt" and invoice.paid_at.date() == datetime.now().date()
    receipt = c.get_cashbook_entry(entry_id).receipt_number
    assert any(receipt in h.action for h in c.get_document_history("Invoice", invoice_id))
    assert c.cash_invoices() == [] # paid: no longer offered
    assert c.verify_integrity(check_files=False) == []

    # Cancelling the cash entry takes the payment back
    c.storno_cashbook_entry(entry_id)
    invoice = c.get_invoice_header(invoice_id)
    assert invoice.status == "Offen" and not invoice.paid_amount and invoice.paid_at is None
    assert c.verify_integrity(check_files=False) == []


def test_finalizing_fails_as_a_whole_if_the_invoice_was_paid_meanwhile(controller, seller):
    c = controller
    invoice_id = _this_month_invoice(c)
    c.add_cashbook_entry(datetime.now(), 119.0, "Rechnung bar", "A", "Einnahme", 19, invoice_id=invoice_id)
    c.record_payment(invoice_id, datetime.now()) # paid by bank transfer in the meantime
    with pytest.raises(GoBDError, match="bereits bezahlt"):
        c.finalize_cashbook()
    assert c.cashbook_draft_count() == 1 # nothing sealed


def test_cashbook_form_by_type(controller, seller, qapp):
    from src.views.cashbook_interface import CashbookInterface
    c = controller
    invoice_id = _this_month_invoice(c)
    page = CashbookInterface(c)
    page.typeCombo.setCurrentText("Barentnahme Firma")
    assert page.attachBox.isVisibleTo(page) and not page.invoiceBox.isVisibleTo(page)
    page.attachment_path = "C:/beleg.pdf"
    page.typeCombo.setCurrentText("Barentnahme Privat")
    assert not page.attachBox.isVisibleTo(page) and page.attachment_path == "" # no receipt for private withdrawals
    page.typeCombo.setCurrentText("Einnahme")
    assert page.invoiceBox.isVisibleTo(page) and page.attachBox.isVisibleTo(page) # receipt required for income too
    assert page.invoiceCombo.itemText(0) == "Ohne Rechnung" and page.invoiceCombo.itemData(1) == invoice_id

    page.invoiceCombo.setCurrentIndex(1)
    invoice = c.get_invoice_header(invoice_id)
    assert page.amountEdit.text() == "119,00" and page.descEdit.text() == f"Rechnung {invoice.invoice_number} – Bäckerei Korn"
    assert page.attachment_path == invoice.pdf_path # the invoice itself is the receipt
    page.add_entry()
    entry = c.get_cashbook_entries()[0]
    assert entry.invoice_id == invoice_id and entry.attachment_hash == invoice.pdf_hash
    c.finalize_cashbook()
    assert c.get_invoice_header(invoice_id).status == "Bezahlt"


def test_quotes_have_no_archive_entry(window, controller, qapp):
    today = datetime.now(timezone.utc)
    customer_id = controller.add_customer(company_name="Kunde AG")
    quote_id = controller.create_quote(customer_id, today, ITEM)
    menu = RoundMenu()
    window.quote_interface.list_page.fill_context_menu(menu, controller.get_quote(quote_id))
    texts = [a.text() for a in menu.actions()]
    assert "Archivieren" not in texts and "Löschen" in texts


def test_closing_with_unsaved_input_asks(window, qapp, monkeypatch):
    import src.views.main_window as module
    from PySide6.QtGui import QCloseEvent
    answers = [False]
    monkeypatch.setattr(module, "ask_discard_changes", lambda parent: answers.pop(0))
    window.switchTo(window.cashbook_interface)
    window.cashbook_interface.amountEdit.setText("5,00")
    event = QCloseEvent()
    window.closeEvent(event)
    assert not event.isAccepted() and window.cashbook_interface.amountEdit.text() == "5,00"


def test_receipt_is_required_for_income_and_business_withdrawals(controller, seller):
    from receipts import RECEIPT
    c = controller
    for entry_type in ("Einnahme", "Barentnahme Firma"):
        with pytest.raises(ValueError, match="Beleg Pflicht"):
            c.add_cashbook_entry(datetime(2026, 11, 2), 10.0, "ohne", "A", entry_type, 19)
    income = c.add_cashbook_entry(datetime(2026, 11, 2), 50.0, "Einlage", "A", "Einnahme", 19, attachment_source=RECEIPT)
    c.add_cashbook_entry(datetime(2026, 11, 3), 5.0, "Privat", "A", "Barentnahme Privat", 0) # no receipt needed
    # Editing keeps the receipt; an invoice's PDF is its receipt
    c.update_cashbook_entry(income, datetime(2026, 11, 2), 60.0, "Einlage", "Einnahme")
    assert c.get_cashbook_entry(income).attachment_hash
    invoice_id = _this_month_invoice(c)
    entry = c.add_cashbook_entry(datetime.now(), 119.0, "Rechnung bar", "A", "Einnahme", 19, invoice_id=invoice_id)
    assert c.get_cashbook_entry(entry).attachment_hash == c.get_invoice_header(invoice_id).pdf_hash


def test_form_receipt_next_to_a_short_description(controller, seller, qapp):
    from src.views.cashbook_interface import CashbookInterface
    page = CashbookInterface(controller)
    page.resize(1200, 500)
    page.show()
    qapp.processEvents()
    assert page.descEdit.width() <= 375
    for entry_type, receipt, invoice in (("Einnahme", True, True), ("Barentnahme Firma", True, False),
                                         ("Barentnahme Privat", False, False)):
        page.typeCombo.setCurrentText(entry_type)
        assert page.attachBox.isVisibleTo(page) == receipt and page.invoiceBox.isVisibleTo(page) == invoice
    page.typeCombo.setCurrentText("Einnahme")
    # The receipt field sits right after the description
    assert 0 < page.attachBox.x() - (page.descEdit.mapTo(page, page.descEdit.rect().topRight()).x()) < 40
    page.amountEdit.setText("10,00")
    page.add_entry() # neither invoice nor receipt: refused
    assert controller.get_cashbook_entries() == []
