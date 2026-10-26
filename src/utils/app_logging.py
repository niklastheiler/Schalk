import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from src.utils import paths

logger = logging.getLogger("schalk")


def setup_logging():
    os.makedirs(paths.DATA_DIR, exist_ok=True)
    handler = RotatingFileHandler(paths.LOG_PATH, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    # Third-party libraries are chatty on INFO
    for noisy in ("factur-x", "facturx", "PIL", "pypdf"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def install_excepthook():
    """Unhandled exceptions are logged and shown instead of silently killing the Qt event loop."""
    def handle(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical("Unbehandelter Fehler", exc_info=(exc_type, exc_value, exc_tb))
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            if QApplication.instance():
                QMessageBox.critical(None, "Schalk – Fehler",
                                     f"Ein unerwarteter Fehler ist aufgetreten:\n\n{exc_value}\n\nDetails stehen in:\n{paths.LOG_PATH}")
        except Exception:
            pass
    sys.excepthook = handle
