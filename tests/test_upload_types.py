from datetime import datetime
import pytest
from PySide6.QtWidgets import QFileDialog
from src.utils import paths


def test_cashbook_receipt_must_be_pdf(controller, tmp_path):
    controller.add_cashbook_entry(datetime(2026, 10, 1), 100, "Einlage", "A", "Einnahme", 19)
    image = tmp_path / "beleg.png"
    image.write_bytes(b"\x89PNG\r\n")
    with pytest.raises(ValueError, match="nur PDF"):
        controller.add_cashbook_entry(datetime(2026, 10, 2), 5, "Porto", "A", "Barentnahme Firma", 19, attachment_source=str(image))
    pdf = tmp_path / "beleg.pdf"
    pdf.write_bytes(b"%PDF-1.7 test")
    controller.add_cashbook_entry(datetime(2026, 10, 2), 5, "Porto", "A", "Barentnahme Firma", 19, attachment_source=str(pdf))


def test_incoming_invoice_must_be_pdf_or_xrechnung(controller, tmp_path):
    fake = tmp_path / "rechnung.pdf"
    fake.write_bytes(b"kein pdf")
    with pytest.raises(ValueError):
        controller.add_incoming_invoice("Lieferant", datetime(2026, 10, 1), 10, "x", str(fake))


def test_file_dialog_filters(controller, qapp, monkeypatch):
    monkeypatch.setattr(paths, "downloads_dir", lambda: "C:/Downloads")
    filters = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda p, c, d, f: (filters.append(f), ("", ""))[1]))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda p, c, d, f: (filters.append(f), ([], ""))[1]))
    from src.views.cashbook_interface import CashbookInterface
    from src.views.incoming_invoice_interface import IncomingInvoiceInterface
    CashbookInterface(controller).attach_file()
    IncomingInvoiceInterface(controller, "Lieferant").upload()
    assert filters == ["PDF-Dokumente (*.pdf)", "Rechnungen als PDF oder XRechnung (*.pdf *.xml)"]
