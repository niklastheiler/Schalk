import os
import re
from datetime import datetime, timezone
import pytest
from facturx import get_facturx_xml_from_pdf
from pypdf import PdfReader
from src.controllers.db_controller import GoBDError
from src.utils.einvoice_parser import read_einvoice
from src.utils.einvoice_validation import validate_en16931
from src.utils.invoice_documents import build_invoice_pdf, export_xrechnung

DAY = datetime(2026, 10, 1, tzinfo=timezone.utc)
ITEMS = [
    {"title": "Beratung", "quantity": 2, "unit": "Stunde", "unit_price": 100.0, "tax_percent": 19.0},
    {"title": "Buch", "description": "Fachbuch", "quantity": 1, "unit": "Stück", "unit_price": 20.0, "discount_percent": 10, "tax_percent": 7.0},
]


def _customer(c, **extra):
    fields = dict(company_name="Kunde AG", address="Weg 2", postal_code="20095", city="Hamburg", email="buchhaltung@kunde.de")
    fields.update(extra)
    return c.add_customer(**fields)


def test_finalization_requires_mandatory_seller_data(controller):
    invoice_id = controller.create_invoice(_customer(controller), DAY, DAY, ITEMS)
    ok, message = controller.update_invoice_status(invoice_id, "Offen")
    assert not ok and "Steuernummer" in message
    assert controller.is_draft_number(controller.get_invoice(invoice_id).invoice_number)


def test_finalize_seals_numbers_and_archives(controller, seller):
    c = controller
    customer_id = _customer(c)
    invoice_id = c.create_invoice(customer_id, DAY, DAY, ITEMS, credit_amount=10, credit_desc="Bonus")
    ok, _ = c.update_invoice_status(invoice_id, "Offen")
    invoice = c.get_invoice(invoice_id)
    assert ok and invoice.invoice_number.startswith(f"RE{datetime.now().year}")
    # credit split over the tax rates: 19 %: 190.83 -> 36.26, 7 %: 17.17 -> 1.20
    assert (invoice.net_amount, invoice.tax_amount, invoice.gross_amount) == (218.0, 37.46, 245.46)
    assert os.path.isfile(invoice.pdf_path)
    with pytest.raises(GoBDError):
        c.update_invoice(invoice_id, customer_id, DAY, DAY, ITEMS)
    with pytest.raises(GoBDError):
        c.delete_invoice(invoice_id)
    # Later changes don't alter the issued invoice
    c.set_settings({"company_name": "Andere GmbH", "payment_terms_days": "30"})
    c.update_customer(customer_id, address="Neue Str. 9")
    invoice = c.get_invoice(invoice_id)
    assert c.seller_of(invoice)["company_name"] == seller["company_name"]
    assert c.buyer_of(invoice)["address"] == "Weg 2"
    assert c.payment_terms_of(invoice) == 14
    assert c.verify_integrity() == []


def test_einvoice_pdf_is_valid_pdfa3_with_en16931_xml(controller, seller):
    c = controller
    invoice_id = c.create_invoice(_customer(c), DAY, DAY, ITEMS, status="Offen")
    pdf = c.get_invoice(invoice_id).pdf_path
    _, xml = get_facturx_xml_from_pdf(open(pdf, "rb").read(), check_xsd=True)
    assert validate_en16931(xml) == []
    reader = PdfReader(pdf)
    root = reader.trailer["/Root"]
    assert "/OutputIntents" in root and "/AF" in root and reader.pdf_header == "%PDF-1.7"
    for font in reader.pages[0]["/Resources"]["/Font"].values():
        assert "/FontFile2" in font.get_object()["/FontDescriptor"].get_object()
    broken = re.sub(rb'(<ram:GrandTotalAmount[^>]*>)[^<]+', rb'\g<1>999.99', xml)
    assert broken != xml
    assert any("BR-CO-15" in p for p in validate_en16931(broken))


