import ctypes
import logging
import os
import sys
import threading
from datetime import datetime
from PySide6.QtCore import QLockFile, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox
from src.controllers.db_controller import DBController
from src.models.database import DatabaseManager, KeyMissingError, WrongPasswordError
from src.utils import paths
from src.utils.app_logging import install_excepthook, setup_logging
from src.utils.signal_bus import SignalBus
from src.utils.translations import install_german_translations
from src.version import APP_NAME, APP_VERSION

logger = logging.getLogger(__name__)
APP_ID = "Schalk.Rechnungsprogramm"
APP_ICON = os.path.join(os.path.dirname(__file__), "resources", "icons", "schalk.ico")


def _set_windows_app_id():
    # Own taskbar group/icon instead of being grouped under python.exe
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)


def _database_manager():
    return DatabaseManager(db_path=paths.DB_PATH, key_path=paths.KEY_PATH,
                           on_save_error=lambda e: SignalBus.get().saveFailed.emit(str(e)))


def set_aside_database() -> list:
    """
    Renames the database and its key (nothing is deleted), so Schalk can start with an empty database and a
    backup can be restored. Returns the new file names.
    """
    suffix = f".defekt-{datetime.now():%Y%m%d-%H%M%S}"
    renamed = []
    for path in (paths.DB_PATH, paths.KEY_PATH):
        if os.path.exists(path):
            os.replace(path, path + suffix)
            renamed.append(path + suffix)
    return renamed


def open_database():
    """Opens the encrypted database without a prompt; the key is protected by Windows (DPAPI)."""
    try:
        return _database_manager()
    except (KeyMissingError, WrongPasswordError) as e:
        logger.error("Datenbank kann nicht geöffnet werden: %s", e)
        # Without a way out, the backup (restored in the settings) could never be reached
        box = QMessageBox(QMessageBox.Critical, "Schalk",
                          f"Die Datenbank kann nicht geöffnet werden.\n\n{e}\n\n"
                          "Schalk kann mit einer leeren Datenbank starten. Danach unter Einstellungen > Sicherheit & GoBD "
                          "das letzte Backup einspielen. Die bisherigen Dateien werden dabei nicht gelöscht, sondern "
                          f"umbenannt (Endung „.defekt-…“ im Ordner {paths.DATA_DIR}).")
        start_empty = box.addButton("Leer starten (Backup einspielen)", QMessageBox.AcceptRole)
        box.addButton("Beenden", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not start_empty:
            return None
    try:
        logger.warning("Datenbank beiseitegelegt: %s", set_aside_database())
        return _database_manager()
    except Exception as e:
        logger.exception("Neue Datenbank konnte nicht angelegt werden")
        QMessageBox.critical(None, "Schalk", f"Die Datenbank konnte nicht neu angelegt werden:\n{e}")
        return None


def _warm_up():
    # Loading Saxon and compiling the EN 16931 rules takes a few seconds the first time; done in the
    # background, the first finalization of an invoice doesn't wait for it
    try:
        from src.utils.einvoice_validation import warm_up
        warm_up()
    except Exception:
        logger.exception("Prüfregeln konnten nicht vorab geladen werden")


def main():
    setup_logging()
    install_excepthook()
    _set_windows_app_id()
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setWindowIcon(QIcon(APP_ICON))
    install_german_translations(app)

    # Two instances would overwrite each other's changes in the encrypted database file
    lock = QLockFile(paths.LOCK_PATH)
    lock.setStaleLockTime(0)
    if not lock.tryLock(5000):
        QMessageBox.warning(None, "Schalk", "Schalk ist bereits geöffnet.")
        return 0

    paths.clean_temp_documents()
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
    window.updates.start()
    QTimer.singleShot(500, window, window.remind_of_backup)
    threading.Thread(target=_warm_up, name="schalk-warm-up", daemon=True).start()
    logger.info("Schalk gestartet, Daten in %s", paths.DATA_DIR)

    if not window.isVisible():
        # Closed while starting (e.g. to install an update): nothing left to run, the process must end
        lock.unlock()
        return 0
    exit_code = app.exec()
    lock.unlock()
    return exit_code
