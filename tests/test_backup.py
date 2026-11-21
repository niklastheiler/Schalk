import os
import stat
import struct
import zipfile
import pytest
from src.models.database import WrongPasswordError
from src.utils import backup
from src.utils.backup import create_backup, restore_backup


def _folders(root):
    return {"app_data": str(root / "app_data"), "assets": str(root / "assets")}


def test_single_backup_file_with_documents(controller, tmp_path, monkeypatch):
    # Small chunks so the archive spans many encrypted chunks
    monkeypatch.setattr(backup, "CHUNK_SIZE", 1024)
    source = tmp_path / "source"
    (source / "app_data" / "archive").mkdir(parents=True)
    (source / "assets").mkdir()
    big = os.urandom(10_000)
    (source / "app_data" / "archive" / "R-1.pdf").write_bytes(big)
    (source / "assets" / "logo.png").write_bytes(b"logo")
    controller.add_customer(company_name="Im Backup")

    path = tmp_path / "Schalk.backup"
    create_backup(controller.db.snapshot(), str(path), "geheim123", _folders(source))
    data = path.read_bytes()
    assert data.startswith(backup.MAGIC) and not zipfile.is_zipfile(path)
    assert b"Im Backup" not in data and not os.path.exists(f"{path}.tmp")

    target = tmp_path / "target"
    (target / "assets").mkdir(parents=True)
    (target / "assets" / "logo.png").write_bytes(b"vorhanden")
    with pytest.raises(WrongPasswordError):
        restore_backup(controller.db, str(path), "falsch", _folders(target))
    assert not (target / "app_data").exists()

    restore_backup(controller.db, str(path), "geheim123", _folders(target))
    restored = target / "app_data" / "archive" / "R-1.pdf"
    assert restored.read_bytes() == big
    # Restored documents are archived documents again: read-only
    assert not os.stat(restored).st_mode & stat.S_IWRITE
    # Existing (read-only archived) files are never overwritten
    assert (target / "assets" / "logo.png").read_bytes() == b"vorhanden"


def test_damaged_or_foreign_backup_is_rejected(controller, tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "CHUNK_SIZE", 1024)
    path = tmp_path / "b.backup"
    create_backup(controller.db.snapshot(), str(path), "geheim123", {})
    data = path.read_bytes()

    # A damaged or cut-off file is reported as such, also when the first chunk is affected,
    # and never as a wrong password
    header = backup.HEADER_SIZE + backup.CHECK_SIZE
    for name, damaged in (("truncated", data[:-(1024 + backup.TAG_SIZE)]), ("first_chunk_only", data[:header + 100]),
                          ("flipped_end", data[:-5] + bytes([data[-5] ^ 1]) + data[-4:]),
                          ("flipped_start", data[:header + 3] + bytes([data[header + 3] ^ 1]) + data[header + 4:])):
        (tmp_path / f"{name}.backup").write_bytes(damaged)
        with pytest.raises(ValueError, match="beschädigt"):
            restore_backup(controller.db, str(tmp_path / f"{name}.backup"), "geheim123", {})
    with pytest.raises(WrongPasswordError):
        restore_backup(controller.db, str(path), "falsch", {})

    (tmp_path / "x.backup").write_bytes(b"PK\x03\x04 kein Backup")
    with pytest.raises(ValueError, match="kein gültiges"):
        restore_backup(controller.db, str(tmp_path / "x.backup"), "geheim123", {})


def _create_version_1(snapshot: bytes, path, password: str):
    """A backup as Schalk up to 1.2.3 wrote it (no password check in the header)."""
    header = backup.MAGIC_V1 + struct.pack(">I", 1000) + os.urandom(backup.SALT_SIZE) + os.urandom(backup.PREFIX_SIZE)
    aead = backup._derive_key(password, header[len(backup.MAGIC_V1) + 4:len(backup.MAGIC_V1) + 4 + backup.SALT_SIZE], 1000)
    with open(path, "wb") as f:
        f.write(header)
        writer = backup._EncryptingWriter(f, aead, header, header[-backup.PREFIX_SIZE:])
        with zipfile.ZipFile(writer, "w") as zipf:
            zipf.writestr(backup.DB_NAME, snapshot)
        writer.finish()


def test_backups_of_older_versions_are_still_restored(controller, tmp_path):
    controller.add_customer(company_name="Aus Version 1")
    path = tmp_path / "alt.backup"
    _create_version_1(controller.db.snapshot(), path, "geheim123")
    with pytest.raises(WrongPasswordError):
        restore_backup(controller.db, str(path), "falsch", {})
    restore_backup(controller.db, str(path), "geheim123", {})
    assert controller.db._restored


def test_paths_outside_the_folder_are_ignored(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zipf:
        zipf.writestr("assets/../../evil.txt", "x")
        zipf.writestr("assets/ok.txt", "ok")
    target = tmp_path / "t" / "assets"
    with zipfile.ZipFile(archive) as zipf:
        backup._extract_missing(zipf, {"assets": str(target)})
    assert (target / "ok.txt").read_text() == "ok" and not (tmp_path / "evil.txt").exists()


def test_password_dialog_validation(window, qapp):
    from src.views.backup_password_dialog import BackupPasswordDialog
    dialog = BackupPasswordDialog("create", parent=window)
    dialog.passwordEdit.setText("kurz")
    assert not dialog.validate() and dialog.messageLabel.isVisibleTo(dialog)
    dialog.passwordEdit.setText("langesPasswort")
    dialog.repeatEdit.setText("anderes")
    assert not dialog.validate()
    dialog.repeatEdit.setText("langesPasswort")
    assert dialog.validate() and dialog.password() == "langesPasswort"
