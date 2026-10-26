from src.views.invoice_editor import InvoiceEditor

ITEM_TEXT = "Leistung"


def _editor(controller):
    editor = InvoiceEditor(controller)
    editor.clear_form()
    editor.add_item_row()
    editor.table.cellWidget(0, 0).setText(ITEM_TEXT)
    editor.table.cellWidget(0, 3).setText("10,00")
    return editor


def _choose(editor, name):
    label = next(label for label in editor._customer_entries if label.startswith(name))
    editor._on_customer_chosen(label)


def test_new_customer_from_invoice_editor_is_listed(controller, qapp):
    editor = _editor(controller)
    editor.companyEdit.setText("Neukunde GmbH")
    assert editor.customerHint.text() == "Neuer Kunde wird beim Speichern angelegt"
    editor.save()
    assert [c.display_name for c in controller.get_customers()] == ["Neukunde GmbH"]


def test_overwriting_the_name_of_a_chosen_customer_creates_a_new_one(controller, qapp):
    controller.add_customer(company_name="Bestandskunde AG", city="Berlin")
    editor = _editor(controller)
    _choose(editor, "Bestandskunde AG")
    assert editor.customerHint.text().startswith("Bestehender Kunde: Bestandskunde AG")
    editor.companyEdit.setText("Zweitkunde AG")
    assert editor.customerHint.text() == "Neuer Kunde wird beim Speichern angelegt"
    editor.save()
    assert sorted(c.display_name for c in controller.get_customers()) == ["Bestandskunde AG", "Zweitkunde AG"]


def test_address_change_updates_the_chosen_customer(controller, qapp):
    customer_id = controller.add_customer(company_name="Bestandskunde AG", city="Berlin")
    editor = _editor(controller)
    _choose(editor, "Bestandskunde AG")
    editor.cityEdit.setText("Hamburg")
    editor.save()
    assert len(controller.get_customers()) == 1 and controller.get_customer(customer_id).city == "Hamburg"


def test_typing_in_the_search_field_deselects_the_customer(controller, qapp):
    controller.add_customer(company_name="Bestandskunde AG")
    editor = _editor(controller)
    _choose(editor, "Bestandskunde AG")
    editor.customerSearch.textEdited.emit("Ganz anderer Kunde")
    assert editor.customer_id is None


def test_dropdown_lists_all_customers_and_selects_one(controller, qapp):
    for name in ("Alpha GmbH", "Beta AG", "Gamma KG"):
        controller.add_customer(company_name=name, city="Berlin")
    editor = _editor(controller)
    editor.show()
    editor.customerDropdownBtn.click()
    menu = editor.customerSearch._completerMenu
    assert [menu.view.item(i).text().split(" – ")[0] for i in range(menu.view.count())] == ["Alpha GmbH", "Beta AG", "Gamma KG"]
    menu._onItemClicked(menu.view.item(1))
    assert editor.companyEdit.text() == "Beta AG" and editor.customer_id is not None
    # Typing still filters (search behaviour unchanged)
    editor.customerSearch.setText("gam")
    editor.customerSearch._showCompleterMenu()
    assert [menu.view.item(i).text().split(" – ")[0] for i in range(menu.view.count())] == ["Gamma KG"]
