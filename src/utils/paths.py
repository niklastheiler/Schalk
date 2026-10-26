import os
import sys


def _resolve_app_dir() -> str:
    # Frozen build (e.g. PyInstaller): data lives next to the .exe
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    # Source checkout: project root (two levels above src/utils)
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


APP_DIR = _resolve_app_dir()

DB_PATH = os.path.join(APP_DIR, "schalk.enc.db")
# DPAPI-protected database key (only usable by the same Windows user account)
KEY_PATH = os.path.join(APP_DIR, "schalk.key")
ERROR_LOG = os.path.join(APP_DIR, "error.log")
APP_DATA_DIR = os.path.join(APP_DIR, "app_data")
ASSETS_DIR = os.path.join(APP_DIR, "assets")

INCOMING_INVOICES_DIR = os.path.join(APP_DATA_DIR, "incoming_invoices")
RECEIPTS_DIR = os.path.join(ASSETS_DIR, "receipts")
INVOICE_ARCHIVE_DIR = os.path.join(APP_DATA_DIR, "archive", "invoices")


def desktop_path(filename: str) -> str:
    return os.path.join(os.path.expanduser("~"), "Desktop", filename)
