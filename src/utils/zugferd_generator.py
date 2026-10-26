"""
Generates the structured invoice data (UN/CEFACT CII, EN 16931) for
- ZUGFeRD / Factur-X (profile EN 16931, embedded into the PDF/A-3)
- XRechnung 3.0 (CII syntax, pure XML; required by public authorities and accepted for B2B)
"""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List
from drafthorse.models.document import Document
from drafthorse.models.accounting import ApplicableTradeTax, CategoryTradeTax, TradeAllowanceCharge
from drafthorse.models.party import TaxRegistration
from drafthorse.models.payment import PaymentMeans, PaymentTerms
from drafthorse.models.tradelines import LineItem
from src.utils.calculations import tax_breakdown, round_money
from src.utils.tax import vat_category

GUIDELINE_EN16931 = "urn:cen.eu:en16931:2017"
GUIDELINE_XRECHNUNG = "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0"
BUSINESS_PROCESS = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"

# UN/ECE Rec. 20 unit codes
UNIT_CODES = {
    "stück": "C62", "stk": "C62", "stk.": "C62",
    "stunde": "HUR", "stunden": "HUR", "std": "HUR", "std.": "HUR", "h": "HUR",
    "tag": "DAY", "tage": "DAY",
    "kg": "KGM", "g": "GRM", "t": "TNE",
    "m": "MTR", "m²": "MTK", "m2": "MTK", "m³": "MTQ", "m3": "MTQ", "km": "KMT",
    "l": "LTR", "liter": "LTR",
    "pauschal": "LS", "psch": "LS", "psch.": "LS",
    "monat": "MON", "monate": "MON",
}

def country_code(code) -> str:
    return (code or "DE").strip().upper()


def _dec(value) -> Decimal:
    return Decimal(str(round_money(value)))


def _date(value):
    return value.date() if isinstance(value, datetime) else value


def xrechnung_problems(db_controller, invoice) -> List[str]:
    """Additional German XRechnung rules (BR-DE-*) on top of EN 16931."""
    seller = db_controller.seller_of(invoice)
    buyer = db_controller.buyer_of(invoice)
    problems = []
    if not (seller.get("first_name") or seller.get("last_name")):
        problems.append("Ansprechpartner (Vor-/Nachname) in den Firmendaten fehlt (BR-DE-5).")
    if not seller.get("phone"):
        problems.append("Telefonnummer in den Firmendaten fehlt (BR-DE-6).")
    if not seller.get("email"):
        problems.append("E-Mail-Adresse in den Firmendaten fehlt (BR-DE-7).")
    if not buyer.get("email"):
        problems.append("E-Mail-Adresse des Kunden fehlt (elektronische Adresse BT-49).")
    if not seller.get("iban") and not invoice.cancels_invoice_id:
        problems.append("IBAN in den Bankdaten fehlt (Zahlungsanweisungen, BR-DE-1).")
    return problems


