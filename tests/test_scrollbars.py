from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication


def test_table_scrollbars_stay_expanded(controller, qapp):
    from src.views.invoice_interface import InvoiceInterface
    from src.views.invoice_editor import InvoiceEditor
    tables = [InvoiceInterface(controller).list_page.table, InvoiceEditor(controller).table]
    for table in tables:
        bar = table.scrollDelagate.vScrollBar
        # Hovering out would normally collapse the bar back to a faint 3 px line
        QApplication.sendEvent(bar, QEvent(QEvent.Leave))
        bar.collapse()
        qapp.processEvents()
        assert bar.groove.opacity == 1
        assert bar.handle.width() == 6
