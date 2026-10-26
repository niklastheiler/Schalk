import re
import pytest
from facturx import get_facturx_xml_from_pdf
from einvoice_cases import CASES
from src.utils.einvoice_validation import validate_en16931, validate_xrechnung
from src.utils.invoice_documents import build_invoice_pdf
from src.utils.zugferd_generator import build_cii_xml


@pytest.mark.parametrize("name", CASES)
def test_every_tax_case_passes_the_official_rules(controller, seller, name):
    c = controller
    invoice_id = CASES[name](c)
    invoice = c.get_invoice(invoice_id)
    assert c.is_finalized(invoice), invoice.status
    # ZUGFeRD: the XML exactly as embedded in the archived PDF
    _, zugferd = get_facturx_xml_from_pdf(open(build_invoice_pdf(c, invoice), "rb").read(), check_xsd=True)
    assert validate_en16931(zugferd) == []
    # XRechnung: CEN EN 16931 + KoSIT XRechnung rules, like the official validator
    assert validate_xrechnung(build_cii_xml(invoice, c, "xrechnung")) == []


def test_xrechnung_rules_detect_violations(controller, seller):
    c = controller
    xml = build_cii_xml(c.get_invoice(CASES["Behoerde_Leitweg-ID"](c)), c, "xrechnung")
    broken = xml.replace(b"<ram:BuyerReference>04011000-12345-34</ram:BuyerReference>", b"")
    assert broken != xml
    assert any("BR-DE-15" in p for p in validate_xrechnung(broken)) # Leitweg-ID/buyer reference missing


def test_units_are_mapped_to_un_ece_codes(controller, seller):
    c = controller
    xml = build_cii_xml(c.get_invoice(CASES["Einheiten_und_Rundung"](c)), c, "xrechnung").decode()
    codes = re.findall(r'unitCode="([^"]+)"', xml)
    assert codes == ["KGM", "MTR", "LTR", "KMT", "MON", "DAY", "C62"]
