from PySide6.QtWidgets import QFileDialog
from src.utils import paths


def test_uploads_start_in_downloads_folder(controller, qapp, monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "downloads_dir", lambda: str(tmp_path / "Downloads"))
    calls = []
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda parent, caption, directory, flt: (calls.append(directory), ([], ""))[1]))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda parent, caption, directory, flt: (calls.append(directory), ("", ""))[1]))
    from src.views.cashbook_interface import CashbookInterface
    from src.views.incoming_invoice_interface import IncomingInvoiceInterface
    IncomingInvoiceInterface(controller, "Lieferant").upload()
    CashbookInterface(controller).attach_file()
    assert calls == [str(tmp_path / "Downloads")] * 2
