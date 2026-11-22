import os
import re
import facturx
import pytest
from src.utils.einvoice_messages import german_message

STYLESHEETS = [
    os.path.join(os.path.dirname(facturx.__file__), "xsd_and_schematron", "facturx-en16931", "FACTUR-X_EN16931.xslt"),
    os.path.join("src", "resources", "en16931", "EN16931-CII-validation.xslt"),
    os.path.join("src", "resources", "xrechnung", "XRechnung-CII-validation.xslt"),
]


def _fatal_rules():
    rules = {}
    for path in STYLESHEETS:
        content = open(path, encoding="utf-8").read()
        for block in re.findall(r"<svrl:failed-assert.*?</svrl:failed-assert>", content, re.S):
            rule_id = re.search(r'name="id">([^<]+)<', block)
            flag = re.search(r'name="flag">([^<]+)<', block)
            text = re.search(r"<svrl:text>(.*?)</svrl:text>", block, re.S)
            if rule_id and (flag.group(1) if flag else "fatal") == "fatal":
                rules.setdefault(rule_id.group(1), text.group(1) if text else "")
    return rules


RULES = _fatal_rules()
ENGLISH = re.compile(r"\b(shall|must|should|Invoice|Seller|Buyer|amount|element|occur|allowed|required)\b", re.I)


def test_all_rules_are_found():
    assert len(RULES) > 500


@pytest.mark.parametrize("rule_id", sorted(RULES))
def test_every_rule_is_shown_in_german(rule_id):
    message = german_message(rule_id, RULES[rule_id])
    assert not ENGLISH.search(message), message
    assert rule_id in message
    if rule_id.startswith("BR-"):
        # Business rules are translated, not only reported as a technical error
        assert "technisch fehlerhaft" not in message, rule_id


def test_missing_seller_identifier_is_explained():
    message = german_message("BR-CO-26", "")
    assert "Steuernummer oder USt-IdNr." in message
