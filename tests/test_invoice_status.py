from datetime import datetime, timezone
from PySide6.QtWidgets import QStyleOptionViewItem
from qfluentwidgets import ComboBox, MessageBox

DAY = datetime(2026, 10, 1, tzinfo=timezone.utc)
ITEM = [{"title": "Leistung", "quantity": 1, "unit_price": 100.0, "tax_percent": 19.0}]


def _invoice(controller, status="Entwurf"):
    customer_id = controller.add_customer(company_name="Kunde", address="A 1", postal_code="1", city="B")
    return controller.create_invoice(customer_id, DAY, DAY, ITEM, status=status)


def test_only_sensible_next_statuses(controller, seller):
    c = controller
    invoice_id = _invoice(c)
    assert c.next_invoice_statuses(c.get_invoice(invoice_id)) == ["Offen"]
    ok, message = c.update_invoice_status(invoice_id, "Bezahlt")
    assert not ok and "nicht vorgesehen" in message
    assert c.update_invoice_status(invoice_id, "Offen")[0]
    assert c.next_invoice_statuses(c.get_invoice(invoice_id)) == ["Teilbezahlt", "Bezahlt", "Storniert"]
    assert c.update_invoice_status(invoice_id, "Bezahlt")[0]
    assert c.next_invoice_statuses(c.get_invoice(invoice_id)) == ["Offen"] # payment taken back
    assert c.update_invoice_status(invoice_id, "Offen")[0]
    assert c.update_invoice_status(invoice_id, "Storniert")[0]
    assert c.next_invoice_statuses(c.get_invoice(invoice_id)) == []
    storno = next(i for i in c.get_invoices() if i.cancels_invoice_id == invoice_id)
    assert c.next_invoice_statuses(storno) == []


def test_status_dropdown_in_the_list(controller, seller, qapp, monkeypatch):
    monkeypatch.setattr(MessageBox, "exec", lambda self: 1)
    from src.views.invoice_interface import InvoiceInterface
    invoice_id = _invoice(controller)
    interface = InvoiceInterface(controller)
    interface.resize(1200, 600)
    interface.show()
    qapp.processEvents()
    page = interface.list_page
    status_column = [c.title for c in page.model.columns].index("Status")
    index = page.proxy.index(0, status_column)
    page._on_cell_clicked(index)
    qapp.processEvents()
    combo = page.table.indexWidget(index) or next(w for w in page.table.viewport().findChildren(ComboBox) if w.isVisible())
    assert [combo.itemText(i) for i in range(combo.count())] == ["Entwurf", "Offen"]
    # The cell text must not shine through the open (semi-transparent) combo box
    delegate = page.table.itemDelegateForColumn(status_column)
    option = QStyleOptionViewItem()
    delegate.initStyleOption(option, index)
    assert option.text == ""
    combo.setCurrentIndex(1) # choose "Offen"
    for _ in range(5):
        qapp.processEvents()
    invoice = controller.get_invoice(invoice_id)
    assert invoice.status == "Offen" and controller.is_finalized(invoice)
    option = QStyleOptionViewItem()
    delegate.initStyleOption(option, page.proxy.index(0, status_column))
    assert option.text == "Offen" # shown again once the combo box is closed
    # A cancelled invoice offers no drop-down
    controller.update_invoice_status(invoice_id, "Storniert")
    qapp.processEvents()
    row = next(r for r in range(page.proxy.rowCount()) if page.model.text(page.proxy.mapToSource(page.proxy.index(r, 0)).row(), 1) == invoice.invoice_number)
    assert not (page.proxy.index(row, status_column).flags() & page.proxy.index(row, status_column).flags().ItemIsEditable)
