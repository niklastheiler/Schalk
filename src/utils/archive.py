import hashlib
import os
import shutil
import stat
from datetime import datetime


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


def archive_file(source_path: str, target_dir: str, prefix: str = "") -> tuple:
    """
    Copies a file into the archive directory under a unique name and marks it read-only
    (GoBD: archived documents must not be overwritten or altered).
    Returns (archived_path, sha256).
    """
    os.makedirs(target_dir, exist_ok=True)
    filename = os.path.basename(source_path)
    stamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
    safe_name = f"{prefix}{stamp}_{filename}" if prefix else f"{stamp}_{filename}"
    dest_path = os.path.join(target_dir, safe_name)

    shutil.copy2(source_path, dest_path)
    make_read_only(dest_path)
    return dest_path, file_sha256(dest_path)


def make_read_only(path: str):
    try:
        os.chmod(path, stat.S_IREAD)
    except OSError:
        pass


def verify_file(path: str, expected_hash: str) -> bool:
    if not path or not expected_hash or not os.path.isfile(path):
        return False
    return file_sha256(path) == expected_hash
