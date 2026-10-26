import ctypes
import os
import uuid


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


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, value: str):
        super().__init__()
        raw = uuid.UUID(value).bytes_le
        ctypes.memmove(ctypes.byref(self), raw, ctypes.sizeof(self))


_FOLDERID_DESKTOP = "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}"


def _known_desktop_folder() -> str:
    """Real desktop folder, also when it is redirected (e.g. OneDrive)."""
    path_ptr = ctypes.c_wchar_p()
    if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(_GUID(_FOLDERID_DESKTOP)), 0, None, ctypes.byref(path_ptr)) != 0:
        raise OSError("Der Desktop-Ordner konnte nicht ermittelt werden.")
    try:
        return path_ptr.value
    finally:
        ctypes.windll.ole32.CoTaskMemFree(path_ptr)


def desktop_path(filename: str) -> str:
    return os.path.join(_known_desktop_folder(), filename)
