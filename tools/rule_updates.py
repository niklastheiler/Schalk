"""
Checks Maven Central for newer versions of the e-invoice validation rules and the Mustang validator.

    python tools/rule_updates.py            report; exit code 10 if anything is outdated
    python tools/rule_updates.py --update   additionally replace the rule files in src/resources

The versions in use are recorded in src/resources/rules.json. The Mustang version used by the
check workflow is updated by hand in .github/workflows/einvoice-check.yml (version and SHA-1).
"""
import io
import json
import os
import re
import sys
import urllib.request
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RESOURCES = os.path.join(ROOT, "src", "resources")
RULES_FILE = os.path.join(RESOURCES, "rules.json")
OUTDATED = 10 # distinct from 1, which a crash (e.g. no network) returns
MAVEN = "https://repo1.maven.org/maven2"
PHIVE = {
    # rule set: (artifact, path pattern inside the jar, target file)
    "en16931": ("phive-rules-en16931", r"external/schematron/([^/]+)/cii/(?:xslt/)?EN16931-CII-validation\.xslt",
                os.path.join("en16931", "EN16931-CII-validation.xslt")),
    "xrechnung": ("phive-rules-xrechnung", r"external/schematron/([^/]+)/XRechnung-CII-validation\.xslt",
                  os.path.join("xrechnung", "XRechnung-CII-validation.xslt")),
}


def _get(url: str) -> bytes:
    # Maven Central rejects the default Python user agent (HTTP 429)
    request = urllib.request.Request(url, headers={"User-Agent": "Schalk-rule-update-check"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def latest_release(group: str, artifact: str) -> str:
    metadata = _get(f"{MAVEN}/{group.replace('.', '/')}/{artifact}/maven-metadata.xml").decode()
    return re.search(r"<release>([^<]+)</release>", metadata).group(1)


def _version_key(version: str) -> tuple:
    return tuple(int(part) if part.isdigit() else -1 for part in re.split(r"[.\-]", re.sub(r"[a-z]+$", "", version)))


def newest_rules(artifact: str, phive_version: str, pattern: str):
    """(rule version, xslt bytes) of the newest rule set inside a phive rules jar."""
    jar = zipfile.ZipFile(io.BytesIO(_get(
        f"{MAVEN}/com/helger/phive/rules/{artifact}/{phive_version}/{artifact}-{phive_version}.jar")))
    found = {m.group(1): name for name in jar.namelist() if (m := re.fullmatch(pattern, name))}
    version = max(found, key=_version_key)
    return version, jar.read(found[version])


def main(update: bool) -> int:
    with open(RULES_FILE, encoding="utf-8") as f:
        current = json.load(f)
    latest = dict(current)
    files = {}
    latest["phive_rules"] = latest_release("com.helger.phive.rules", "phive-rules-xrechnung")
    for name, (artifact, pattern, target) in PHIVE.items():
        latest[name], files[target] = newest_rules(artifact, latest["phive_rules"], pattern)
    latest["mustang"] = latest_release("org.mustangproject", "Mustang-CLI")

    outdated = [key for key in ("en16931", "xrechnung", "mustang") if latest[key] != current[key]]
    for key in ("en16931", "xrechnung", "mustang"):
        marker = "NEU" if key in outdated else "ok "
        print(f"{marker}  {key:10} eingebaut {current[key]:10} aktuell {latest[key]}")
    if not outdated:
        return 0
    if update:
        for target, data in files.items():
            with open(os.path.join(RESOURCES, target), "wb") as f:
                f.write(data)
        current.update({key: latest[key] for key in ("phive_rules", "en16931", "xrechnung")})
        with open(RULES_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)
            f.write("\n")
        print("Regelwerke aktualisiert. Danach die Tests laufen lassen"
              + ("; Mustang-Version und SHA-1 in .github/workflows/einvoice-check.yml von Hand anpassen." if "mustang" in outdated else "."))
    return OUTDATED


if __name__ == "__main__":
    sys.exit(main("--update" in sys.argv[1:]))
