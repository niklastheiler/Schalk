from src.views.invoice_editor import InvoiceEditor


def test_dropdown_lists_all_customers_and_selects_one(controller, qapp):
    for name in ("Alpha GmbH", "Beta AG", "Gamma KG"):
        controller.add_customer(company_name=name, city="Berlin")
    editor = InvoiceEditor(controller)
    editor.clear_form()
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
