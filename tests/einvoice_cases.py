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


def special_characters(c):
    """Characters that must be escaped in XML, umlauts, € sign, line breaks and very long texts."""
    long_text = "Detaillierte Leistungsbeschreibung mit Umlauten (äöüß ÄÖÜ), Sonderzeichen <>&\"' und € – " * 8
    return _invoice(c, dict(DOMESTIC, company_name="Müller & Söhne <Bau> GmbH & Co. KG", address="Straße des 17. Juni 1–3",
                            email="rechnung@müller-bau.de".replace("ü", "ue")), [
        {"title": "Planung „Phase 1“ & <Entwurf>", "description": long_text.strip() + "\nZweite Zeile\nDritte Zeile",
         "quantity": 1, "unit": "Pauschale", "unit_price": 1250.0, "tax_percent": 19.0},
        {"title": "Ø 50 mm Rohr – 'Sonderanfertigung'", "quantity": 12, "unit": "Meter", "unit_price": 7.35, "tax_percent": 19.0},
    ])


def many_items(c):
    """40 positions with alternating rates and discounts plus a credit (sum rounding over many lines)."""
    items = [{"title": f"Artikel {i:02d}", "quantity": 1 + i % 4, "unit": "Stück", "unit_price": 3.33 + i * 1.07,
              "discount_percent": (0, 5, 12.5, 33)[i % 4], "tax_percent": (19.0, 7.0)[i % 2]} for i in range(40)]
    return _invoice(c, DOMESTIC, items, credit_amount=17.89, credit_desc="Mengenrabatt")


def units_and_rounding(c):
    """Uncommon units, fractional quantities and prices with more than two decimal places."""
    return _invoice(c, DOMESTIC, [
        {"title": "Kies", "quantity": 2.375, "unit": "Kilogramm", "unit_price": 0.4375, "tax_percent": 19.0},
        {"title": "Kabel", "quantity": 33.3, "unit": "Meter", "unit_price": 1.111, "discount_percent": 3, "tax_percent": 19.0},
        {"title": "Heizöl", "quantity": 1234.5, "unit": "Liter", "unit_price": 0.9876, "tax_percent": 19.0},
        {"title": "Anfahrt", "quantity": 87.6, "unit": "km", "unit_price": 0.3, "tax_percent": 19.0},
        {"title": "Miete Gerüst", "quantity": 2.5, "unit": "Monat", "unit_price": 333.33, "tax_percent": 19.0},
        {"title": "Leihgerät", "quantity": 3, "unit": "Tag", "unit_price": 0.01, "tax_percent": 19.0},
        {"title": "Lebensmittel", "quantity": 7, "unit": "Stück", "unit_price": 0.995, "tax_percent": 7.0},
    ])


CASES = {
    "Standard_19_7_Rabatt_Gutschrift": standard,
    "Behoerde_Leitweg-ID": authority,
    "Kleinunternehmer_19_UStG": small_business,
    "Steuerfrei_4_UStG": tax_exempt,
    "Reverse_Charge_13b_UStG": reverse_charge,
    "Innergemeinschaftliche_Lieferung": intra_community,
    "Ausfuhrlieferung": export,
    "Stornorechnung": storno,
    "Sonderzeichen_lange_Texte": special_characters,
    "Viele_Positionen_gemischt": many_items,
    "Einheiten_und_Rundung": units_and_rounding,
}
