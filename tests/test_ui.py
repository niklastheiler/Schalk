"""Smoke test of the main workflows through the user interface (dialogs are auto-confirmed)."""
from datetime import datetime, timezone
from PySide6.QtCore import Qt
from qfluentwidgets import RoundMenu


def _menu_texts(page, record):
    menu = RoundMenu()
    page.fill_context_menu(menu, record)
    return [a.text() for a in menu.actions()]


def test_invoice_workflow(window, controller, qapp):
    c, ii = controller, window.invoice_interface
    window.switchTo(ii)
    ii.show_editor()
    ed = ii.editor
    for edit, text in ((ed.companyEdit, "Neukunde KG"), (ed.addressEdit, "Allee 5"), (ed.postalCodeEdit, "80331"),
                       (ed.cityEdit, "München"), (ed.emailEdit, "rechnung@neukunde.de")):
        edit.setText(text)
    ed.add_item_row()
    ed.table.cellWidget(0, 0).setText("Leistung")
    ed.table.cellWidget(0, 3).setText("100,00")
    ed.add_item_row()
    ed.table.cellWidget(1, 0).setText("Buch")
    ed.table.cellWidget(1, 3).setText("10,00")
    ed.table.cellWidget(1, 4).setCurrentIndex(1)
    assert "129,70" in ed.grossTotalLabel.text()
    ed.table.cellWidget(1, 4).setCurrentIndex(2)
    assert ed.exemptionEdit.isVisibleTo(ed)
    ed.save() # no exemption reason -> refused, no customer created
    assert c.get_customers() == []
    ed.exemptionEdit.setText("Steuerfreie Leistung gemäß § 4 UStG")
    ed.save()
    qapp.processEvents()
    assert ii.list_page.model.rowCount() == 1

    invoice = c.get_invoices()[0]
    assert "Entwurf löschen" in _menu_texts(ii.list_page, invoice)
    ii.change_status(invoice.id, "Offen")
    qapp.processEvents()
    invoice = c.get_invoice(invoice.id)
    assert c.is_finalized(invoice) and ii.list_page.model.text(0, 1) == invoice.invoice_number
    assert "Stornieren" in _menu_texts(ii.list_page, c.get_invoices()[0])
    ii.save_pdf(invoice.id)
    ii.export_xrechnung(invoice.id)
    ii.print_pdf(invoice.id)
    assert window.opened[-1][1] == "print"
    c.update_customer(invoice.customer_id, address="Umgezogen 9")
    ii.show_editor(invoice.id)
    assert not ed.saveBtn.isVisibleTo(ed)
    assert ed.addressEdit.text() == "Allee 5" # the issued invoice keeps its recipient

    page = ii.list_page
    page.searchEdit.setText("neukunde")
    page.apply_filters()
    assert page.proxy.rowCount() == 1
    page.table.horizontalHeader().setSortIndicator(3, Qt.DescendingOrder)
    assert page.model.rowCount() == 1


def test_reminders_cashbook_customers(window, controller, qapp):
    c = controller
    customer = c.add_customer(company_name="Alt GmbH", address="A 1", postal_code="1", city="B")
    old = datetime(2025, 1, 1, tzinfo=timezone.utc)
    invoice_id = c.create_invoice(customer, old, old, [{"title": "Alt", "quantity": 1, "unit_price": 10, "tax_percent": 19}], status="Offen")
    c.refresh_overdue()
    ri = window.reminder_interface
    window.switchTo(ri)
    qapp.processEvents()
    assert ri.model.rowCount() == 1
    ri.table.selectRow(0)
    ri.remind_selected()
    assert c.get_invoice(invoice_id).reminder_level == 1
    ri.mark_as_paid(invoice_id)
    qapp.processEvents()
    assert ri.model.rowCount() == 0

    cb = window.cashbook_interface
    window.switchTo(cb)
    cb.amountEdit.setText("250,00")
    cb.add_entry()
    qapp.processEvents()
    assert cb.model.rowCount() == 1 and "250,00" in cb.balanceLabel.text()
    c.finalize_cashbook()
    cb.storno_entry(cb.model.record(0).id)
    qapp.processEvents()
    assert cb.model.rowCount() == 2

    ci = window.customer_interface
    window.switchTo(ci)
    ci.show_editor()
    ci.editor.edits["company_name"].setText("Behörde")
    ci.editor.edits["buyer_reference"].setText("991-1")
    ci.editor.save_customer()
    qapp.processEvents()
    assert any(x.buyer_reference == "991-1" for x in c.get_customers())

    window.switchTo(window.analysis_interface)
    window.switchTo(window.settings_interface)
    qapp.processEvents()
