"""
Automatic updates from GitHub releases.

On every start the latest release is looked up. If it is newer, its ZIP is downloaded, verified against
the SHA-256 digest GitHub publishes for the asset and unpacked into a staging folder. The new files are
copied over the program folder by a small batch script that waits until Schalk has exited, so the
running program never replaces its own files. User data lives in %LOCALAPPDATA%\\Schalk and is not touched.
Only the packaged EXE updates itself; a source checkout (python run.py) is never modified.
"""
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from typing import Optional
from src.utils import paths
from src.version import APP_VERSION

logger = logging.getLogger(__name__)

REPOSITORY = "niklastheiler/Schalk"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
ASSET_PATTERN = re.compile(r"Schalk-v(?P<version>[\d.]+)-windows-x64\.zip")
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


def is_newer(candidate: str, current: str = APP_VERSION) -> bool:
    return version_key(candidate) > version_key(current)


def is_installed_build() -> bool:
    """Only the packaged EXE updates itself."""
    return bool(getattr(sys, "frozen", False))


def install_dir() -> str:
    return os.path.dirname(os.path.abspath(sys.executable))


def _request(url: str, accept: str = "application/vnd.github+json"):
    request = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": f"Schalk/{APP_VERSION}"})
    return urllib.request.urlopen(request, timeout=TIMEOUT)


def parse_release(data: dict) -> Optional[Release]:
    """The release's Windows ZIP, or None if the release has none (or is a draft/pre-release)."""
    if data.get("draft") or data.get("prerelease"):
        return None
    for asset in data.get("assets", []):
        match = ASSET_PATTERN.fullmatch(asset.get("name", ""))
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


def fetch_latest_release() -> Optional[Release]:
    with _request(LATEST_RELEASE_URL) as response:
        return parse_release(json.load(response))


def find_update() -> Optional[Release]:
    """The latest release if it is newer than the running version."""
    release = fetch_latest_release()
    if release and is_newer(release.version):
        return release
    return None


def staged_dir(version: str) -> str:
    return os.path.join(UPDATE_DIR, f"Schalk-{version}")


def staged_version() -> Optional[str]:
    """Version of a completely prepared update waiting to be installed."""
    if not os.path.isdir(UPDATE_DIR):
        return None
    versions = [name[len("Schalk-"):] for name in os.listdir(UPDATE_DIR)
                if name.startswith("Schalk-") and os.path.isfile(os.path.join(UPDATE_DIR, name, "Schalk.exe"))]
    newer = [v for v in versions if is_newer(v)]
    return max(newer, key=version_key) if newer else None


def download(release: Release, progress=None) -> str:
    """Downloads, verifies and unpacks the release. Returns the staged program folder."""
    target = staged_dir(release.version)
    if os.path.isfile(os.path.join(target, "Schalk.exe")):
        return target
    os.makedirs(UPDATE_DIR, exist_ok=True)
    sha256 = hashlib.sha256()
    fd, zip_path = tempfile.mkstemp(suffix=".zip", dir=UPDATE_DIR)
    try:
        with os.fdopen(fd, "wb") as f, _request(release.url, accept="application/octet-stream") as response:
            done = 0
            for chunk in iter(lambda: response.read(1 << 20), b""):
                f.write(chunk)
                sha256.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, release.size)
        if release.sha256 and sha256.hexdigest() != release.sha256:
            raise ValueError("Die heruntergeladene Datei ist beschädigt (Prüfsumme stimmt nicht).")
        _unpack(zip_path, target)
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)
    return target


def _unpack(zip_path: str, target: str):
    temp_target = target + ".partial"
    shutil.rmtree(temp_target, ignore_errors=True)
    with zipfile.ZipFile(zip_path) as archive:
        root = os.path.abspath(temp_target)
        for member in archive.infolist():
            # Nothing may be written outside the staging folder
            dest = os.path.abspath(os.path.join(root, member.filename))
            if os.path.commonpath([root, dest]) != root:
                raise ValueError(f"Ungültiger Pfad im Update: {member.filename}")
        archive.extractall(temp_target)
    # The release ZIP contains the folder "Schalk" with Schalk.exe and _internal
    program = os.path.join(temp_target, "Schalk")
    if not os.path.isfile(os.path.join(program, "Schalk.exe")):
        shutil.rmtree(temp_target, ignore_errors=True)
        raise ValueError("Das Update enthält kein Schalk.exe.")
    shutil.rmtree(target, ignore_errors=True)
    os.replace(program, target)
    shutil.rmtree(temp_target, ignore_errors=True)


def build_apply_script(source: str, destination: str, pid: int, restart: bool) -> str:
    """
    Batch script that waits for Schalk (pid) to exit, replaces the program files and optionally restarts.
    _internal is removed first so no files of the old version remain; other files in the folder stay.
    """
    restart_line = f'start "" "{destination}\\Schalk.exe"' if restart else "rem no restart"
    return "\r\n".join([
        "@echo off",
        "setlocal",
        ":wait",
        f'tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul && (timeout /t 1 /nobreak >nul & goto wait)',
        f'if exist "{destination}\\_internal" rmdir /s /q "{destination}\\_internal"',
        f'robocopy "{source}" "{destination}" /E /R:10 /W:1 /NFL /NDL /NJH /NJS /NP >nul',
        "if errorlevel 8 goto failed",
        f'rmdir /s /q "{source}"',
        restart_line,
        'del "%~f0" & exit /b 0',
        ":failed",
        f'echo Update fehlgeschlagen, robocopy-Code %errorlevel% > "{UPDATE_DIR}\\update_error.log"',
        restart_line,
        "exit /b 1",
        "",
    ])


def apply_on_exit(version: str, restart: bool):
    """Starts the installer script detached; it waits until this process has exited."""
    destination = install_dir()
    if not (os.path.isfile(os.path.join(destination, "Schalk.exe")) and os.path.isdir(os.path.join(destination, "_internal"))):
        raise RuntimeError(f"Unerwarteter Programmordner: {destination}")
    with open(APPLY_SCRIPT, "w", encoding="ascii", errors="replace") as f:
        f.write(build_apply_script(staged_dir(version), destination, os.getpid(), restart))
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    subprocess.Popen(["cmd.exe", "/c", APPLY_SCRIPT], creationflags=flags, close_fds=True, cwd=UPDATE_DIR)
    logger.info("Update auf %s wird nach dem Beenden installiert (Neustart: %s)", version, restart)


def can_write_install_dir() -> bool:
    """Updating needs write access to the program folder (not given under C:\\Program Files)."""
    try:
        probe = os.path.join(install_dir(), ".schalk_update_probe")
        with open(probe, "w"):
            pass
        os.remove(probe)
        return True
    except OSError:
        return False
