"""
Automatic updates from GitHub releases.

Schalk is installed with Schalk-Setup (into C:\\Program Files\\Schalk). On every start the latest release
is looked up. If it is newer, its setup is downloaded and verified against the SHA-256 digest GitHub
publishes for every release asset. When Schalk exits, the database is backed up and the setup runs silently
with administrator rights (Windows asks once via UAC); the setup replaces the program files and starts the
new version. User data lives in %LOCALAPPDATA%\\Schalk and is not touched. Only the installed EXE updates
itself; a source checkout (python run.py) is never modified.
"""
import ctypes
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from src.utils import paths
from src.version import APP_VERSION

logger = logging.getLogger(__name__)

REPOSITORY = "niklastheiler/Schalk"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
SETUP_PATTERN = re.compile(r"Schalk-Setup-v(?P<version>[\d.]+)\.exe")
SETUP_ARGS = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CLOSEAPPLICATIONS"
UPDATE_DIR = os.path.join(paths.DATA_DIR, "updates")
SETUP_LOG = os.path.join(UPDATE_DIR, "setup.log")
BACKUP_DIR = os.path.join(paths.DATA_DIR, "backups")
BACKUPS_KEPT = 5
TIMEOUT = 30


@dataclass
class Release:
    version: str
    url: str
    size: int
    sha256: Optional[str]
    notes: str


def version_key(version: str) -> tuple:
    """'1.10.2' -> (1, 10, 2); '1.1' == '1.1.0'."""
    parts = [int(p) for p in re.findall(r"\d+", version)]
    while parts and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def is_newer(candidate: str, current: Optional[str] = None) -> bool:
    return version_key(candidate) > version_key(current or APP_VERSION)


def is_installed() -> bool:
    """Only an installation made with Schalk-Setup (it has an uninstaller) updates itself."""
    if not getattr(sys, "frozen", False):
        return False
    return os.path.isfile(os.path.join(os.path.dirname(os.path.abspath(sys.executable)), "unins000.exe"))


def _request(url: str, accept: str = "application/vnd.github+json"):
    request = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": f"Schalk/{APP_VERSION}"})
    return urllib.request.urlopen(request, timeout=TIMEOUT)


def parse_release(data: dict) -> Optional[Release]:
    """The release's setup, or None if it has none (or is a draft/pre-release)."""
    if data.get("draft") or data.get("prerelease"):
        return None
    for asset in data.get("assets", []):
        match = SETUP_PATTERN.fullmatch(asset.get("name", ""))
        if match:
            digest = asset.get("digest") or ""
            return Release(
                version=match.group("version"),
                url=asset["browser_download_url"],
                size=int(asset.get("size") or 0),
                sha256=digest.split(":", 1)[1].lower() if digest.startswith("sha256:") else None,
                notes=(data.get("body") or "").strip(),
            )
    return None


def find_update() -> Optional[Release]:
    """The latest release if it is newer than the running version."""
    with _request(LATEST_RELEASE_URL) as response:
        release = parse_release(json.load(response))
    if release and is_newer(release.version):
        return release
    return None


def staged_setup(version: str) -> str:
    return os.path.join(UPDATE_DIR, f"Schalk-Setup-v{version}.exe")


def _staged_versions() -> dict:
    """version -> path of every downloaded and verified setup."""
    if not os.path.isdir(UPDATE_DIR):
        return {}
    return {m.group("version"): os.path.join(UPDATE_DIR, name)
            for name in os.listdir(UPDATE_DIR) if (m := SETUP_PATTERN.fullmatch(name))}


def staged_version() -> Optional[str]:
    """Version of a downloaded update waiting to be installed."""
    newer = [v for v in _staged_versions() if is_newer(v)]
    return max(newer, key=version_key) if newer else None


def remove_installed_updates():
    """Deletes setups of versions that are already installed (or older)."""
    for version, path in _staged_versions().items():
        if not is_newer(version):
            os.remove(path)


def download(release: Release, progress=None) -> str:
    """Downloads the setup and verifies its SHA-256 digest. Returns the path of the verified setup."""
    target = staged_setup(release.version)
    if os.path.isfile(target):
        return target
    os.makedirs(UPDATE_DIR, exist_ok=True)
    sha256 = hashlib.sha256()
    # Only a complete and verified download gets the setup's name
    fd, temp_path = tempfile.mkstemp(suffix=".download", dir=UPDATE_DIR)
    try:
        with os.fdopen(fd, "wb") as f, _request(release.url, accept="application/octet-stream") as response:
            done = 0
            for chunk in iter(lambda: response.read(1 << 20), b""):
                f.write(chunk)
                sha256.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, release.size)
        if not release.sha256:
            raise ValueError("Für das Update ist keine Prüfsumme veröffentlicht.")
        if sha256.hexdigest() != release.sha256:
            raise ValueError("Die heruntergeladene Datei ist beschädigt (Prüfsumme stimmt nicht).")
        os.replace(temp_path, target)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    return target


def backup_database(version: str) -> str:
    """
    Copies the encrypted database and its key before an update (the database is closed at this point).
    The newest BACKUPS_KEPT copies are kept in %LOCALAPPDATA%\\Schalk\\backups.
    """
    target = os.path.join(BACKUP_DIR, f"vor-update-{version}-{datetime.now():%Y%m%d-%H%M%S}")
    os.makedirs(target)
    for path in (paths.DB_PATH, paths.KEY_PATH):
        if os.path.isfile(path):
            shutil.copy2(path, target)
    old = sorted(name for name in os.listdir(BACKUP_DIR) if name.startswith("vor-update-"))
    for name in old[:-BACKUPS_KEPT]:
        shutil.rmtree(os.path.join(BACKUP_DIR, name), ignore_errors=True)
    return target


def setup_arguments(restart: bool) -> str:
    """/STARTAPP=1 makes the setup start the new version afterwards; the log helps if an update fails."""
    return f'{SETUP_ARGS} /STARTAPP={1 if restart else 0} /LOG="{SETUP_LOG}"'


def apply_on_exit(version: str, restart: bool):
    """
    Called while Schalk exits, after the database is closed: backs up the database, then starts the setup
    with administrator rights (Windows asks once). The setup closes the remaining Schalk process, replaces the
    program files and starts the new version. If the UAC prompt is declined, nothing changes and the update is
    offered again on the next start.
    """
    backup = backup_database(version)
    logger.info("Datenbank vor dem Update gesichert: %s", backup)
    setup = staged_setup(version)
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", setup, setup_arguments(restart), UPDATE_DIR, 1)
    if result <= 32: # ShellExecute reports errors as values up to 32 (e.g. 5 = declined or no rights)
        raise OSError(f"Setup konnte nicht gestartet werden (Fehler {result})")
    logger.info("Update auf %s gestartet (Neustart: %s)", version, restart)
