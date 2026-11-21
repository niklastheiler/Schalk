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
                       (ed.cityEdit, "München")):
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
    # E-mail (needed for XRechnung) is maintained in the customer master, not in the invoice form
    c.update_customer(invoice.customer_id, email="rechnung@neukunde.de")
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


def test_german_thousands_separator_in_prices(window, qapp):
    # "1.500" is one thousand five hundred in German, not 1,50 €
    ii = window.invoice_interface
    window.switchTo(ii)
    ii.show_editor()
    ed = ii.editor
    ed.add_item_row()
    ed.table.cellWidget(0, 0).setText("Maschine")
    ed.table.cellWidget(0, 3).setText("1.500")
    assert ed.collect_items()[0]["unit_price"] == 1500.0 and "1.785,00" in ed.grossTotalLabel.text()
    ed.table.cellWidget(0, 3).setText("12,5")
    assert ed.collect_items()[0]["unit_price"] == 12.5


def test_documents_open_safely(window, tmp_path, monkeypatch):
    import os
    from src.views.common import open_document
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    script = tmp_path / "rechnung.bat"
    script.write_bytes(b"%PDF-1.4\r\ncalc")
    assert not open_document(window, str(script)) and not open_document(window, str(tmp_path / "fehlt.pdf"))
    assert window.opened == []

    # Microsoft Edge as PDF viewer has no "print" command: the PDF is opened for printing instead
    calls = []

    def startfile(path, operation=None):
        calls.append(operation)
        if operation == "print":
            raise OSError(1155, "Keine Anwendung zugeordnet")
    monkeypatch.setattr(os, "startfile", startfile, raising=False)
    assert open_document(window, str(pdf), print_document=True) and calls == ["print", None]

    def no_viewer(path, operation=None):
        raise OSError(1155, "Keine Anwendung zugeordnet")
    monkeypatch.setattr(os, "startfile", no_viewer, raising=False)
    assert not open_document(window, str(pdf)) # reported to the user, no crash


def test_customer_data_is_checked(window, controller, qapp):
    ci = window.customer_interface
    window.switchTo(ci)
    ci.show_editor()
    ed = ci.editor
    ed.edits["company_name"].setText("Client SARL")
    ed.edits["vat_id"].setText("FR 123")
    ed.save_customer()
    assert controller.get_customers() == []
    ed.edits["vat_id"].setText("fr40303265045")
    ed.edits["email"].setText("keine-adresse")
    ed.save_customer()
    assert controller.get_customers() == []
    ed.edits["email"].setText("compta@client.fr")
    ed.save_customer()
    assert [(c.vat_id, c.email) for c in controller.get_customers()] == [("FR40303265045", "compta@client.fr")]


def test_backup_is_created_in_the_background(window, controller, qapp, data_dir):
    import time
    si = window.settings_interface
    window.switchTo(si)
    si.export_backup()
    # The password dialog is auto-confirmed; packing runs on a worker thread and reports back
    deadline = time.monotonic() + 30
    while not si.exportBtn.isEnabled() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    target = next(data_dir.glob("Schalk_Backup_*.backup"), None)
    assert si.exportBtn.isEnabled() and target is not None and target.stat().st_size > 0


def test_invoice_editor_service_period(window, controller, qapp):
    from PySide6.QtCore import QDate
    ii = window.invoice_interface
    window.switchTo(ii)
    ii.show_editor()
    ed = ii.editor
    assert not ed.deliveryEndDate.isVisibleTo(ed)
    ed.companyEdit.setText("Privat")
    ed.add_item_row()
    ed.table.cellWidget(0, 0).setText("Gartenpflege")
    ed.table.cellWidget(0, 3).setText("100,00")
    ed.deliveryDate.setDate(QDate(2026, 10, 1))
    ed.periodCheck.setChecked(True)
    assert ed.deliveryEndDate.isVisibleTo(ed) and ed.deliveryLabel.text() == "Leistung von"
    ed.deliveryEndDate.setDate(QDate(2026, 10, 31))
    ed.save()
    qapp.processEvents()
    invoice = controller.get_invoice(controller.get_invoices()[0].id)
    assert invoice.delivery_end_date.day == 31
    ii.show_editor(invoice.id)
    assert ed.periodCheck.isChecked()
