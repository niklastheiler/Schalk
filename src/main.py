import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from src.controllers.db_controller import DBController
from src.models.database import DatabaseManager, KeyMissingError, WrongPasswordError
from src.utils import paths


def open_database():
    """Opens the encrypted database without a prompt; the key is protected by Windows (DPAPI)."""
    from PySide6.QtWidgets import QMessageBox
    try:
        return DatabaseManager(db_path=paths.DB_PATH, key_path=paths.KEY_PATH)
    except (KeyMissingError, WrongPasswordError) as e:
        QMessageBox.critical(None, "Schalk", f"Die Datenbank kann nicht geöffnet werden.\n\n{e}")
        return None


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)

    db_manager = open_database()
    if db_manager is None:
        sys.exit(1)
    db_controller = DBController(db_manager)

    from src.views.main_window import MainWindow
    window = MainWindow(db_controller)
    window.showMaximized()
    window.check_integrity_on_startup()

    exit_code = app.exec()
    sys.exit(exit_code)

if __name__ == '__main__':
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    main()
