"""
Prepares a new version: sets APP_VERSION in src/version.py and adds its section to CHANGELOG.md.

    python tools/bump_version.py 1.1.1 "Sicherheitsupdate: cryptography 50.0.1"
    python tools/bump_version.py 1.2 "Neue Funktion A" "Fehler B behoben"
    python tools/bump_version.py --auto "Prüfregeln aktualisiert"   # automatic release: 1.4.5 -> 1.4.5.1 -> 1.4.5.2

Each text becomes one changelog entry. Afterwards: open a PR, merge it when the checks are green and
start the release workflow (Actions -> Release -> Run workflow).
"""
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
VERSION_RE = re.compile(r'APP_VERSION = "([^"]+)"')


def _key(version: str) -> tuple:
    if not re.fullmatch(r"\d+(\.\d+){1,3}", version):
        raise ValueError(f"Ungültige Version: {version} (erwartet z. B. 1.2, 1.1.1 oder 1.1.1.1)")
    return tuple(int(part) for part in version.split("."))


def next_automatic_version(current: str) -> str:
    """Automatic releases count the fourth number: 1.4.5 -> 1.4.5.1, 1.4.5.1 -> 1.4.5.2."""
    parts = (_key(current) + (0, 0, 0))[:3] if len(_key(current)) < 4 else _key(current)[:3]
    build = _key(current)[3] + 1 if len(_key(current)) == 4 else 1
    return ".".join(str(n) for n in parts + (build,))


def current_version(root: str) -> str:
    with open(os.path.join(root, "src", "version.py"), encoding="utf-8") as f:
        return VERSION_RE.search(f.read()).group(1)


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
    args = sys.argv[1:]
    if len(args) < 2:
        sys.exit(__doc__)
    try:
        target = next_automatic_version(current_version(ROOT)) if args[0] == "--auto" else args[0]
        previous = bump(ROOT, target, args[1:])
    except ValueError as e:
        sys.exit(str(e))
    print(f"Version {previous} -> {target}; src/version.py und CHANGELOG.md aktualisiert.")
