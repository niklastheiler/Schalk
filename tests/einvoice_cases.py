"""
Typical invoices for every tax case. Used by the compliance tests and to create the sample files
that can be checked with external validators (KoSIT, Mustang, veraPDF).
"""
from datetime import datetime, timezone

DAY = datetime(2026, 10, 1, tzinfo=timezone.utc)
SELLER = {
    "company_name": "Test & Söhne GmbH", "first_name": "Max", "last_name": "Muster", "address": "Hauptstr. 1",
    "postal_code": "10115", "city": "Berlin", "tax_id": "12/345/67890", "vat_id": "DE100000008",
    "email": "info@test.de", "phone": "030 123456", "iban": "DE02120300000000202051", "bic": "BYLADEM1001",
    "bank_name": "Bank", "payment_terms_days": "14",
}
DOMESTIC = dict(company_name="Kunde AG", address="Weg 2", postal_code="20095", city="Hamburg", email="buchhaltung@kunde.de")


def _invoice(c, customer: dict, items: list, **kwargs) -> int:
    customer_id = c.add_customer(**customer)
    return c.create_invoice(customer_id, DAY, DAY, items, status="Offen", **kwargs)


def standard(c):
    """19 % and 7 %, line discount and a credit (document level allowance)."""
    return _invoice(c, DOMESTIC, [
        {"title": "Beratung", "quantity": 2, "unit": "Stunde", "unit_price": 100.0, "tax_percent": 19.0},
        {"title": "Fachbuch", "quantity": 3, "unit": "Stück", "unit_price": 19.99, "discount_percent": 10, "tax_percent": 7.0},
    ], credit_amount=10, credit_desc="Treuebonus")


def authority(c):
    """Public authority with Leitweg-ID (buyer reference)."""
    return _invoice(c, dict(DOMESTIC, company_name="Stadt Musterhausen", buyer_reference="04011000-12345-34"),
                    [{"title": "Wartung", "quantity": 1, "unit": "Pauschale", "unit_price": 450.0, "tax_percent": 19.0}])


def small_business(c):
    c.set_settings({"small_business": "1"})
    try:
        return _invoice(c, DOMESTIC, [{"title": "Gartenpflege", "quantity": 4, "unit": "Stunde", "unit_price": 35.0, "tax_percent": 0.0}],
                        tax_exemption_reason="Kein Ausweis von Umsatzsteuer, da Kleinunternehmer gemäß § 19 UStG")
    finally:
        c.set_settings({"small_business": "0"})


def tax_exempt(c):
    return _invoice(c, DOMESTIC, [{"title": "Heilbehandlung", "quantity": 1, "unit_price": 120.0, "tax_percent": 0.0}],
                    tax_exemption_reason="Steuerfreie Leistung gemäß § 4 UStG")


def reverse_charge(c):
    return _invoice(c, dict(DOMESTIC, company_name="Client SARL", city="Paris", postal_code="75001", country="FR", vat_id="FR40303265045"),
                    [{"title": "Montage", "quantity": 1, "unit_price": 1000.0, "tax_percent": 0.0}],
                    tax_exemption_reason="Steuerschuldnerschaft des Leistungsempfängers gemäß § 13b UStG (Reverse Charge)")


def intra_community(c):
    return _invoice(c, dict(DOMESTIC, company_name="Klant BV", city="Amsterdam", postal_code="1011", country="NL", vat_id="NL004495445B01"),
                    [{"title": "Maschine", "quantity": 1, "unit": "Stück", "unit_price": 2500.0, "tax_percent": 0.0}],
                    tax_exemption_reason="Steuerfreie innergemeinschaftliche Lieferung gemäß § 4 Nr. 1b UStG")


def export(c):
    return _invoice(c, dict(DOMESTIC, company_name="Kunde AG Schweiz", city="Zürich", postal_code="8001", country="CH"),
                    [{"title": "Ersatzteil", "quantity": 5, "unit": "Stück", "unit_price": 80.0, "tax_percent": 0.0}],
                    tax_exemption_reason="Steuerfreie Ausfuhrlieferung gemäß § 4 Nr. 1a UStG")


def storno(c):
    """Cancellation invoice (credit note, type 381) of a standard invoice."""
    original = standard(c)
    c.update_invoice_status(original, "Storniert")
    return next(i.id for i in c.get_invoices() if i.cancels_invoice_id == original)


CASES = {
    "Standard_19_7_Rabatt_Gutschrift": standard,
    "Behoerde_Leitweg-ID": authority,
    "Kleinunternehmer_19_UStG": small_business,
    "Steuerfrei_4_UStG": tax_exempt,
    "Reverse_Charge_13b_UStG": reverse_charge,
    "Innergemeinschaftliche_Lieferung": intra_community,
    "Ausfuhrlieferung": export,
    "Stornorechnung": storno,
}
