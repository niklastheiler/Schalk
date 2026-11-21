"""
Portable backups: a single encrypted .backup file with the database and all archived documents.

File format: MAGIC | iterations (uint32 BE) | salt (16 bytes) | nonce prefix (7 bytes) | password check (16 bytes) | chunks
The payload is a ZIP archive, streamed in chunks of 1 MiB and encrypted with AES-256-GCM (key derived
from the backup password with PBKDF2). Each nonce holds the chunk counter and a final-chunk flag, so
reordered, missing or cut-off chunks are detected; the header is authenticated with every chunk.
The password check (the GCM tag of an empty message) tells a wrong password apart from a damaged file.
Backups of version 1 (Schalk up to 1.2.3) have no password check and are still read.
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
from src.utils.archive import make_read_only

MAGIC = b"SCHALKB\x02"
MAGIC_V1 = b"SCHALKB\x01"
SALT_SIZE = 16
PREFIX_SIZE = 7
# Header without the password check (version 1 ends here)
HEADER_SIZE = len(MAGIC) + 4 + SALT_SIZE + PREFIX_SIZE
CHECK_SIZE = 16
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


def _check_nonce(prefix: bytes) -> bytes:
    # Never used for a chunk: chunk nonces end with 0x00 or 0x01
    return prefix + b"\xff\xff\xff\xff\x02"


class _EncryptingWriter:
    """Write-only stream for zipfile that encrypts everything written to it chunk by chunk."""

    def __init__(self, f, aead: AESGCM, header: bytes, prefix: bytes):
        self._f = f
        self._aead = aead
        self._header = header
        self._prefix = prefix
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


def create_backup(snapshot: bytes, path: str, password: str, folders: dict):
    """
    Writes a database snapshot (DatabaseManager.snapshot()) and the given folders ({name in backup: directory})
    into one .backup file. Needs no access to the running database, so it can run on a worker thread.
    """
    salt, prefix = os.urandom(SALT_SIZE), os.urandom(PREFIX_SIZE)
    core = MAGIC + struct.pack(">I", KDF_ITERATIONS) + salt + prefix
    aead = _derive_key(password, salt, KDF_ITERATIONS)
    header = core + aead.encrypt(_check_nonce(prefix), b"", core)
    temp_path = path + ".tmp"
    try:
        with open(temp_path, "wb") as f:
            f.write(header)
            writer = _EncryptingWriter(f, aead, header, prefix)
            with zipfile.ZipFile(writer, "w", zipfile.ZIP_DEFLATED) as zipf:
                zipf.writestr(DB_NAME, snapshot)
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
        version = {MAGIC: 2, MAGIC_V1: 1}.get(header[:len(MAGIC)])
        if len(header) < HEADER_SIZE or version is None:
            raise ValueError("Die Datei ist kein gültiges Schalk-Backup.")
        (iterations,) = struct.unpack(">I", header[len(MAGIC):len(MAGIC) + 4])
        aead = _derive_key(password, header[len(MAGIC) + 4:len(MAGIC) + 4 + SALT_SIZE], iterations)
        prefix = header[-PREFIX_SIZE:]
        if version == 2:
            check = f.read(CHECK_SIZE)
            if len(check) < CHECK_SIZE:
                raise ValueError("Das Backup ist beschädigt oder unvollständig.")
            try:
                aead.decrypt(_check_nonce(prefix), check, header)
            except InvalidTag:
                raise WrongPasswordError("Falsches Backup-Passwort.")
            header += check
        counter = 0
        block = f.read(CHUNK_SIZE + TAG_SIZE)
        while True:
            following = f.read(CHUNK_SIZE + TAG_SIZE)
            last = not following
            try:
                out.write(aead.decrypt(_nonce(prefix, counter, last), block, header))
            except InvalidTag:
                # Version 1 cannot tell a wrong password from a damaged first chunk
                if counter == 0 and version == 1:
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
        # Restored documents are archived documents again (GoBD: read-only)
        make_read_only(dest)


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
