"""Received invoices: amount field and recognition, in-app view of the receipt, protected archive; cash book DATEV export."""
import os
import subprocess
import zipfile
from datetime import date, datetime
import pytest
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from receipts import RECEIPT
from PySide6.QtCore import Qt
from src.utils import archive, paths
from src.utils.datev_generator import DatevGenerator
from src.utils.pdf_text_guess import guess_amount


def _pdf(path, lines):
    c = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    for line in lines:
        c.drawString(60, y, line)
        y -= 18
    c.showPage()
    c.drawString(60, 800, "Seite 2")
    c.save()
    return str(path)


# --- Upload dialog ---
def _dialog(qapp, amount):
    from PySide6.QtWidgets import QWidget
    from src.views.incoming_invoice_interface import IncomingInvoiceDialog
    parent = QWidget()
    parent.resize(900, 700)
    return IncomingInvoiceDialog(parent, amount, date(2024, 6, 18), "ROLAND", supplier="ROLAND"), parent


def test_amount_field_shows_the_value_and_is_empty_without_one(qapp):
    dialog, _ = _dialog(qapp, 1234.5)
    assert dialog.amountEdit.text() == "1234,50" and dialog.get_data()["amount"] == 1234.5
    dialog, _ = _dialog(qapp, 0.0)
    assert dialog.amountEdit.text() == "" # nothing recognized: nothing suggested
    assert not dialog.validate() and dialog.amountEdit.isError() # saving needs an amount
    dialog.amountEdit.setText("-49,90") # credit note
    assert dialog.validate() and dialog.get_data()["amount"] == -49.9
    dialog.amountEdit.setText("1.500,00")
    assert dialog.get_data()["amount"] == 1500.0


@pytest.mark.parametrize("text, amount", [
    ("Sehr geehrter Herr Muster,\nIhre Versicherungssumme beträgt 100.000,00 EUR.\nMit freundlichen Grüßen", 0.0),
    ("Wir übernehmen Kosten bis zu einem Betrag von 100.000,00 €.", 0.0),
    ("Deckungssumme: 100.000,00 €\nBeitrag laut Vertrag", 0.0),
    ("Leistungen gesamt bis 100.000,00 €\nZahlbetrag: 45,90 €", 45.9),
    ("Summe: 119,00 €", 119.0),
    ("Position Betrag\nArbeit 100,00\nSumme 100,00", 100.0),
    ("Gesamtbetrag: 119,00 EUR", 119.0),
])
def test_amount_recognition_ignores_insured_sums_and_sentences(text, amount):
    assert guess_amount(text) == amount


# --- Viewing the receipt ---
def test_double_click_shows_the_archived_pdf_in_schalk(controller, seller, tmp_path, monkeypatch, qapp):
    from src.views import document_viewer
    from src.views.incoming_invoice_interface import IncomingInvoiceInterface
    source = _pdf(tmp_path / "rechnung.pdf", ["Elektro Schulz e.K.", "Gesamtbetrag: 119,00 EUR"])
    invoice_id = controller.add_incoming_invoice("Lieferant", datetime(2026, 11, 5), 119.0, "Schulz", source,
                                                 invoice_number="2026-0815", supplier_name="Elektro Schulz e.K.")
    os.remove(source) # the original in the downloads folder is gone: the archived copy is shown
    shown = []

    def exec_(viewer):
        shown.append((viewer.windowTitle(), viewer.page_count(), viewer.path, viewer.save_name))
        return 1
    monkeypatch.setattr(document_viewer.PdfViewer, "exec", exec_)
    opened = []
    monkeypatch.setattr("src.views.incoming_invoice_interface.open_document", lambda *a: opened.append(a))
    page = IncomingInvoiceInterface(controller, "Lieferant")
    invoice = controller.get_incoming_invoice(invoice_id)
    page.on_activated(invoice)
    title, pages, path, save_name = shown[0]
    assert "Elektro Schulz e.K." in title and "2026-0815" in title and pages == 2
    assert path == invoice.file_path and save_name == "Elektro_Schulz_e.K._2026-0815.pdf"
    assert opened == [] # no PDF program


def test_missing_archived_receipt_gives_a_message(controller, seller, tmp_path, monkeypatch, qapp):
    from src.views.incoming_invoice_interface import IncomingInvoiceInterface
    source = _pdf(tmp_path / "rechnung.pdf", ["Rechnung"])
    invoice_id = controller.add_incoming_invoice("Sonstige", datetime(2026, 11, 5), 10.0, "X", source)
    invoice = controller.get_incoming_invoice(invoice_id)
    os.chmod(invoice.file_path, 0o600)
    os.remove(invoice.file_path)
    errors = []
    monkeypatch.setattr("src.views.common.notify_error", lambda parent, title, text="": errors.append(title))
    IncomingInvoiceInterface(controller, "Sonstige").on_activated(invoice)
    assert errors == ["Beleg fehlt im Archiv"]


