import json
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def test_rule_files_and_versions_are_consistent():
    with open(os.path.join(ROOT, "src", "resources", "rules.json"), encoding="utf-8") as f:
        rules = json.load(f)
    for path in (("en16931", "EN16931-CII-validation.xslt"), ("xrechnung", "XRechnung-CII-validation.xslt")):
        assert os.path.isfile(os.path.join(ROOT, "src", "resources", *path))
    # The check workflow reads the Mustang version and its SHA-1 from rules.json
    assert re.fullmatch(r"[0-9a-f]{40}", rules["mustang_sha1"])
    with open(os.path.join(ROOT, ".github", "workflows", "einvoice-check.yml"), encoding="utf-8") as f:
        assert "MUSTANG_VERSION" not in f.read()
