"""
Prepares a new version: sets APP_VERSION in src/version.py and adds its section to CHANGELOG.md.

    python tools/bump_version.py 1.1.1 "Sicherheitsupdate: cryptography 50.0.1"
    python tools/bump_version.py 1.2 "Neue Funktion A" "Fehler B behoben"

Each text becomes one changelog entry. Afterwards: open a PR, merge it when the checks are green and
start the release workflow (Actions -> Release -> Run workflow).
"""
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
VERSION_RE = re.compile(r'APP_VERSION = "([^"]+)"')


def _key(version: str) -> tuple:
    if not re.fullmatch(r"\d+(\.\d+){1,2}", version):
        raise ValueError(f"Ungültige Version: {version} (erwartet z. B. 1.2 oder 1.1.1)")
    return tuple(int(part) for part in version.split("."))


def bump(root: str, version: str, notes: list) -> str:
    """Returns the previous version. Raises ValueError if the new one is not greater."""
    if not notes:
        raise ValueError("Mindestens ein Changelog-Eintrag ist nötig.")
    version_file = os.path.join(root, "src", "version.py")
    changelog_file = os.path.join(root, "CHANGELOG.md")
    with open(version_file, encoding="utf-8") as f:
        source = f.read()
    current = VERSION_RE.search(source).group(1)
    if _key(version) <= _key(current):
        raise ValueError(f"Die neue Version {version} muss größer sein als {current}.")

    with open(changelog_file, encoding="utf-8") as f:
        changelog = f.read()
    if re.search(rf"^## {re.escape(version)}$", changelog, re.M):
        raise ValueError(f"CHANGELOG.md enthält schon einen Abschnitt {version}.")
    section = f"## {version}\n\n" + "".join(f"- {note}\n" for note in notes) + "\n"
    head, separator, rest = changelog.partition("\n## ")
    changelog = f"{head.rstrip()}\n\n{section}" + (f"## {rest}" if separator else "")

    with open(version_file, "w", encoding="utf-8") as f:
        f.write(VERSION_RE.sub(f'APP_VERSION = "{version}"', source))
    with open(changelog_file, "w", encoding="utf-8") as f:
        f.write(changelog)
    return current


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    try:
        previous = bump(ROOT, sys.argv[1], sys.argv[2:])
    except ValueError as e:
        sys.exit(str(e))
    print(f"Version {previous} -> {sys.argv[1]}; src/version.py und CHANGELOG.md aktualisiert.")
