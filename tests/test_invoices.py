import os
import re
from datetime import datetime, timedelta, timezone
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


def test_pdf_texts_are_escaped_and_keep_line_breaks():
    from src.utils.pdf_generator import _markup
    assert _markup("Rohr <Ø 50> & Co.\nZweite Zeile\r\nDritte") == "Rohr &lt;Ø 50&gt; &amp; Co.<br/>Zweite Zeile<br/>Dritte"


def test_export_requires_own_vat_id(controller, seller):
    # EN 16931 BR-G-02: an export invoice needs the seller's VAT ID, the tax number alone is not enough
    c = controller
    c.set_settings({"vat_id": ""})
    invoice_id = c.create_invoice(_customer(c, country="CH", city="Zürich", postal_code="8001"), DAY, DAY,
                                  [{"title": "Ersatzteil", "quantity": 1, "unit_price": 80.0, "tax_percent": 0.0}],
                                  tax_exemption_reason="Steuerfreie Ausfuhrlieferung gemäß § 4 Nr. 1a UStG")
    ok, message = c.update_invoice_status(invoice_id, "Offen")
    assert not ok and "Ausfuhrlieferung ist die eigene USt-IdNr. Pflicht" in message


@pytest.mark.parametrize("item, text", [
    ({"unit_price": -10.0}, "darf nicht negativ"),
    ({"discount_percent": 150}, "zwischen 0 und 100"),
    ({"quantity": float("nan")}, "ungültige Zahl"),
    ({"unit_price": float("inf")}, "ungültige Zahl"),
])
def test_invalid_items_are_refused(controller, item, text):
    line = dict({"title": "X", "quantity": 1, "unit_price": 5.0, "tax_percent": 19.0}, **item)
    with pytest.raises(ValueError, match=text):
        controller.create_invoice(_customer(controller), DAY, DAY, [line])


def test_negative_credit_is_refused(controller):
    with pytest.raises(ValueError, match="nicht negativ"):
        controller.create_invoice(_customer(controller), DAY, DAY, ITEMS, credit_amount=-5)


def test_reminders_only_for_unpaid_invoices(controller, seller):
    c = controller
    invoice_id = c.create_invoice(_customer(c), DAY, DAY, ITEMS, status="Offen")
    c.update_invoice_status(invoice_id, "Bezahlt")
    with pytest.raises(GoBDError, match="Mahnung ist nicht möglich"):
        c.record_reminder(invoice_id, 1)
    assert c.get_invoice(invoice_id).status == "Bezahlt"


def test_clock_set_back_does_not_break_the_hash_chain(controller, seller, monkeypatch):
    # Time synchronisation or the end of daylight saving time can turn the clock back between two finalizations
    from src.controllers import db_controller
    c = controller
    first = c.get_invoice(c.create_invoice(_customer(c), DAY, DAY, ITEMS, status="Offen"))

    class EarlierClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) - timedelta(hours=2)
    monkeypatch.setattr(db_controller, "datetime", EarlierClock)
    second = c.get_invoice(c.create_invoice(_customer(c), DAY, DAY, ITEMS, status="Offen"))
    assert second.finalized_at > first.finalized_at
    assert c.verify_integrity() == []


def _pdf_text(path) -> str:
    # Whitespace normalized: table cells wrap their text over several lines
    return " ".join(" ".join(page.extract_text() for page in PdfReader(path).pages).split())


def test_invoice_pdf_texts(controller, seller):
    c = controller
    customer_id = _customer(c, company_name="Łukasz Wiśniewski Dvořák", city="Łódź")
    invoice_id = c.create_invoice(customer_id, DAY, DAY, [
        {"title": "Kies", "quantity": 2.375, "unit": "Kilogramm", "unit_price": 0.4375, "tax_percent": 19.0},
        {"title": "Montage", "quantity": 1, "unit_price": 100.0, "discount_percent": 12.5, "tax_percent": 0.0},
    ], status="Offen", tax_exemption_reason="Steuerfreie Leistung gemäß § 4 UStG")
    text = _pdf_text(c.get_invoice(invoice_id).pdf_path)
    # Names with Polish and Czech letters are printed completely (the font has the glyphs)
    assert "Łukasz Wiśniewski Dvořák" in text and "Łódź" in text
    # Exact quantities and prices instead of values rounded to two decimals
    assert "2,375 Kilogramm" in text and "0,4375 €" in text and "12,5 % Rabatt" in text
    assert "innerhalb von 14 Tagen ohne Abzug" in text

    c.update_invoice_status(invoice_id, "Storniert")
    storno = next(i for i in c.get_invoices() if i.cancels_invoice_id == invoice_id)
    assert "-0,00" not in _pdf_text(build_invoice_pdf(c, storno))


def test_immediate_payment_terms(controller, seller):
    c = controller
    c.set_settings({"payment_terms_days": "0"})
    invoice = c.get_invoice(c.create_invoice(_customer(c), DAY, DAY, ITEMS, status="Offen"))
    assert "sofort ohne Abzug unter Angabe der Rechnungsnummer" in _pdf_text(invoice.pdf_path)
    xml = get_facturx_xml_from_pdf(open(invoice.pdf_path, "rb").read())[1]
    assert "Zahlbar sofort ohne Abzug.".encode() in xml and validate_en16931(xml) == []


