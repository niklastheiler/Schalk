from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea
from src.views.common import SCROLLBAR_STYLE


def test_tables_use_classic_visible_scrollbars(controller, qapp):
    from src.views.invoice_editor import InvoiceEditor
    from src.views.invoice_interface import InvoiceInterface
    for table in (InvoiceInterface(controller).list_page.table, InvoiceEditor(controller).table):
        assert table.scrollDelagate.vScrollBar._isForceHidden
        assert table.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded
        assert table.verticalScrollBar().styleSheet() == SCROLLBAR_STYLE


def test_list_scrollbar_shows_with_many_rows(controller, qapp):
    from datetime import datetime, timezone
    from src.views.invoice_interface import InvoiceInterface
    customer_id = controller.add_customer(company_name="Kunde")
    day = datetime(2026, 10, 1, tzinfo=timezone.utc)
    for i in range(40):
        controller.create_invoice(customer_id, day, day, [{"title": "X", "quantity": 1, "unit_price": 10, "tax_percent": 19}])
    page = InvoiceInterface(controller)
    page.resize(1000, 500)
    page.show()
    qapp.processEvents()
    assert page.list_page.table.verticalScrollBar().isVisible()


def test_editor_and_settings_pages_scroll(controller, qapp):
    from src.views.invoice_editor import InvoiceEditor
    from src.views.settings_interface import SettingsInterface
    editor = InvoiceEditor(controller)
    assert editor.findChild(QScrollArea) is not None
    editor.resize(1200, 500) # smaller than the content
    editor.show()
    qapp.processEvents()
    assert editor.findChild(QScrollArea).verticalScrollBar().isVisible()
    settings = SettingsInterface(controller)
    assert all(isinstance(settings.stackedWidget.widget(i), QScrollArea) for i in range(settings.stackedWidget.count()))
