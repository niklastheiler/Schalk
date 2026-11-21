import ctypes
import os
import re
import tempfile
import uuid
from datetime import datetime


def _resolve_data_dir() -> str:
    # Explicit override (e.g. portable installation or tests)
    override = os.environ.get("SCHALK_DATA_DIR")
    if override:
        return os.path.abspath(override)
    # Per-user application data, writable even if the program is installed under "C:\Program Files"
    return os.path.join(os.environ["LOCALAPPDATA"], "Schalk")


DATA_DIR = _resolve_data_dir()

DB_PATH = os.path.join(DATA_DIR, "schalk.enc.db")
# DPAPI-protected database key (only usable by the same Windows user account)
KEY_PATH = os.path.join(DATA_DIR, "schalk.key")
LOCK_PATH = os.path.join(DATA_DIR, "schalk.lock")
LOG_PATH = os.path.join(DATA_DIR, "schalk.log")
APP_DATA_DIR = os.path.join(DATA_DIR, "app_data")
ASSETS_DIR = os.path.join(DATA_DIR, "assets")

INCOMING_INVOICES_DIR = os.path.join(APP_DATA_DIR, "incoming_invoices")
RECEIPTS_DIR = os.path.join(ASSETS_DIR, "receipts")
INVOICE_ARCHIVE_DIR = os.path.join(APP_DATA_DIR, "archive", "invoices")
# Documents opened or printed from Schalk (draft previews, quotes, reminders); emptied on every start
TEMP_DOCUMENTS_DIR = os.path.join(tempfile.gettempdir(), "Schalk")

_DATA_FOLDERS = ("app_data", "assets")


def resolve(stored: str) -> str:
    """
    Current location of an archived file. The database keeps the path the file had when it was archived;
    after a backup was restored on another PC or Windows account the data folder is somewhere else, so the
    part below the data folder (app_data\\... or assets\\...) is looked up in the current data folder.
    """
    if not stored or os.path.exists(stored):
        return stored
    parts = re.split(r"[\\/]", stored)
    # The last data folder in the path (the file name itself is never one)
    for i in range(len(parts) - 2, -1, -1):
        if parts[i] in _DATA_FOLDERS:
            candidate = os.path.join(DATA_DIR, *parts[i:])
            return candidate if os.path.exists(candidate) else stored
    return stored


def temp_document(filename: str) -> str:
    """
    A new path in the temp folder for a document that is only shown or printed. Every call gets its own
    name: a PDF viewer may still hold the previous version open, so it could not be overwritten.
    """
    os.makedirs(TEMP_DOCUMENTS_DIR, exist_ok=True)
    stem, ext = os.path.splitext(filename)
    return os.path.join(TEMP_DOCUMENTS_DIR, f"{stem}_{datetime.now():%Y%m%d%H%M%S%f}{ext}")


def clean_temp_documents():
    """Removes the documents of earlier sessions: they contain customer data and must not pile up."""
    if not os.path.isdir(TEMP_DOCUMENTS_DIR):
        return
    for name in os.listdir(TEMP_DOCUMENTS_DIR):
        try:
            os.remove(os.path.join(TEMP_DOCUMENTS_DIR, name))
        except OSError:
            pass # still open in a viewer; removed on a later start


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, value: str):
        super().__init__()
        raw = uuid.UUID(value).bytes_le
        ctypes.memmove(ctypes.byref(self), raw, ctypes.sizeof(self))


_FOLDERID_DESKTOP = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"
_FOLDERID_DOWNLOADS = "{374DE290-123F-4565-9164-39C4925E467B}"


def _known_folder(folder_id: str, name: str) -> str:
    """Real location of a Windows user folder, also when it is moved or redirected (e.g. OneDrive)."""
    path_ptr = ctypes.c_wchar_p()
    if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(_GUID(folder_id)), 0, None, ctypes.byref(path_ptr)) != 0:
        raise OSError(f"Der Ordner '{name}' konnte nicht ermittelt werden.")
    try:
        return path_ptr.value
    finally:
        ctypes.windll.ole32.CoTaskMemFree(path_ptr)


def desktop_path(filename: str) -> str:
    return os.path.join(_known_folder(_FOLDERID_DESKTOP, "Desktop"), filename)


def downloads_dir() -> str:
    return _known_folder(_FOLDERID_DOWNLOADS, "Downloads")
