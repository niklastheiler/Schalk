import os
import sys
import tempfile

# Separate data folder for the whole test run (must be set before src.utils.paths is imported)
os.environ["SCHALK_DATA_DIR"] = tempfile.mkdtemp(prefix="schalk_test_")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from PySide6.QtWidgets import QApplication

from src.utils import paths

SELLER = {
    "company_name": "Test & Söhne GmbH", "first_name": "Max", "last_name": "Muster", "address": "Hauptstr. 1",
    "postal_code": "10115", "city": "Berlin", "tax_id": "12/345/67890", "vat_id": "DE100000008",
    "email": "info@test.de", "phone": "030 123456", "iban": "DE02120300000000202051", "bic": "BYLADEM1001",
    "bank_name": "Bank", "payment_terms_days": "14",
}


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    for name, sub in (("DATA_DIR", ""), ("APP_DATA_DIR", "app_data"), ("ASSETS_DIR", "assets"),
                      ("INCOMING_INVOICES_DIR", "app_data/incoming_invoices"), ("RECEIPTS_DIR", "assets/receipts"),
                      ("INVOICE_ARCHIVE_DIR", "app_data/archive/invoices")):
        monkeypatch.setattr(paths, name, str(tmp_path / sub))
    monkeypatch.setattr(paths, "DB_PATH", str(tmp_path / "schalk.enc.db"))
    monkeypatch.setattr(paths, "KEY_PATH", str(tmp_path / "schalk.key"))
    monkeypatch.setattr(paths, "desktop_path", lambda f: str(tmp_path / f))
    return tmp_path


@pytest.fixture
def controller(qapp, data_dir):
    from src.controllers.db_controller import DBController
    from src.models.database import DatabaseManager
    from src.utils.invoice_documents import archive_invoice_document, validate_invoice
    c = DBController(DatabaseManager(paths.DB_PATH, paths.KEY_PATH))
    c.archiver = lambda invoice_id: archive_invoice_document(c, invoice_id)
    c.einvoice_validator = lambda invoice: validate_invoice(c, invoice)
    yield c
    c.close()


@pytest.fixture
def seller(controller):
    controller.set_settings(SELLER)
    return SELLER


@pytest.fixture
def window(controller, seller, monkeypatch):
    import os
    from PySide6.QtWidgets import QDialog, QFileDialog
    from qfluentwidgets import MessageBox, MessageBoxBase
    opened = []
    monkeypatch.setattr(os, "startfile", lambda *a, **k: opened.append(a), raising=False)
    monkeypatch.setattr(MessageBox, "exec", lambda self: 1)
    monkeypatch.setattr(MessageBoxBase, "exec", lambda self: 1)
    monkeypatch.setattr(QDialog, "exec", lambda self: 1)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda parent, caption, path, flt="": (path, "")))
    from src.views.main_window import MainWindow
    w = MainWindow(controller)
    w.resize(1400, 900)
    w.show()
    w.opened = opened
    yield w
    w.hide()
