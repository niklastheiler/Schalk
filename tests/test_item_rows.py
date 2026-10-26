from datetime import datetime, timezone
from PySide6.QtCore import QEvent, QObject
from src.views.document_editor import COL_DELETE, ITEM_WIDGET_HEIGHT


class WindowSpy(QObject):
    """Records every widget that is shown as its own window, even if only for a moment."""

    def __init__(self, ignore):
        super().__init__()
        self.ignore = ignore
        self.windows = []

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Show and obj.isWidgetType() and obj.isWindow() and obj is not self.ignore:
            self.windows.append(type(obj).__name__)
        return False


def test_adding_and_loading_items_opens_no_extra_window(controller, seller, qapp):
    from src.views.invoice_editor import InvoiceEditor
    editor = InvoiceEditor(controller)
    editor.show()
    qapp.processEvents()
    spy = WindowSpy(editor)
    qapp.installEventFilter(spy)
    try:
        editor.add_item_row()
        # Loading an invoice (double click in the list) builds all rows the same way
        customer_id = controller.add_customer(company_name="Kunde", address="A 1", postal_code="1", city="B")
        day = datetime(2026, 10, 1, tzinfo=timezone.utc)
        items = [{"title": f"Pos {i}", "quantity": 1, "unit_price": 1, "tax_percent": 19} for i in range(5)]
        editor.load_invoice(controller.create_invoice(customer_id, day, day, items))
        qapp.processEvents()
    finally:
        qapp.removeEventFilter(spy)
    assert spy.windows == []


def test_all_fields_of_a_row_have_the_same_height(controller, qapp):
    from src.views.invoice_editor import InvoiceEditor
    editor = InvoiceEditor(controller)
    editor.show()
    editor.add_item_row()
    qapp.processEvents()
    heights = {editor.table.cellWidget(0, col).height() for col in range(COL_DELETE + 1)}
    assert heights == {ITEM_WIDGET_HEIGHT}
