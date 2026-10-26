import hashlib
import json
import io
import pytest
from src.utils import updater

PAYLOAD = b"MZ fake setup"
SHA = hashlib.sha256(PAYLOAD).hexdigest()


def _release_json(version="1.2", **asset):
    data = {"name": f"Schalk-Setup-v{version}.exe", "browser_download_url": f"https://example.org/v{version}.exe",
            "size": len(PAYLOAD), "digest": f"sha256:{SHA}"}
    data.update(asset)
    return {"tag_name": f"v{version}", "body": "Neu: Updates", "draft": False, "prerelease": False,
            "assets": [{"name": "Quellcode.zip"}, data]}


@pytest.fixture
def update_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "UPDATE_DIR", str(tmp_path / "updates"))
    monkeypatch.setattr(updater, "APP_VERSION", "1.1.1")
    return tmp_path / "updates"


def _serve(monkeypatch, payload: bytes):
    monkeypatch.setattr(updater, "_request", lambda url, accept=None: io.BytesIO(payload))


def test_versions_are_compared_numerically():
    assert updater.version_key("1.10") > updater.version_key("1.9")
    assert updater.version_key("1.1") == updater.version_key("1.1.0")
    assert updater.is_newer("1.2", "1.1.1") and not updater.is_newer("1.1.1", "1.1.1") and not updater.is_newer("1.0", "1.1")


def test_setup_asset_is_found_with_digest():
    release = updater.parse_release(_release_json())
    assert (release.version, release.sha256, release.notes) == ("1.2", SHA, "Neu: Updates")
    assert updater.parse_release(dict(_release_json(), draft=True)) is None
    assert updater.parse_release({"assets": [{"name": "Schalk-v1.2-windows-x64.zip"}]}) is None


def test_only_newer_releases_are_offered(update_dir, monkeypatch):
    for version, offered in (("1.2", True), ("1.1.1", False), ("1.0", False)):
        _serve(monkeypatch, json.dumps(_release_json(version)).encode())
        assert (updater.find_update() is not None) == offered


def test_download_is_verified_and_staged(update_dir, monkeypatch):
    _serve(monkeypatch, PAYLOAD)
    path = updater.download(updater.parse_release(_release_json()))
    assert path == updater.staged_setup("1.2") and open(path, "rb").read() == PAYLOAD
    assert updater.staged_version() == "1.2"
    assert [p.name for p in update_dir.iterdir()] == ["Schalk-Setup-v1.2.exe"] # no partial download left


def test_damaged_or_unverifiable_downloads_are_rejected(update_dir, monkeypatch):
    _serve(monkeypatch, b"manipuliert")
    with pytest.raises(ValueError, match="Prüfsumme stimmt nicht"):
        updater.download(updater.parse_release(_release_json()))
    _serve(monkeypatch, PAYLOAD)
    with pytest.raises(ValueError, match="keine Prüfsumme"):
        updater.download(updater.parse_release(_release_json(digest=None)))
    assert updater.staged_version() is None and list(update_dir.iterdir()) == []


def test_installed_versions_are_cleaned_up(update_dir):
    update_dir.mkdir()
    for version in ("1.1", "1.1.1", "1.3"):
        (update_dir / f"Schalk-Setup-v{version}.exe").write_bytes(b"x")
    assert updater.staged_version() == "1.3"
    updater.remove_installed_updates()
    assert [p.name for p in update_dir.iterdir()] == ["Schalk-Setup-v1.3.exe"]


def test_apply_script_waits_then_runs_setup_elevated():
    script = updater.build_apply_script(r"C:\U\Schalk-Setup-v1.2.exe", 4711, restart=True)
    assert 'PID eq 4711' in script
    assert r"Start-Process -FilePath 'C:\U\Schalk-Setup-v1.2.exe'" in script and "-Verb RunAs" in script
    assert "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /STARTAPP=1" in script
    assert "/STARTAPP=0" in updater.build_apply_script("s", 1, restart=False)


def test_source_checkout_never_updates(window):
    assert not updater.is_installed()
    window.updates.start()
    assert window.updates.pending_version is None


def test_notifier_downloads_and_installs_on_exit(window, qapp, monkeypatch):
    from qfluentwidgets import MessageBox
    notifier = window.updates
    release = updater.parse_release(_release_json())
    applied = []
    monkeypatch.setattr(updater, "find_update", lambda: release)
    monkeypatch.setattr(updater, "download", lambda r: updater.staged_setup(r.version))
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
