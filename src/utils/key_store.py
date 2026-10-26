"""
Stores the database key protected by the Windows Data Protection API (DPAPI).
Only the same Windows user account can decrypt it, so no password prompt is needed.
"""
import os
import win32crypt

_DESCRIPTION = "Schalk Datenbankschluessel"
_ENTROPY = b"schalk-db-key-v1"
CRYPTPROTECT_UI_FORBIDDEN = 0x01


def save_key(path: str, key: bytes):
    blob = win32crypt.CryptProtectData(key, _DESCRIPTION, _ENTROPY, None, None, CRYPTPROTECT_UI_FORBIDDEN)
    temp_path = path + ".tmp"
    with open(temp_path, "wb") as f:
        f.write(blob)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_path, path)


def load_key(path: str) -> bytes:
    with open(path, "rb") as f:
        blob = f.read()
    _, key = win32crypt.CryptUnprotectData(blob, _ENTROPY, None, None, CRYPTPROTECT_UI_FORBIDDEN)
    return key