def test_viewer_saves_a_copy(tmp_path, monkeypatch, qapp):
    from PySide6.QtWidgets import QFileDialog
    from src.views.document_viewer import PdfViewer
    source = _pdf(tmp_path / "beleg.pdf", ["Beleg"])
    target = tmp_path / "kopie.pdf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), "")))
    monkeypatch.setattr("src.utils.paths.desktop_path", lambda name: str(tmp_path / name))
    viewer = PdfViewer(source, "Beleg", "beleg.pdf")
    viewer.save_copy()
    assert target.read_bytes() == open(source, "rb").read()


# --- Protected archive folders ---
def test_protection_is_only_set_on_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(archive.os, "name", "posix")
    assert archive.protect_folder(str(tmp_path / "a")) is False


def test_protection_denies_deleting_for_everyone(tmp_path, monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append(args[1:])
        return subprocess.CompletedProcess(args, 0, stdout="" if len(calls) == 1 else "ok", stderr="")
    monkeypatch.setattr(archive.os, "name", "nt")
    monkeypatch.setattr(archive.subprocess, "run", run)
    folder = str(tmp_path / "incoming_invoices")
    assert archive.protect_folder(folder)
    assert calls == [[folder], [folder, "/deny", "*S-1-1-0:(OI)(CI)(DE,DC)"]]
    # Already protected: nothing is changed
    calls.clear()
    monkeypatch.setattr(archive.subprocess, "run", lambda args, **k: (calls.append(args[1:]), subprocess.CompletedProcess(
        args, 0, stdout=f"{folder} Jeder:(OI)(CI)(DENY)(DE,DC)", stderr=""))[1])
    assert archive.protect_folder(folder) and calls == [[folder]]


def test_startup_protects_every_archive_folder():
    from src import main
    from src.utils import paths
    assert set(main.archive_folders()) == {paths.INVOICE_ARCHIVE_DIR, paths.REMINDER_ARCHIVE_DIR,
                                          paths.INCOMING_INVOICES_DIR, paths.RECEIPTS_DIR}


# --- Cash book DATEV export ---
def test_cashbook_export_leaves_out_cancelled_entries_and_their_storno(controller, seller, tmp_path):
    c = controller
    c.add_cashbook_entry(datetime(2026, 11, 2), 100.0, "Einlage", "A", "Einnahme", 0, attachment_source=RECEIPT)
    c.finalize_cashbook()
    kept = c.get_cashbook_entries()[0]
    c.add_cashbook_entry(datetime(2026, 11, 3), 20.0, "Material", "A", "Barentnahme Firma", 19, attachment_source=RECEIPT)
    c.finalize_cashbook()
    cancelled = next(e for e in c.get_cashbook_entries() if e.id != kept.id)
    c.storno_cashbook_entry(cancelled.id)
    entries = c.get_cashbook_entries()
    assert [e.id for e in DatevGenerator.exportable_cashbook_entries(c, entries)] == [kept.id]
    target = tmp_path / "kasse.zip"
    assert DatevGenerator(c).generate_cashbook_export(entries, str(target))
    assert zipfile.ZipFile(target).namelist() == [f"{kept.receipt_number}_{os.path.basename(kept.attachment_path)}"]
    # Only an entry and its storno: nothing to export
    assert not DatevGenerator(c).generate_cashbook_export([e for e in entries if e.id != kept.id], str(tmp_path / "leer.zip"))


def test_cashbook_receipt_column_and_view(controller, seller, monkeypatch, qapp):
    from src.views import document_viewer
    from src.views.cashbook_interface import CashbookInterface
    c = controller
    c.add_cashbook_entry(datetime(2026, 11, 2), 50.0, "Einlage", "A", "Einnahme", 0, attachment_source=RECEIPT)
    c.add_cashbook_entry(datetime(2026, 11, 3), 5.0, "Privat", "A", "Barentnahme Privat", 0)
    c.finalize_cashbook()
    page = CashbookInterface(c)
    page.refresh()
    column = next(i for i, col in enumerate(page.model.columns) if col.title == "Beleg")
    marks = {page.proxy.index(r, 0).data(Qt.UserRole + 1).description: page.proxy.index(r, column).data()
             for r in range(page.proxy.rowCount())}
    assert marks == {"Einlage": "✓", "Privat": "✗"}
    shown = []
    monkeypatch.setattr(document_viewer.PdfViewer, "exec", lambda viewer: shown.append(viewer.path))
    entry = next(e for e in c.get_cashbook_entries() if e.attachment_path)
    page.on_activated(entry) # double click: the receipt in Schalk, not in a PDF program
    assert shown == [paths.resolve(entry.attachment_path)]


def test_invoice_pdf_opens_without_the_attachment_panel(controller, seller):
    from pypdf import PdfReader
    from src.utils.invoice_documents import build_invoice_pdf
    customer_id = controller.add_customer(company_name="Kunde AG", address="Weg 2", postal_code="20095", city="Hamburg")
    day = datetime(2026, 11, 2)
    invoice_id = controller.create_invoice(customer_id, day, day, [
        {"title": "Leistung", "quantity": 1, "unit_price": 100.0, "tax_percent": 19.0}], status="Offen")
    reader = PdfReader(build_invoice_pdf(controller, controller.get_invoice(invoice_id)))
    assert reader.trailer["/Root"]["/PageMode"] == "/UseNone"
    assert "factur-x.xml" in reader.attachments # the e-invoice data stays embedded
