"""PDF symbol next to the status (save invoices, quotes, reminders without opening a PDF program), no "Archivieren" menu entry, DATEV export filter."""
from datetime import datetime, timezone
from PySide6.QtCore import Qt
from qfluentwidgets import RoundMenu
from src.utils.datev_generator import DatevGenerator

DAY = datetime(2026, 10, 1, tzinfo=timezone.utc)
ITEM = [{"title": "Leistung", "quantity": 1, "unit_price": 100.0, "tax_percent": 19.0}]


def _customer(c):
    return c.add_customer(company_name="Kunde AG", address="Weg 2", postal_code="20095", city="Hamburg")


def _pdf_index(page, record_id):
    column = next(i for i, c in enumerate(page.model.columns) if c.icon_svg and "PDF" in c.icon_svg)
    row = next(r for r in range(page.proxy.rowCount()) if page.proxy.index(r, 0).data(Qt.UserRole + 1).id == record_id)
    return page.proxy.index(row, column)


def test_invoice_pdf_symbol_saves_only_finalized_invoices(window, controller, data_dir, qapp):
    c = controller
    customer_id = _customer(c)
    draft = c.create_invoice(customer_id, DAY, DAY, ITEM)
    issued = c.create_invoice(customer_id, DAY, DAY, ITEM, status="Offen")
    window.switchTo(window.invoice_interface)
    page = window.invoice_interface.list_page
    page.refresh()
    qapp.processEvents()
    columns = [col.title for col in page.model.columns]
    pdf = _pdf_index(page, draft).column()
    assert pdf == columns.index("Status") + 1 # right next to the status

    index = _pdf_index(page, draft)
    assert "Festschreiben" in index.data(Qt.ToolTipRole)
    page._on_cell_clicked(index) # greyed out: nothing happens
    assert window.opened == []

    index = _pdf_index(page, issued)
    assert index.data(Qt.ToolTipRole) == "PDF speichern unter …"
    page._on_cell_clicked(index) # only the "Speichern unter" dialog (patched: saves on the desktop)
    number = c.get_invoice_header(issued).invoice_number
    saved = data_dir / f"Rechnung_{number}.pdf"
    assert saved.read_bytes() == open(c.get_invoice_header(issued).pdf_path, "rb").read()
    assert window.opened == [] # no PDF program


def test_no_archive_entry_in_the_invoice_menu(window, controller, qapp):
    invoice_id = controller.create_invoice(_customer(controller), DAY, DAY, ITEM)
    page = window.invoice_interface.list_page
    for record_id in (invoice_id, controller.create_invoice(_customer(controller), DAY, DAY, ITEM, status="Offen")):
        menu = RoundMenu()
        page.fill_context_menu(menu, controller.get_invoice_header(record_id))
        assert "Archivieren" not in [a.text() for a in menu.actions()]


def test_quote_and_reminder_pdf_symbols(window, controller, data_dir, qapp):
    c = controller
    customer_id = _customer(c)
    quote_id = c.create_quote(customer_id, DAY, ITEM)
    window.switchTo(window.quote_interface)
    qapp.processEvents()
    page = window.quote_interface.list_page
    page._on_cell_clicked(_pdf_index(page, quote_id))
    quote = c.get_quote(quote_id)
    assert (data_dir / f"Angebot_{quote.quote_number}.pdf").read_bytes().startswith(b"%PDF")

    invoice_id = c.create_invoice(customer_id, DAY, DAY, ITEM, status="Offen") # overdue since 15.10.2026
    window.switchTo(window.reminder_interface)
    qapp.processEvents()
    page = window.reminder_interface
    page.refresh()
    qapp.processEvents()
    opened = len(window.opened)
    index = _pdf_index(page, invoice_id)
    assert index.data(Qt.ToolTipRole) == "Noch keine Mahnung erstellt"
    page._on_cell_clicked(index)
    assert len(window.opened) == opened # no reminder yet: greyed out
    c.record_reminder(invoice_id, 1)
    page.refresh()
    qapp.processEvents()
    page._on_cell_clicked(_pdf_index(page, invoice_id))
    number = c.get_invoice_header(invoice_id).invoice_number
    assert (data_dir / f"Mahnung_1_{number}.pdf").read_bytes().startswith(b"%PDF")
    assert window.opened == [] # nothing was opened in a PDF program
    assert c.get_invoice_header(invoice_id).reminder_level == 1 # saving again is no new reminder


def test_datev_export_takes_paid_invoices_without_cancellations(controller, seller, tmp_path):
    c = controller
    customer_id = _customer(c)
    paid = c.create_invoice(customer_id, DAY, DAY, ITEM, status="Offen") # never "archived"
    c.update_invoice_status(paid, "Bezahlt")
    cancelled = c.create_invoice(customer_id, DAY, DAY, ITEM, status="Offen")
    storno = c.cancel_invoice(cancelled)
    c.create_invoice(customer_id, DAY, DAY, ITEM) # draft
    c.create_invoice(customer_id, DAY, DAY, ITEM, status="Offen") # open
    assert [i.id for i in DatevGenerator.exportable_invoices(c)] == [paid]
    # Also when the list handed in contains them
    target = tmp_path / "datev.zip"
    everything = [c.get_invoice_header(i) for i in (paid, cancelled, storno)]
    assert DatevGenerator(c).generate_export(everything, str(target))
    import zipfile
    assert zipfile.ZipFile(target).namelist() == [f"Rechnung_{c.get_invoice_header(paid).invoice_number}.pdf"]
