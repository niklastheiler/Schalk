from datetime import datetime, timezone
import pytest
from src.controllers.db_controller import NO_ITEMS_MESSAGE

DAY = datetime(2026, 10, 1, tzinfo=timezone.utc)
ITEM = [{"title": "Leistung", "quantity": 1, "unit_price": 10.0, "tax_percent": 19.0}]


def test_controller_refuses_documents_without_items(controller):
    c = controller
    customer_id = c.add_customer(company_name="Kunde")
    with pytest.raises(ValueError, match=NO_ITEMS_MESSAGE):
        c.create_invoice(customer_id, DAY, DAY, [])
    with pytest.raises(ValueError, match=NO_ITEMS_MESSAGE):
        c.create_quote(customer_id, DAY, [])
    invoice_id = c.create_invoice(customer_id, DAY, DAY, ITEM)
    quote_id = c.create_quote(customer_id, DAY, ITEM)
    with pytest.raises(ValueError, match=NO_ITEMS_MESSAGE):
        c.update_invoice(invoice_id, customer_id, DAY, DAY, [])
    with pytest.raises(ValueError, match=NO_ITEMS_MESSAGE):
        c.update_quote(quote_id, customer_id, DAY, [])
    assert len(c.get_invoice(invoice_id).items) == 1 and len(c.get_quote(quote_id).items) == 1


@pytest.mark.parametrize("editor_class", ["InvoiceEditor", "QuoteEditor"])
def test_save_button_disabled_without_items(controller, qapp, editor_class):
    from src.views.invoice_editor import InvoiceEditor
    from src.views.quote_editor import QuoteEditor
    editor = {"InvoiceEditor": InvoiceEditor, "QuoteEditor": QuoteEditor}[editor_class](controller)
    editor.clear_form()
    assert not editor.saveBtn.isEnabled()
    editor.add_item_row() # an empty row without title does not count
    assert not editor.saveBtn.isEnabled()
    editor.table.cellWidget(0, 0).setText("Leistung")
    assert editor.saveBtn.isEnabled()
    editor._delete_row(editor.table.cellWidget(0, 0))
    assert not editor.saveBtn.isEnabled() and editor.saveBtn.toolTip() == NO_ITEMS_MESSAGE
