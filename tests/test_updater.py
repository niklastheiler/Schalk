import hashlib
import io
import zipfile
import pytest
from src.utils import updater

SHA = "0" * 64


def _release_json(version="1.2", **asset):
    data = {"name": f"Schalk-v{version}-windows-x64.zip", "browser_download_url": f"https://example.org/v{version}.zip",
            "size": 10, "digest": f"sha256:{SHA}"}
    data.update(asset)
    return {"tag_name": f"v{version}", "body": "Neu: Updates", "draft": False, "prerelease": False,
            "assets": [{"name": "Quellcode.zip"}, data]}


def _zip(files: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


@pytest.fixture
def update_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "UPDATE_DIR", str(tmp_path / "updates"))
    monkeypatch.setattr(updater, "APP_VERSION", "1.1.1")
    return tmp_path / "updates"


def test_versions_are_compared_numerically(monkeypatch):
    assert updater.version_key("1.10") > updater.version_key("1.9")
    assert updater.version_key("1.1") == updater.version_key("1.1.0")
    assert updater.is_newer("1.2", "1.1.1") and not updater.is_newer("1.1.1", "1.1.1") and not updater.is_newer("1.0", "1.1")


def test_release_asset_is_found_with_digest():
    release = updater.parse_release(_release_json())
    assert (release.version, release.sha256, release.notes) == ("1.2", SHA, "Neu: Updates")
    assert updater.parse_release(dict(_release_json(), draft=True)) is None
    assert updater.parse_release({"assets": [{"name": "Quellcode.zip"}]}) is None


def _serve(monkeypatch, payload: bytes):
    monkeypatch.setattr(updater, "_request", lambda url, accept=None: io.BytesIO(payload))


def test_download_verifies_and_stages_the_program(update_dir, monkeypatch):
    payload = _zip({"Schalk/Schalk.exe": "exe", "Schalk/_internal/lib.dll": "dll"})
    release = updater.Release("1.2", "https://example.org/x.zip", len(payload), hashlib.sha256(payload).hexdigest(), "")
    _serve(monkeypatch, payload)
    staged = updater.download(release)
    assert (update_dir / "Schalk-1.2" / "_internal" / "lib.dll").read_text() == "dll"
    assert staged == updater.staged_dir("1.2") and updater.staged_version() == "1.2"
    assert [p.name for p in update_dir.iterdir()] == ["Schalk-1.2"] # no leftovers


def test_damaged_or_malicious_downloads_are_rejected(update_dir, monkeypatch):
    payload = _zip({"Schalk/Schalk.exe": "exe"})
    _serve(monkeypatch, payload)
    with pytest.raises(ValueError, match="Prüfsumme"):
        updater.download(updater.Release("1.2", "u", len(payload), SHA, ""))
    evil = _zip({"Schalk/Schalk.exe": "exe", "../../evil.cmd": "x"})
    _serve(monkeypatch, evil)
    with pytest.raises(ValueError, match="Ungültiger Pfad"):
        updater.download(updater.Release("1.3", "u", len(evil), hashlib.sha256(evil).hexdigest(), ""))
    without_exe = _zip({"Schalk/readme.txt": "x"})
    _serve(monkeypatch, without_exe)
    with pytest.raises(ValueError, match="kein Schalk.exe"):
        updater.download(updater.Release("1.4", "u", 1, None, ""))
    assert updater.staged_version() is None


def test_older_staged_versions_are_ignored(update_dir):
    (update_dir / "Schalk-1.1").mkdir(parents=True)
    (update_dir / "Schalk-1.1" / "Schalk.exe").write_text("alt")
    assert updater.staged_version() is None


def test_apply_script_waits_replaces_and_restarts():
    script = updater.build_apply_script(r"C:\U\Schalk-1.2", r"C:\Apps\Schalk", 4711, restart=True)
    assert 'PID eq 4711' in script and r'rmdir /s /q "C:\Apps\Schalk\_internal"' in script
    assert r'robocopy "C:\U\Schalk-1.2" "C:\Apps\Schalk" /E' in script
    assert script.count(r'start "" "C:\Apps\Schalk\Schalk.exe"') == 2 # also after a failed copy
    assert 'start ""' not in updater.build_apply_script("a", "b", 1, restart=False)


def test_apply_refuses_unexpected_program_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "install_dir", lambda: str(tmp_path))
    with pytest.raises(RuntimeError):
        updater.apply_on_exit("1.2", restart=True)


def test_notifier_downloads_and_installs_on_exit(window, qapp, monkeypatch):
    from qfluentwidgets import MessageBox
    notifier = window.updates
    notifier.start() # source checkout: nothing happens
    assert notifier.pending_version is None

    release = updater.Release("1.2", "u", 1, None, "")
    applied = []
    monkeypatch.setattr(updater, "is_installed_build", lambda: True)
    monkeypatch.setattr(updater, "staged_version", lambda: None)
    monkeypatch.setattr(updater, "find_update", lambda: release)
    monkeypatch.setattr(updater, "can_write_install_dir", lambda: True)
    monkeypatch.setattr(updater, "download", lambda r: updater.staged_dir(r.version))
    monkeypatch.setattr(updater, "apply_on_exit", lambda version, restart: applied.append((version, restart)))
    monkeypatch.setattr(MessageBox, "exec", lambda self: 0) # "Später"
    notifier._check_and_download() # what the background thread runs
    qapp.processEvents()
    assert notifier.pending_version == "1.2" and not notifier.restart
    notifier.install_on_exit()
    assert applied == [("1.2", False)]


def test_restart_now_saves_and_installs_with_restart(window, qapp, monkeypatch):
    from qfluentwidgets import MessageBox
    applied = []
    monkeypatch.setattr(updater, "apply_on_exit", lambda version, restart: applied.append((version, restart)))
    monkeypatch.setattr(MessageBox, "exec", lambda self: 1) # "Jetzt neu starten"
    window.updates.ready.emit("1.2")
    qapp.processEvents()
    assert applied == [("1.2", True)] and window.db_controller.db._closed