def test_pdf_font_covers_european_names():
    from reportlab.pdfbase import pdfmetrics
    from src.utils.pdf_generator import FONT, FONT_BOLD, _register_fonts
    _register_fonts()
    letters = "äöüßÄÖÜ€łŁńśźżćęąčřšžůőűŞşğıİçñåøæ–„“”"
    for name in (FONT, FONT_BOLD):
        cmap = pdfmetrics.getFont(name).face.charToGlyph
        assert [ch for ch in letters if ord(ch) not in cmap] == []


def test_document_layout_with_own_logo(controller, seller, tmp_path):
    # Own logo with a transparent background, colour of the documents chosen in the settings
    from PIL import Image
    c = controller
    logo = tmp_path / "logo.png"
    Image.new("RGBA", (400, 120), (200, 30, 30, 128)).save(logo)
    c.set_settings({"logo_path": str(logo), "document_color": "Petrol"})
    invoice = c.get_invoice(c.create_invoice(_customer(c, country="AT", vat_id="ATU13585627"), DAY, DAY, ITEMS, status="Offen"))
    reader = PdfReader(invoice.pdf_path)
    page = reader.pages[0]
    assert any(x.get_object()["/Subtype"] == "/Image" for x in page["/Resources"]["/XObject"].values())
    # PDF/A: every font of the page is embedded (no standard font slipped in)
    for font in page["/Resources"]["/Font"].values():
        assert "/FontFile2" in font.get_object()["/FontDescriptor"].get_object()
    text = _pdf_text(invoice.pdf_path)
    for expected in ("Rechnungsnr.", invoice.invoice_number, "Leistungsdatum", "Zahlbar bis 15.10.2026", "Kundennr.",
                     "Ihre USt-IdNr. ATU13585627", "ÖSTERREICH", "Bankverbindung", "IBAN DE02 1203 0000 0000 2020 51",
                     "Steuernr. 12/345/67890", "Seite 1 von 1", "zzgl. 19 % USt. auf 200,00 €", "Gesamtbetrag 257,26 €"):
        assert expected in text, expected
    xml = get_facturx_xml_from_pdf(open(invoice.pdf_path, "rb").read())[1]
    assert validate_en16931(xml) == []


def test_long_invoices_continue_on_further_pages(controller, seller):
    c = controller
    items = [{"title": f"Position {i}", "description": "Beschreibung " * 30, "quantity": 1, "unit_price": 10.0,
              "tax_percent": 19.0} for i in range(40)]
    invoice = c.get_invoice(c.create_invoice(_customer(c), DAY, DAY, items, status="Offen"))
    reader = PdfReader(invoice.pdf_path)
    assert len(reader.pages) > 2
    last = " ".join(reader.pages[-1].extract_text().split())
    assert f"Seite {len(reader.pages)} von {len(reader.pages)}" in last and "Mit freundlichen Grüßen" in last


def test_service_period_and_retention_notice(controller, seller):
    from einvoice_cases import CASES
    from src.models.database import Invoice
    from src.utils.zugferd_generator import build_cii_xml
    from src.utils.einvoice_validation import validate_xrechnung
    c = controller
    invoice = c.get_invoice(CASES["Leistungszeitraum_Privatkunde"](c))
    text = _pdf_text(invoice.pdf_path)
    assert "Leistungszeitraum 01.10.–14.10.2026" in text and "Leistungsdatum" not in text
    assert "zwei Jahre lang aufzubewahren (§ 14b Abs. 1 Satz 5 UStG)" in text
    xml = get_facturx_xml_from_pdf(open(invoice.pdf_path, "rb").read())[1]
    assert b"BillingSpecifiedPeriod" in xml and b"20261014" in xml and b"14b Abs. 1" in xml
    assert validate_en16931(xml) == []
    assert validate_xrechnung(build_cii_xml(invoice, c, "xrechnung")) == []
    # Both are sealed in the hash chain
    assert c.verify_integrity() == []
    with c.get_session() as session:
        session.query(Invoice).filter(Invoice.id == invoice.id).update({"retention_notice": False})
        session.commit()
    assert any("verändert" in p for p in c.verify_integrity())


def test_service_period_must_not_end_before_it_starts(controller):
    with pytest.raises(ValueError, match="vor seinem Beginn"):
        controller.create_invoice(_customer(controller), DAY, DAY, ITEMS, delivery_end_date=DAY - timedelta(days=1))
    # The same day is a single date of delivery, not a period
    invoice_id = controller.create_invoice(_customer(controller), DAY, DAY, ITEMS, delivery_end_date=DAY)
    assert controller.get_invoice(invoice_id).delivery_end_date is None


def test_hash_of_invoices_without_the_new_fields_is_unchanged(controller, seller):
    # Invoices sealed before version 1.3 must still verify: their payload has no keys for the new fields
    c = controller
    invoice = c.get_invoice(c.create_invoice(_customer(c), DAY, DAY, ITEMS, status="Offen"))
    payload = c._invoice_hash_payload(invoice, invoice.items)
    assert "delivery_end_date" not in payload and "retention_notice" not in payload