def test_xrechnung_export(controller, seller, tmp_path):
    c = controller
    invoice_id = c.create_invoice(_customer(c, buyer_reference="04011000-12345-34"), DAY, DAY, ITEMS, status="Offen")
    target = tmp_path / "x.xml"
    export_xrechnung(c, c.get_invoice(invoice_id), str(target))
    data = read_einvoice(str(target))
    assert data.format == "XRechnung (CII)" and data.buyer_reference == "04011000-12345-34"
    no_mail = c.create_invoice(c.add_customer(company_name="Ohne Mail", address="X 1", postal_code="1", city="Y"), DAY, DAY, ITEMS, status="Offen")
    with pytest.raises(GoBDError, match="E-Mail-Adresse des Kunden"):
        export_xrechnung(c, c.get_invoice(no_mail), str(target))


def test_reverse_charge_requires_vat_ids(controller, seller):
    c = controller
    customer_id = _customer(c, country="FR", city="Paris", postal_code="75001")
    reason = "Steuerschuldnerschaft des Leistungsempfängers gemäß § 13b UStG (Reverse Charge)"
    invoice_id = c.create_invoice(customer_id, DAY, DAY, [{"title": "Montage", "quantity": 1, "unit_price": 1000, "tax_percent": 0.0}], tax_exemption_reason=reason)
    ok, message = c.update_invoice_status(invoice_id, "Offen")
    assert not ok and "USt-IdNr. des Kunden" in message
    c.update_customer(customer_id, vat_id="FR40303265045")
    ok, _ = c.update_invoice_status(invoice_id, "Offen")
    assert ok
    xml = get_facturx_xml_from_pdf(open(c.get_invoice(invoice_id).pdf_path, "rb").read())[1]
    assert b"<ram:CategoryCode>AE</ram:CategoryCode>" in xml and validate_en16931(xml) == []


def test_zero_rate_requires_exemption_reason(controller):
    with pytest.raises(ValueError):
        controller.create_invoice(_customer(controller), DAY, DAY, [{"title": "X", "quantity": 1, "unit_price": 5, "tax_percent": 0.0}])


def test_storno_and_gapless_numbers(controller, seller):
    c = controller
    customer_id = _customer(c)
    first = c.create_invoice(customer_id, DAY, DAY, ITEMS, status="Offen")
    c.delete_invoice(c.create_invoice(customer_id, DAY, DAY, ITEMS))
    ok, _ = c.update_invoice_status(first, "Storniert")
    assert ok and c.get_invoice(first).status == "Storniert"
    storno = next(i for i in c.get_invoices() if i.cancels_invoice_id == first)
    assert storno.gross_amount == -c.get_invoice(first).gross_amount
    data = read_einvoice(build_invoice_pdf(c, storno))
    assert data.type_code == "381" and data.payable_amount > 0
    year = datetime.now().year
    numbers = sorted(i.invoice_number for i in c.get_invoices())
    assert [n[-3:] for n in numbers] == ["001", "002"] and all(n.startswith(f"RE{year}") for n in numbers)
    with pytest.raises(GoBDError):
        c.cancel_invoice(storno.id)


def test_tampering_is_detected(controller, seller):
    from src.models.database import Invoice
    c = controller
    invoice_id = c.create_invoice(_customer(c), DAY, DAY, ITEMS, status="Offen")
    with c.get_session() as session:
        session.query(Invoice).filter(Invoice.id == invoice_id).update({"gross_amount": 1.0})
        session.commit()
    assert any("verändert" in p for p in c.verify_integrity())


def test_quote_to_invoice(controller):
    c = controller
    quote_id = c.create_quote(_customer(c), DAY, ITEMS)
    invoice_id = c.create_invoice_from_quote(quote_id)
    assert len(c.get_invoice(invoice_id).items) == 2
    assert c.get_quote(quote_id).status == "Angenommen"
