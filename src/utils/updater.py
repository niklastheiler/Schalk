"""
Automatic updates from GitHub releases.

Schalk is installed with Schalk-Setup (into C:\\Program Files\\Schalk). On every start the latest release
is looked up. If it is newer, its setup is downloaded and verified against the SHA-256 digest GitHub
publishes for every release asset. After Schalk has exited, a small script runs the setup silently with
administrator rights (Windows asks once via UAC); the setup replaces the program files and starts the
new version. User data lives in %LOCALAPPDATA%\\Schalk and is not touched. Only the installed EXE updates
itself; a source checkout (python run.py) is never modified.
"""
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from typing import Optional
from src.utils import paths
from src.version import APP_VERSION

logger = logging.getLogger(__name__)

REPOSITORY = "niklastheiler/Schalk"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
SETUP_PATTERN = re.compile(r"Schalk-Setup-v(?P<version>[\d.]+)\.exe")
SETUP_ARGS = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART"
UPDATE_DIR = os.path.join(paths.DATA_DIR, "updates")
APPLY_SCRIPT = os.path.join(UPDATE_DIR, "apply_update.cmd")
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


def build_apply_script(setup: str, pid: int, restart: bool) -> str:
    """
    Waits for Schalk (pid) to exit, then runs the setup silently with administrator rights. /STARTAPP=1
    makes the setup start the new version afterwards. If the user declines the UAC prompt nothing changes
    and the update is offered again on the next start.
    """
    arguments = f"{SETUP_ARGS} /STARTAPP={1 if restart else 0}"
    return "\r\n".join([
        "@echo off",
        ":wait",
        f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul && (timeout /t 1 /nobreak >nul & goto wait)',
        f"powershell -NoProfile -ExecutionPolicy Bypass -Command \"Start-Process -FilePath '{setup}' "
        f"-ArgumentList '{arguments}' -Verb RunAs\"",
        'del "%~f0" & exit /b 0',
        "",
    ])


def apply_on_exit(version: str, restart: bool):
    """Starts the installer script detached; it waits until this process has exited."""
    with open(APPLY_SCRIPT, "w", encoding="ascii", errors="replace") as f:
        f.write(build_apply_script(staged_setup(version), os.getpid(), restart))
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    subprocess.Popen(["cmd.exe", "/c", APPLY_SCRIPT], creationflags=flags, close_fds=True, cwd=UPDATE_DIR)
    logger.info("Update auf %s wird nach dem Beenden installiert (Neustart: %s)", version, restart)
