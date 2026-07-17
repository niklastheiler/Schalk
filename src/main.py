import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from src.controllers.db_controller import DBController
from src.models.database import DatabaseManager
from src.views.main_window import MainWindow

def main():
    db_manager = DatabaseManager(db_path="schalk.enc.db", password="schalk_secure")
    db_controller = DBController(db_manager)

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

    app = QApplication(sys.argv)
    window = MainWindow(db_controller)
    window.showMaximized()
    
    exit_code = app.exec()
    sys.exit(exit_code)

if __name__ == '__main__':
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    main()
