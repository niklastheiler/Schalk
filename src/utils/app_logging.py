import faulthandler
import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from src.utils import paths

logger = logging.getLogger("schalk")
_crash_log = None


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
    # Hard crashes (e.g. an access violation in Qt) end the process without a Python traceback; the
    # interpreter writes the stack of every thread into this file instead
    global _crash_log
    try:
        _crash_log = open(os.path.join(paths.DATA_DIR, "absturz.log"), "a", encoding="utf-8")
        faulthandler.enable(_crash_log)
    except OSError:
        logger.warning("Absturzprotokoll kann nicht geöffnet werden", exc_info=True)


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

    def handle_thread(args):
        # Without a console the default hook prints nowhere, so errors of worker threads would get lost
        if issubclass(args.exc_type, SystemExit):
            return
        name = args.thread.name if args.thread else "?"
        logger.critical("Unbehandelter Fehler im Hintergrund (%s)", name, exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    threading.excepthook = handle_thread
