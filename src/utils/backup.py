"""
Portable backups: a single encrypted .backup file with the database and all archived documents.

File format: MAGIC | iterations (uint32 BE) | salt (16 bytes) | nonce prefix (7 bytes) | chunks
The payload is a ZIP archive, streamed in chunks of 1 MiB and encrypted with AES-256-GCM (key derived
from the backup password with PBKDF2). Each nonce holds the chunk counter and a final-chunk flag, so
reordered, missing or cut-off chunks are detected; the header is authenticated with every chunk.
"""
import os
import shutil
import struct
import tempfile
import zipfile
from datetime import datetime
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from src.models.database import WrongPasswordError

MAGIC = b"SCHALKB\x01"
SALT_SIZE = 16
PREFIX_SIZE = 7
HEADER_SIZE = len(MAGIC) + 4 + SALT_SIZE + PREFIX_SIZE
KDF_ITERATIONS = 600_000
CHUNK_SIZE = 1 << 20
TAG_SIZE = 16
DB_NAME = "schalk.db"
# Decrypted backups up to this size stay in memory; larger ones are spooled next to the database
SPOOL_LIMIT = 64 << 20


def _derive_key(password: str, salt: bytes, iterations: int) -> AESGCM:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return AESGCM(kdf.derive((password or "").encode("utf-8")))


def _nonce(prefix: bytes, counter: int, last: bool) -> bytes:
    return prefix + struct.pack(">I", counter) + (b"\x01" if last else b"\x00")


class _EncryptingWriter:
    """Write-only stream for zipfile that encrypts everything written to it chunk by chunk."""

    def __init__(self, f, aead: AESGCM, header: bytes):
        self._f = f
        self._aead = aead
        self._header = header
        self._prefix = header[-PREFIX_SIZE:]
        self._buffer = bytearray()
        self._counter = 0

    def write(self, data) -> int:
        self._buffer += data
        # Keep the last chunk back: only finish() knows which one is final
        while len(self._buffer) > CHUNK_SIZE:
            self._emit(bytes(self._buffer[:CHUNK_SIZE]), last=False)
            del self._buffer[:CHUNK_SIZE]
        return len(data)

    def flush(self):
        pass

    def finish(self):
        self._emit(bytes(self._buffer), last=True)
        self._buffer.clear()

    def _emit(self, chunk: bytes, last: bool):
        self._f.write(self._aead.encrypt(_nonce(self._prefix, self._counter, last), chunk, self._header))
        self._counter += 1


def create_backup(db, path: str, password: str, folders: dict):
    """Writes the database and the given folders ({name in backup: directory}) into one .backup file."""
    header = MAGIC + struct.pack(">I", KDF_ITERATIONS) + os.urandom(SALT_SIZE) + os.urandom(PREFIX_SIZE)
    aead = _derive_key(password, header[len(MAGIC) + 4:len(MAGIC) + 4 + SALT_SIZE], KDF_ITERATIONS)
    temp_path = path + ".tmp"
    try:
        with open(temp_path, "wb") as f:
            f.write(header)
            writer = _EncryptingWriter(f, aead, header)
            with zipfile.ZipFile(writer, "w", zipfile.ZIP_DEFLATED) as zipf:
                zipf.writestr(DB_NAME, db.snapshot())
                for name, folder in folders.items():
                    for root, _, files in os.walk(folder):
                        for file in files:
                            full = os.path.join(root, file)
                            zipf.write(full, f"{name}/{os.path.relpath(full, folder).replace(os.sep, '/')}")
            writer.finish()
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    except BaseException:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise


def _decrypt(path: str, password: str, out):
    with open(path, "rb") as f:
        header = f.read(HEADER_SIZE)
        if len(header) < HEADER_SIZE or not header.startswith(MAGIC):
            raise ValueError("Die Datei ist kein gültiges Schalk-Backup.")
        (iterations,) = struct.unpack(">I", header[len(MAGIC):len(MAGIC) + 4])
        aead = _derive_key(password, header[len(MAGIC) + 4:len(MAGIC) + 4 + SALT_SIZE], iterations)
        prefix = header[-PREFIX_SIZE:]
        counter = 0
        block = f.read(CHUNK_SIZE + TAG_SIZE)
        while True:
            following = f.read(CHUNK_SIZE + TAG_SIZE)
            last = not following
            try:
                out.write(aead.decrypt(_nonce(prefix, counter, last), block, header))
            except InvalidTag:
                if counter == 0:
                    raise WrongPasswordError("Falsches Backup-Passwort.")
                raise ValueError("Das Backup ist beschädigt oder unvollständig.")
            if last:
                return
            block = following
            counter += 1


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


def restore_backup(db, path: str, password: str, folders: dict):
    """
    Restores a .backup file: the current database is kept as .bak copy and replaced, missing documents
    are added to the folders. Raises WrongPasswordError before anything is changed.
    The application must be restarted afterwards.
    """
    with tempfile.SpooledTemporaryFile(max_size=SPOOL_LIMIT, dir=os.path.dirname(db.db_path) or None) as plain:
        _decrypt(path, password, plain)
        plain.seek(0)
        try:
            zipf = zipfile.ZipFile(plain)
        except zipfile.BadZipFile:
            raise ValueError("Das Backup enthält keine gültigen Daten.")
        with zipf:
            if DB_NAME not in zipf.namelist():
                raise ValueError("Das Backup enthält keine Datenbank.")
            data = zipf.read(DB_NAME)
            # The writer is flushed first so the .bak copy is complete
            db.flush()
            if os.path.exists(db.db_path):
                shutil.copy2(db.db_path, f"{db.db_path}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}")
            db.restore_database(data)
            _extract_missing(zipf, folders)
