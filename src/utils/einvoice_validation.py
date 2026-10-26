"""
Validates e-invoices with the official Schematron rules using Saxon-HE. The XSD check alone does
not catch calculation or VAT category errors; the Schematron does.
- ZUGFeRD/Factur-X: Factur-X EN 16931 rules shipped with the factur-x package (EN 16931 + profile rules)
- XRechnung: the combination of the official KoSIT validator, the CEN EN 16931 rules (1.3.16) plus the
  German XRechnung rules (3.0.2, BR-DE-*), both in src/resources (Apache License 2.0)
"""
import os
import threading
from functools import lru_cache
from typing import List
import facturx
from lxml import etree
from saxonche import PySaxonProcessor

_FACTURX_XSLT = os.path.join(os.path.dirname(facturx.__file__), "xsd_and_schematron", "facturx-en16931", "FACTUR-X_EN16931.xslt")
_RESOURCES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")
_CEN_XSLT = os.path.join(_RESOURCES, "en16931", "EN16931-CII-validation.xslt")
_XRECHNUNG_XSLT = os.path.join(_RESOURCES, "xrechnung", "XRechnung-CII-validation.xslt")
_SVRL = "{http://purl.oclc.org/dsdl/svrl}"
_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def _processor():
    return PySaxonProcessor(license=False)


@lru_cache(maxsize=None)
def _executable(stylesheet: str):
    return _processor().new_xslt30_processor().compile_stylesheet(stylesheet_file=stylesheet)


def _run_schematron(stylesheet: str, xml: bytes) -> List[str]:
    """Returns the violated rules (fatal assertions) as readable messages; empty list = valid."""
    with _LOCK:
        node = _processor().parse_xml(xml_text=xml.decode("utf-8"))
        report = _executable(stylesheet).transform_to_string(xdm_node=node)
    root = etree.fromstring(report.encode("utf-8"))
    problems = []
    for failed in root.iter(f"{_SVRL}failed-assert"):
        if failed.get("flag", "fatal") != "fatal":
            continue
        text = " ".join((failed.findtext(f"{_SVRL}text") or "").split())
        problems.append(text or failed.get("id", "Unbekannte Regel"))
    return problems


def validate_en16931(xml: bytes) -> List[str]:
    """ZUGFeRD/Factur-X invoice (profile EN 16931)."""
    return _run_schematron(_FACTURX_XSLT, xml)


def validate_xrechnung(xml: bytes) -> List[str]:
    """XRechnung (CII) with the rule sets of the official KoSIT validator."""
    return _run_schematron(_CEN_XSLT, xml) + _run_schematron(_XRECHNUNG_XSLT, xml)
