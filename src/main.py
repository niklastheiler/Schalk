import ctypes
import logging
import sys
from PySide6.QtCore import QLockFile, Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from src.controllers.db_controller import DBController
from src.models.database import DatabaseManager, KeyMissingError, WrongPasswordError
from src.utils import paths
from src.utils.app_logging import install_excepthook, setup_logging
from src.utils.signal_bus import SignalBus

logger = logging.getLogger(__name__)
APP_ID = "Schalk.Rechnungsprogramm"


def _set_windows_app_id():
    # Own taskbar group/icon instead of being grouped under python.exe
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass


def open_database():
    """Opens the encrypted database without a prompt; the key is protected by Windows (DPAPI)."""
    try:
        return DatabaseManager(db_path=paths.DB_PATH, key_path=paths.KEY_PATH,
                               on_save_error=lambda e: SignalBus.get().saveFailed.emit(str(e)))
    except (KeyMissingError, WrongPasswordError) as e:
        QMessageBox.critical(None, "Schalk", f"Die Datenbank kann nicht geöffnet werden.\n\n{e}")
        return None


def main():
    setup_logging()
    install_excepthook()
    _set_windows_app_id()
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("Schalk")

    # Two instances would overwrite each other's changes in the encrypted database file
    lock = QLockFile(paths.LOCK_PATH)
    lock.setStaleLockTime(0)
    if not lock.tryLock(5000):
        QMessageBox.warning(None, "Schalk", "Schalk ist bereits geöffnet.")
        return 0

    db_manager = open_database()
    if db_manager is None:
        return 1
    db_controller = DBController(db_manager)

    from src.utils.invoice_documents import archive_invoice_document, validate_invoice
    db_controller.archiver = lambda invoice_id: archive_invoice_document(db_controller, invoice_id)
    db_controller.einvoice_validator = lambda invoice: validate_invoice(db_controller, invoice)

    from src.views.main_window import MainWindow
    window = MainWindow(db_controller)
    window.showMaximized()
    window.check_integrity_on_startup()
    logger.info("Schalk gestartet, Daten in %s", paths.DATA_DIR)

    exit_code = app.exec()
    lock.unlock()
    return exit_code
