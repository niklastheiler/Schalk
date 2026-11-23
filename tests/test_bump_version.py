import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
from bump_version import bump, next_automatic_version  # noqa: E402


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "version.py").write_text('APP_NAME = "Schalk"\nAPP_VERSION = "1.1"\n', encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\n## 1.1\n\n- Alt\n", encoding="utf-8")
    return tmp_path


def test_bump_sets_version_and_adds_changelog_section(repo):
    assert bump(str(repo), "1.1.1", ["Sicherheitsupdate: cryptography 50.0.1"]) == "1.1"
    assert 'APP_VERSION = "1.1.1"' in (repo / "src" / "version.py").read_text(encoding="utf-8")
    assert (repo / "CHANGELOG.md").read_text(encoding="utf-8") == (
        "# Changelog\n\n## 1.1.1\n\n- Sicherheitsupdate: cryptography 50.0.1\n\n## 1.1\n\n- Alt\n")


@pytest.mark.parametrize("version", ["1.1", "1.0.9", "1.1.0.0.1", "v1.2", "1.2-beta"])
def test_bump_rejects_invalid_or_older_versions(repo, version):
    with pytest.raises(ValueError):
        bump(str(repo), version, ["X"])
    assert 'APP_VERSION = "1.1"' in (repo / "src" / "version.py").read_text(encoding="utf-8")


def test_bump_requires_notes(repo):
    with pytest.raises(ValueError):
        bump(str(repo), "1.2", [])


def test_automatic_releases_count_the_fourth_number(repo):
    assert next_automatic_version("1.4.5") == "1.4.5.1"
    assert next_automatic_version("1.4.5.1") == "1.4.5.2"
    assert next_automatic_version("1.4.5.9") == "1.4.5.10"
    assert next_automatic_version("1.5") == "1.5.0.1"
    bump(str(repo), "1.1.0.1", ["Prüfregeln aktualisiert"])
    assert 'APP_VERSION = "1.1.0.1"' in (repo / "src" / "version.py").read_text(encoding="utf-8")
    from src.utils.updater import is_newer
    assert is_newer("1.4.5.1", "1.4.5") and is_newer("1.4.5.2", "1.4.5.1") and is_newer("1.4.6", "1.4.5.9")
