from datetime import datetime, timezone
from PySide6.QtCore import Qt

DAY = datetime(2026, 10, 1, tzinfo=timezone.utc)


def test_rocket_turns_quote_into_invoice(window, controller, qapp, monkeypatch):
    import src.views.quote_interface as module
    answers = [False, True]
    monkeypatch.setattr(module, "confirm", lambda *a: answers.pop(0))
    customer_id = controller.add_customer(company_name="Muster GmbH")
    controller.create_quote(customer_id, DAY, [{"title": "Beratung", "quantity": 2, "unit_price": 80, "tax_percent": 19}])
    window.switchTo(window.quote_interface)
    page = window.quote_interface.list_page
    qapp.processEvents()

    rocket = len(page.model.columns) - 1
    index = page.proxy.index(0, rocket)
    assert page.proxy.data(index) == "" and page.proxy.data(index, Qt.ToolTipRole) == "In Rechnung umwandeln"
    page._on_cell_clicked(index) # cancelled in the confirmation
    assert controller.get_invoices() == []

    page._on_cell_clicked(index)
    qapp.processEvents()
    invoices = controller.get_invoices()
    assert len(invoices) == 1 and invoices[0].status == "Entwurf"
    assert [i.title for i in controller.get_invoice(invoices[0].id).items] == ["Beratung"]
    assert window.stackedWidget.currentWidget() is window.invoice_interface
