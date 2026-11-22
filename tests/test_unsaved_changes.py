"""Question before leaving a tab with unsaved input; centered table cells; no delete button on issued invoices."""
from datetime import datetime, timezone
import pytest
from PySide6.QtCore import Qt
import src.views.main_window as main_window_module

DAY = datetime(2026, 11, 3, tzinfo=timezone.utc)
ITEM = [{"title": "Leistung", "quantity": 1, "unit_price": 100.0, "tax_percent": 19.0}]


@pytest.fixture
def answers(monkeypatch):
    """Answers of the question, in order (True = discard, False = stay); records every question asked."""
    asked = []
    queue = []

    def ask(parent):
        asked.append(parent)
        return queue.pop(0)
    monkeypatch.setattr(main_window_module, "ask_discard_changes", ask)
    for module in ("src.views.invoice_interface", "src.views.quote_interface", "src.views.customer_interface"):
        monkeypatch.setattr(f"{module}.ask_discard_changes", ask)
    return queue, asked


def test_unsaved_invoice_asks_before_switching_tabs(window, qapp, answers):
    queue, asked = answers
    invoices = window.invoice_interface
    window.switchTo(invoices)
    invoices.show_editor()
    assert window.switchTo(window.cashbook_interface) and not asked # nothing typed: no question
    window.switchTo(invoices)
    invoices.show_editor()
    invoices.editor.companyEdit.setText("Neuer Kunde GmbH")

    queue.append(False) # stay
    assert not window.switchTo(window.cashbook_interface)
    assert window.stackedWidget.currentWidget() is invoices and invoices.stackedWidget.currentWidget() is invoices.editor
    assert invoices.editor.companyEdit.text() == "Neuer Kunde GmbH"

    queue.append(True) # discard
    assert window.switchTo(window.cashbook_interface)
    assert window.stackedWidget.currentWidget() is window.cashbook_interface
    assert invoices.stackedWidget.currentWidget() is invoices.list_page and invoices.editor.companyEdit.text() == ""
    assert len(asked) == 2


def test_new_item_row_and_back_arrow_count_too(window, qapp, answers):
    queue, asked = answers
    quotes = window.quote_interface
    window.switchTo(quotes)
    quotes.show_editor()
    quotes.editor.add_item_row()
    queue.append(False)
    # The back arrow switches the stacked widget directly: it is guarded as well
    window.stackedWidget.setCurrentWidget(window.invoice_interface)
    assert window.stackedWidget.currentWidget() is quotes and len(asked) == 1
    queue.append(True)
    quotes.leave_editor() # "Zurück" inside the tab asks as well
    assert quotes.stackedWidget.currentWidget() is quotes.list_page and len(asked) == 2


def test_issued_invoice_is_read_only_and_never_asks(window, controller, qapp, answers):
    _, asked = answers
    customer_id = controller.add_customer(company_name="Kunde AG", address="Weg 2", postal_code="20095", city="Hamburg")
    issued = controller.create_invoice(customer_id, DAY, DAY, ITEM, status="Offen")
    draft = controller.create_invoice(customer_id, DAY, DAY, ITEM)
    invoices = window.invoice_interface
    window.switchTo(invoices)
    from src.views.document_editor import COL_DELETE
    invoices.show_editor(issued)
    assert invoices.editor.table.isColumnHidden(COL_DELETE) # no "X" on an issued invoice
    assert window.switchTo(window.customer_interface) and not asked
    window.switchTo(invoices)
    invoices.show_editor(draft)
    assert not invoices.editor.table.isColumnHidden(COL_DELETE)


def test_cashbook_form_and_settings(window, qapp, answers):
    queue, asked = answers
    cashbook = window.cashbook_interface
    window.switchTo(cashbook)
    cashbook.amountEdit.setText("12,50")
    queue.append(True)
    assert window.switchTo(window.settings_interface) and len(asked) == 1
    assert cashbook.amountEdit.text() == ""

    settings = window.settings_interface
    qapp.processEvents()
    original = settings.edits["city"].text()
    settings.edits["city"].setText("Woanders")
    queue.append(False)
    assert not window.switchTo(cashbook)
    queue.append(True)
    assert window.switchTo(cashbook) and settings.edits["city"].text() == original
    # The search field of a list is no unsaved input
    cashbook.searchEdit.setText("Porto")
    assert window.switchTo(window.invoice_interface) and len(asked) == 3


def test_open_invoice_from_reminders_does_not_drop_a_draft_in_the_editor(window, controller, qapp, answers):
    queue, asked = answers
    customer_id = controller.add_customer(company_name="Kunde AG", address="Weg 2", postal_code="20095", city="Hamburg")
    issued = controller.create_invoice(customer_id, DAY, DAY, ITEM, status="Offen")
    invoices = window.invoice_interface
    window.switchTo(invoices)
    invoices.show_editor()
    invoices.editor.companyEdit.setText("Halb fertig")
    queue.append(True) # leave the invoice tab, discarding
    window.switchTo(window.reminder_interface)
    window.open_invoice(issued)
    assert invoices.editor.current_id == issued and len(asked) == 1


def test_all_list_cells_are_centered(window, controller, qapp):
    customer_id = controller.add_customer(company_name="Kunde AG", address="Weg 2", postal_code="20095", city="Hamburg")
    controller.create_invoice(customer_id, DAY, DAY, ITEM)
    for page in (window.invoice_interface.list_page, window.quote_interface.list_page, window.cashbook_interface,
                 window.reminder_interface, window.customer_interface.list_page, window.supplier_invoice_interface):
        page.refresh()
        assert all(column.align == Qt.AlignCenter for column in page.model.columns), page
    page = window.invoice_interface.list_page
    assert all(page.proxy.index(0, col).data(Qt.TextAlignmentRole) == int(Qt.AlignCenter)
               for col in range(len(page.model.columns)))


def test_reordered_fields_are_no_change(window, qapp):
    """Clicking a field can raise() it, which reorders its parent's children: that alone is no change."""
    settings = window.settings_interface
    window.switchTo(settings)
    qapp.processEvents()
    assert not settings.has_unsaved_changes()
    for edit in settings.edits.values():
        edit.raise_()
    settings.edits["company_name"].lower()
    assert not settings.has_unsaved_changes()
    settings.edits["city"].setText("Woanders")
    assert settings.has_unsaved_changes()