def build_cii_xml(invoice, db_controller, profile: str = "en16931") -> bytes:
    """Returns the CII XML (validated against the XSD). profile: 'en16931' (ZUGFeRD) or 'xrechnung'."""
    if not invoice.items:
        raise ValueError("Eine E-Rechnung benötigt mindestens eine Position.")
    seller = db_controller.seller_of(invoice)
    buyer = db_controller.buyer_of(invoice)

    # A Stornorechnung is transmitted as credit note (381) with positive amounts
    is_storno = bool(invoice.cancels_invoice_id)
    sign = -1 if is_storno else 1
    reason = invoice.tax_exemption_reason or ""

    doc = Document()
    doc.context.business_parameter.id = BUSINESS_PROCESS
    doc.context.guideline_parameter.id = GUIDELINE_XRECHNUNG if profile == "xrechnung" else GUIDELINE_EN16931

    doc.header.id = invoice.invoice_number
    doc.header.type_code = "381" if is_storno else "380"
    doc.header.issue_date_time = _date(invoice.invoice_date)

    # Käuferreferenz (BT-10); mandatory for XRechnung, the Leitweg-ID for public authorities
    doc.trade.agreement.buyer_reference = buyer.get("buyer_reference") or (str(invoice.customer_id) if profile == "xrechnung" else None)

    # --- Seller ---
    party = doc.trade.agreement.seller
    party.name = seller.get("company_name") or f"{seller.get('first_name', '')} {seller.get('last_name', '')}".strip()
    party.address.line_one = seller.get("address")
    party.address.postcode = seller.get("postal_code")
    party.address.city_name = seller.get("city")
    party.address.country_id = "DE"
    contact_name = f"{seller.get('first_name', '')} {seller.get('last_name', '')}".strip()
    if contact_name:
        party.contact.person_name = contact_name
    if seller.get("phone"):
        party.contact.telephone.number = seller["phone"]
    if seller.get("email"):
        party.contact.email.address = seller["email"]
        party.electronic_address.uri_ID = ("EM", seller["email"])
    if seller.get("vat_id"):
        reg = TaxRegistration()
        reg.id = ("VA", seller["vat_id"])
        party.tax_registrations.add(reg)
    if seller.get("tax_id"):
        reg = TaxRegistration()
        reg.id = ("FC", seller["tax_id"])
        party.tax_registrations.add(reg)

    # --- Buyer ---
    party = doc.trade.agreement.buyer
    party.name = buyer.get("name")
    party.address.line_one = buyer.get("address")
    party.address.postcode = buyer.get("postal_code")
    party.address.city_name = buyer.get("city")
    party.address.country_id = country_code(buyer.get("country"))
    if buyer.get("email"):
        party.electronic_address.uri_ID = ("EM", buyer["email"])
    if buyer.get("vat_id"):
        reg = TaxRegistration()
        reg.id = ("VA", buyer["vat_id"])
        party.tax_registrations.add(reg)

    # --- Delivery date (BT-72) ---
    doc.trade.delivery.event.occurrence = _date(invoice.delivery_date)

    # --- Settlement ---
    settlement = doc.trade.settlement
    settlement.currency_code = "EUR"
    if is_storno:
        original = db_controller.get_invoice_header(invoice.cancels_invoice_id)
        if original:
            settlement.invoice_referenced_document.issuer_assigned_id = original.invoice_number
            settlement.invoice_referenced_document.issue_date_time = _date(original.invoice_date)

    iban = (seller.get("iban") or "").replace(" ", "")
    if iban and not is_storno:
        means = PaymentMeans()
        means.type_code = "58" # SEPA credit transfer
        means.payee_account.iban = iban
        if seller.get("account_holder"):
            means.payee_account.account_name = seller["account_holder"]
        bic = (seller.get("bic") or "").replace(" ", "")
        if bic:
            means.payee_institution.bic = bic
        settlement.payment_means.add(means)

    if not is_storno:
        payment_days = db_controller.payment_terms_of(invoice)
        terms = PaymentTerms()
        terms.description = f"Zahlbar innerhalb von {payment_days} Tagen ohne Abzug."
        terms.due = _date(invoice.invoice_date + timedelta(days=payment_days))
        settlement.terms.add(terms)

    credit = abs(invoice.credit_amount or 0.0)
    items = invoice.items
    positive_items = [{"total_price": abs(i.total_price), "tax_percent": i.tax_percent} for i in items]
    breakdown = tax_breakdown(positive_items, credit)

    # One tax group per rate (BG-23)
    for rate, (basis, tax_amount) in sorted(breakdown.items()):
        tax = ApplicableTradeTax()
        tax.calculated_amount = _dec(tax_amount)
        tax.basis_amount = _dec(basis)
        category = vat_category(rate, reason)
        tax.type_code = "VAT"
        tax.category_code = category
        tax.rate_applicable_percent = Decimal(str(rate))
        if category != "S": # BR-S-10: no exemption reason for the standard rate
            tax.exemption_reason = reason or "Steuerbefreit"
        settlement.trade_tax.add(tax)

    # The credit (Gutschrift) is a document level allowance, split over the tax rates
    if credit:
        nets = tax_breakdown(positive_items)
        for rate in sorted(breakdown):
            share = round_money(nets[rate][0] - breakdown[rate][0])
            if not share:
                continue
            allowance = TradeAllowanceCharge()
            allowance.indicator = False
            allowance.actual_amount = _dec(share)
            allowance.reason = invoice.credit_desc or "Gutschrift"
            category = CategoryTradeTax()
            category.type_code = "VAT"
            category.category_code = vat_category(rate, reason)
            category.rate_applicable_percent = Decimal(str(rate))
            allowance.trade_tax.add(category)
            settlement.allowance_charge.add(allowance)

    summation = settlement.monetary_summation
    summation.line_total = _dec(sign * invoice.net_amount)
    summation.charge_total = Decimal("0.00")
    summation.allowance_total = _dec(credit)
    summation.tax_basis_total = (_dec(sign * invoice.net_amount - credit), "EUR")
    summation.tax_total = (_dec(sign * invoice.tax_amount), "EUR")
    summation.grand_total = (_dec(sign * invoice.gross_amount), "EUR")
    summation.due_amount = _dec(sign * invoice.gross_amount)

    # --- Items ---
    for i, item in enumerate(items, 1):
        line = LineItem()
        line.document.line_id = str(i)
        line.product.name = item.title
        if item.description:
            line.product.description = item.description

        unit_price = abs(item.unit_price)
        net_price = unit_price * (100 - (item.discount_percent or 0.0)) / 100
        line.agreement.gross.amount = Decimal(str(round(unit_price, 4)))
        line.agreement.net.amount = Decimal(str(round(net_price, 4)))

        line.delivery.billed_quantity = (Decimal(str(item.quantity)), UNIT_CODES.get((item.unit or "").strip().lower(), "C62"))

        line.settlement.trade_tax.type_code = "VAT"
        line.settlement.trade_tax.category_code = vat_category(item.tax_percent, reason)
        line.settlement.trade_tax.rate_applicable_percent = Decimal(str(item.tax_percent))
        line.settlement.monetary_summation.total_amount = _dec(abs(item.total_price))

        doc.trade.items.add(line)

    # Validates against the Factur-X EN 16931 XSD (same CII D16B schema as XRechnung CII)
    return doc.serialize(schema="FACTUR-X_EN16931")

