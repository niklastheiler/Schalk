"""Back/forward buttons of the mouse, DATEV export buttons greyed out without data, grid lines in the tables."""
from datetime import datetime, timezone
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication
from receipts import RECEIPT

DAY = datetime(2026, 10, 1, tzinfo=timezone.utc)
ITEM = [{"title": "Leistung", "quantity": 1, "unit_price": 100.0, "tax_percent": 19.0}]


def _press(window, button):
    event = QMouseEvent(QEvent.MouseButtonPress, QPointF(5, 5), QPointF(5, 5), button, button, Qt.NoModifier)
    return window._mouse_navigation.eventFilter(window, event)


def test_mouse_back_and_forward_switch_tabs(window, qapp):
    start = window.stackedWidget.currentWidget()
    window.switchTo(window.cashbook_interface)
    window.switchTo(window.customer_interface)
    window.go_back()
    assert window.stackedWidget.currentWidget() is window.cashbook_interface
    window.go_back()
    assert window.stackedWidget.currentWidget() is start
    window.go_back() # nothing further back
    assert window.stackedWidget.currentWidget() is start
    window.go_forward()
    window.go_forward()
    assert window.stackedWidget.currentWidget() is window.customer_interface
    # A new tab after going back drops the forward history
    window.go_back()
    window.switchTo(window.settings_interface)
    window.go_forward()
    assert window.stackedWidget.currentWidget() is window.settings_interface


def test_back_closes_an_open_editor_first(window, qapp):
    invoices = window.invoice_interface
    window.switchTo(window.cashbook_interface)
    window.switchTo(invoices)
    invoices.show_editor()
    window.go_back()
    assert window.stackedWidget.currentWidget() is invoices and invoices.stackedWidget.currentWidget() is invoices.list_page
    window.go_back()
    assert window.stackedWidget.currentWidget() is window.cashbook_interface


def test_mouse_buttons_are_handled_by_the_window(window, qapp, monkeypatch):
    calls = []
    monkeypatch.setattr(window, "go_back", lambda: calls.append("back"))
    monkeypatch.setattr(window, "go_forward", lambda: calls.append("forward"))
    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: window))
    assert _press(window, Qt.BackButton) and _press(window, Qt.ForwardButton)
    assert not _press(window, Qt.LeftButton)
    assert calls == ["back", "forward"]


def test_datev_buttons_are_greyed_out_without_data(window, controller, qapp):
    c = controller
    invoices = window.invoice_interface.list_page
    supplier = window.supplier_invoice_interface
    cashbook = window.cashbook_interface
    for page in (invoices, supplier, cashbook):
        page.refresh()
        assert not page.datevButton.isEnabled() and page.datevButton.toolTip()
    customer_id = c.add_customer(company_name="Kunde AG", address="Weg 2", postal_code="20095", city="Hamburg")
    paid = c.create_invoice(customer_id, DAY, DAY, ITEM, status="Offen")
    c.update_invoice_status(paid, "Bezahlt")
    invoices.refresh()
    assert invoices.datevButton.isEnabled()
    c.add_incoming_invoice("Lieferant", datetime(2026, 11, 5), 10.0, "X", RECEIPT)
    supplier.refresh()
    assert supplier.datevButton.isEnabled()
    c.add_cashbook_entry(datetime(2026, 11, 2), 50.0, "Einlage", "A", "Einnahme", 0, attachment_source=RECEIPT)
    cashbook.refresh()
    assert not cashbook.datevButton.isEnabled() # a draft is not exported
    c.finalize_cashbook()
    cashbook.refresh()
    assert cashbook.datevButton.isEnabled()
    c.storno_cashbook_entry(c.get_cashbook_entries()[0].id)
    cashbook.refresh()
    assert not cashbook.datevButton.isEnabled() # cancelled: nothing left for DATEV


def test_tables_show_grid_lines(window, qapp):
    from src.views.common import GRID_COLOR, GridTableView
    for page in (window.invoice_interface.list_page, window.customer_interface.list_page, window.cashbook_interface,
                 window.supplier_invoice_interface, window.quote_interface.list_page, window.reminder_interface):
        assert isinstance(page.table, GridTableView) and page.table.showGrid() and GRID_COLOR
