import hashlib
import logging
import os
import shutil
import stat
# Only icacls with fixed arguments is started (see _icacls)
import subprocess  # nosec B404
from datetime import datetime

logger = logging.getLogger(__name__)

# Windows paths are limited to 260 characters; long names of downloaded files are shortened
MAX_NAME_LENGTH = 80


def file_sha256(path: str) -> str:
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def is_pdf(path: str) -> bool:
    """Checks the file signature, not just the extension."""
    with open(path, "rb") as f:
        return f.read(5) == b"%PDF-"


def archive_file(source_path: str, target_dir: str, prefix: str = "", extension: str = None) -> tuple:
    """
    Copies a file into the archive directory under a unique name and marks it read-only
    (GoBD: archived documents must not be overwritten or altered).
    extension replaces the file's own extension: a PDF is always archived as .pdf, so opening it never
    runs a disguised program (e.g. a script named Rechnung.bat that starts with %PDF-).
    Returns (archived_path, sha256).
    """
    os.makedirs(target_dir, exist_ok=True)
    stem, own_extension = os.path.splitext(os.path.basename(source_path))
    name = f"{prefix}{datetime.now():%Y%m%d%H%M%S%f}_{stem[:MAX_NAME_LENGTH]}"
    extension = extension or own_extension
    dest_path = os.path.join(target_dir, name + extension)
    counter = 1
    while os.path.exists(dest_path):
        counter += 1
        dest_path = os.path.join(target_dir, f"{name}_{counter}{extension}")

    shutil.copy2(source_path, dest_path)
    make_read_only(dest_path)
    return dest_path, file_sha256(dest_path)


def make_read_only(path: str):
    try:
        os.chmod(path, stat.S_IREAD)
    except OSError:
        pass


def remove_tree(path: str):
    """Deletes a folder with archived (read-only) files; Windows refuses to delete read-only files otherwise."""
    def make_writable(function, failed_path, error):
        os.chmod(failed_path, stat.S_IWRITE)
        function(failed_path)
    if os.path.isdir(path):
        unprotect_folder(path)
        shutil.rmtree(path, onexc=make_writable)


def verify_file(path: str, expected_hash: str) -> bool:
    if not path or not expected_hash or not os.path.isfile(path):
        return False
    return file_sha256(path) == expected_hash


# "Everyone" (well-known SID, independent of the Windows language). Deny deleting: the folder itself (DE) and
# its contents (DC), inherited by every file and subfolder (OI)(CI). Adding new files stays allowed.
_EVERYONE = "*S-1-1-0"
_DENY_DELETE = "(OI)(CI)(DE,DC)"
_ICACLS = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "icacls.exe")


def _icacls(*args) -> subprocess.CompletedProcess:
    return subprocess.run([_ICACLS, *args], capture_output=True, text=True, errors="replace", timeout=120,  # nosec B603
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def protect_folder(path: str) -> bool:
    """
    Protects an archive folder against deleting and renaming its documents in Windows Explorer (GoBD: archived
    documents must stay available). Only on Windows; idempotent. Returns True if the folder is protected.
    An administrator can lift the protection: icacls "<Ordner>" /remove:d *S-1-1-0 /T
    """
    if os.name != "nt":
        return False
    os.makedirs(path, exist_ok=True)
    try:
        if "(DE,DC)" in _icacls(path).stdout:
            return True
        result = _icacls(path, "/deny", f"{_EVERYONE}:{_DENY_DELETE}")
        if result.returncode != 0:
            logger.warning("Löschschutz für %s nicht gesetzt: %s", path, (result.stdout + result.stderr).strip())
            return False
        logger.info("Löschschutz für %s gesetzt", path)
        return True
    except (OSError, subprocess.SubprocessError):
        logger.warning("Löschschutz für %s nicht gesetzt", path, exc_info=True)
        return False


def unprotect_folder(path: str):
    """Lifts the protection (only for removing a temporary data folder, e.g. after the self-test)."""
    if os.name == "nt" and os.path.isdir(path):
        try:
            _icacls(path, "/remove:d", _EVERYONE, "/T", "/C")
        except (OSError, subprocess.SubprocessError):
            logger.warning("Löschschutz für %s nicht aufgehoben", path, exc_info=True)
