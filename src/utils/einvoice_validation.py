"""
Validates e-invoices against the official EN 16931 business rules (Schematron, shipped with
the factur-x package) using Saxon-HE. The XSD check alone does not catch calculation or
VAT category errors; the Schematron does.
"""
import os
import threading
from functools import lru_cache
from typing import List
import facturx
from lxml import etree
from saxonche import PySaxonProcessor

_SCHEMATRON_XSLT = os.path.join(os.path.dirname(facturx.__file__), "xsd_and_schematron", "facturx-en16931", "FACTUR-X_EN16931.xslt")
_SVRL = "{http://purl.oclc.org/dsdl/svrl}"
_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def _executable():
    processor = PySaxonProcessor(license=False)
    executable = processor.new_xslt30_processor().compile_stylesheet(stylesheet_file=_SCHEMATRON_XSLT)
    return processor, executable


def validate_en16931(xml: bytes) -> List[str]:
    """Returns the violated rules (fatal assertions) as readable messages; empty list = valid."""
    with _LOCK:
        processor, executable = _executable()
        node = processor.parse_xml(xml_text=xml.decode("utf-8"))
        report = executable.transform_to_string(xdm_node=node)
    root = etree.fromstring(report.encode("utf-8"))
    problems = []
    for failed in root.iter(f"{_SVRL}failed-assert"):
        if failed.get("flag", "fatal") != "fatal":
            continue
        text = " ".join((failed.findtext(f"{_SVRL}text") or "").split())
        problems.append(text or failed.get("id", "Unbekannte Regel"))
    return problems
