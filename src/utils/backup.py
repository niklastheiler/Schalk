"""
Portable backups: a single .backup file with the database and all archived documents.

The file is a ZIP archive (database as schalk.db, documents below app_data/ and assets/) with a marker file
that identifies it as a Schalk backup. ZIP stores a CRC-32 checksum for every file, so a damaged or cut-off
backup is detected before anything is restored. Backups are not encrypted: they contain all business data
and belong in a safe place.
"""
import os
import shutil
import zipfile
from datetime import datetime
from src.utils.archive import make_read_only

DB_NAME = "schalk.db"
MARKER = "schalk-backup.txt"
MARKER_TEXT = "Schalk-Backup, Format 3\n"


def create_backup(snapshot: bytes, path: str, folders: dict):
    """
    Writes a database snapshot (DatabaseManager.snapshot()) and the given folders ({name in backup: directory})
    into one .backup file. Needs no access to the running database, so it can run on a worker thread.
    """
    temp_path = path + ".tmp"
    try:
        with open(temp_path, "wb") as f:
            with zipfile.ZipFile(f, "w", zipfile.ZIP_DEFLATED) as zipf:
                zipf.writestr(MARKER, MARKER_TEXT)
                zipf.writestr(DB_NAME, snapshot)
                for name, folder in folders.items():
                    for root, _, files in os.walk(folder):
                        for file in files:
                            full = os.path.join(root, file)
                            zipf.write(full, f"{name}/{os.path.relpath(full, folder).replace(os.sep, '/')}")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    except BaseException:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise


def _extract_missing(zipf: zipfile.ZipFile, folders: dict):
    for info in zipf.infolist():
        name, _, relative = info.filename.partition("/")
        if info.is_dir() or name not in folders or not relative:
            continue
        target = os.path.abspath(folders[name])
        dest = os.path.abspath(os.path.join(target, relative))
        # Archived documents are read-only and must not be overwritten; nothing may land outside the folder
        if os.path.commonpath([target, dest]) != target or os.path.exists(dest):
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with zipf.open(info) as src, open(dest, "wb") as dst:
            shutil.copyfileobj(src, dst)
        # Restored documents are archived documents again (GoBD: read-only)
        make_read_only(dest)


def restore_backup(db, path: str, folders: dict):
    """
    Restores a .backup file: the current database is kept as .bak copy and replaced, missing documents
    are added to the folders. Raises ValueError before anything is changed if the file is no valid backup.
    The application must be restarted afterwards.
    """
    with open(path, "rb") as f:
        if f.read(7) == b"SCHALKB":
            raise ValueError("Dieses Backup stammt aus einer älteren Schalk-Version (mit Backup-Passwort) "
                             "und wird nicht mehr unterstützt.")
    try:
        zipf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        raise ValueError("Die Datei ist kein gültiges Schalk-Backup oder sie ist beschädigt.")
    with zipf:
        names = set(zipf.namelist())
        if MARKER not in names or DB_NAME not in names:
            raise ValueError("Die Datei ist kein Schalk-Backup dieser Version.")
        # Checks the CRC of every file: a damaged backup must not replace good data
        try:
            broken = zipf.testzip()
        except Exception: # e.g. zlib.error for damaged compressed data
            broken = "?"
        if broken:
            raise ValueError("Das Backup ist beschädigt oder unvollständig.")
        data = zipf.read(DB_NAME)
        # The writer is flushed first so the .bak copy is complete
        db.flush()
        if os.path.exists(db.db_path):
            shutil.copy2(db.db_path, f"{db.db_path}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}")
        db.restore_database(data)
        _extract_missing(zipf, folders)
