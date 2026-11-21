import os
import stat
import zipfile
import pytest
from src.utils import backup
from src.utils.backup import create_backup, restore_backup


def _folders(root):
    return {"app_data": str(root / "app_data"), "assets": str(root / "assets")}


def test_single_backup_file_with_documents(controller, tmp_path):
    source = tmp_path / "source"
    (source / "app_data" / "archive").mkdir(parents=True)
    (source / "assets").mkdir()
    big = os.urandom(10_000)
    (source / "app_data" / "archive" / "R-1.pdf").write_bytes(big)
    (source / "assets" / "logo.png").write_bytes(b"logo")
    controller.add_customer(company_name="Im Backup")

    path = tmp_path / "Schalk.backup"
    create_backup(controller.db.snapshot(), str(path), _folders(source))
    assert zipfile.is_zipfile(path) and not os.path.exists(f"{path}.tmp")

    target = tmp_path / "target"
    (target / "assets").mkdir(parents=True)
    (target / "assets" / "logo.png").write_bytes(b"vorhanden")
    restore_backup(controller.db, str(path), _folders(target))
    restored = target / "app_data" / "archive" / "R-1.pdf"
    assert restored.read_bytes() == big
    # Restored documents are archived documents again: read-only
    assert not os.stat(restored).st_mode & stat.S_IWRITE
    # Existing (read-only archived) files are never overwritten
    assert (target / "assets" / "logo.png").read_bytes() == b"vorhanden"


def test_damaged_old_or_foreign_files_are_rejected(controller, tmp_path):
    source = tmp_path / "source"
    (source / "app_data").mkdir(parents=True)
    (source / "app_data" / "R-1.pdf").write_bytes(os.urandom(50_000))
    path = tmp_path / "b.backup"
    create_backup(controller.db.snapshot(), str(path), _folders(source))
    data = path.read_bytes()

    # Cut off, or a byte changed inside the stored data: nothing is restored
    middle = len(data) // 2
    for name, damaged in (("truncated", data[:middle]), ("flipped", data[:middle] + bytes([data[middle] ^ 1]) + data[middle + 1:])):
        (tmp_path / f"{name}.backup").write_bytes(damaged)
        with pytest.raises(ValueError, match="beschädigt"):
            restore_backup(controller.db, str(tmp_path / f"{name}.backup"), {})
    assert not controller.db._restored

    (tmp_path / "alt.backup").write_bytes(b"SCHALKB\x02" + os.urandom(100))
    with pytest.raises(ValueError, match="älteren Schalk-Version"):
        restore_backup(controller.db, str(tmp_path / "alt.backup"), {})
    other = tmp_path / "fremd.backup"
    with zipfile.ZipFile(other, "w") as zipf:
        zipf.writestr("schalk.db", b"x")
    with pytest.raises(ValueError, match="kein Schalk-Backup"):
        restore_backup(controller.db, str(other), {})


def test_paths_outside_the_folder_are_ignored(tmp_path):
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zipf:
        zipf.writestr("assets/../../evil.txt", "x")
        zipf.writestr("assets/ok.txt", "ok")
    target = tmp_path / "t" / "assets"
    with zipfile.ZipFile(archive) as zipf:
        backup._extract_missing(zipf, {"assets": str(target)})
    assert (target / "ok.txt").read_text() == "ok" and not (tmp_path / "evil.txt").exists()
