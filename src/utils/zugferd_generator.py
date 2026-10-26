from datetime import datetime, timedelta
from decimal import Decimal
from drafthorse.models.document import Document
from drafthorse.models.accounting import ApplicableTradeTax, CategoryTradeTax, TradeAllowanceCharge
from drafthorse.models.party import TaxRegistration
from drafthorse.models.payment import PaymentMeans, PaymentTerms
from drafthorse.models.tradelines import LineItem
from src.utils.calculations import tax_breakdown, round_money
from src.utils.tax import vat_category

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

COUNTRY_CODES = {"deutschland": "DE", "österreich": "AT", "schweiz": "CH", "frankreich": "FR", "niederlande": "NL", "belgien": "BE", "luxemburg": "LU", "italien": "IT", "spanien": "ES", "polen": "PL", "dänemark": "DK"}


def _dec(value) -> Decimal:
    return Decimal(str(round_money(value)))


def _country(name) -> str:
    if not name:
        return "DE"
    name = name.strip()
    if len(name) == 2 and name.isalpha():
        return name.upper()
    return COUNTRY_CODES.get(name.lower(), "DE")


def _date(value):
    return value.date() if isinstance(value, datetime) else value


def generate_zugferd_xml(invoice, db_controller, output_path) -> bool:
    if not invoice.items:
        return False # Signal to caller that ZUGFeRD was skipped

    # A Stornorechnung is transmitted as credit note (381) with positive amounts
    is_storno = bool(invoice.cancels_invoice_id)
    sign = -1 if is_storno else 1

    doc = Document()
    doc.context.guideline_parameter.id = "urn:cen.eu:en16931:2017"

    doc.header.id = invoice.invoice_number
    doc.header.type_code = "381" if is_storno else "380"
    doc.header.issue_date_time = _date(invoice.invoice_date)

    # --- Seller ---
    seller = doc.trade.agreement.seller
    seller.name = db_controller.get_setting("company_name", "Meine Firma GmbH")
    seller.address.line_one = db_controller.get_setting("address", "Musterstraße 1")
    seller.address.postcode = db_controller.get_setting("postal_code", "12345")
    seller.address.city_name = db_controller.get_setting("city", "Musterstadt")
    seller.address.country_id = "DE"
    email = db_controller.get_setting("email", "")
    if email:
        seller.electronic_address.uri_ID = ("EM", email)

    vat_id = db_controller.get_setting("vat_id", "")
    tax_id = db_controller.get_setting("tax_id", "")
    if vat_id:
        reg = TaxRegistration()
        reg.id = ("VA", vat_id)
        seller.tax_registrations.add(reg)
    if tax_id:
        reg = TaxRegistration()
        reg.id = ("FC", tax_id)
        seller.tax_registrations.add(reg)

    # --- Buyer (snapshot taken at finalization) ---
    customer = invoice.customer
    buyer = doc.trade.agreement.buyer
    buyer.name = invoice.customer_name or (customer.company_name if customer.company_name else f"{customer.first_name} {customer.last_name}")
    buyer.address.line_one = (invoice.customer_address if invoice.customer_name else customer.address) or "Unbekannt"
    buyer.address.postcode = (invoice.customer_postal_code if invoice.customer_name else customer.postal_code) or "00000"
    buyer.address.city_name = (invoice.customer_city if invoice.customer_name else customer.city) or "Unbekannt"
    buyer.address.country_id = _country(invoice.customer_country if invoice.customer_name else customer.country)
    if invoice.customer_vat_id:
        reg = TaxRegistration()
        reg.id = ("VA", invoice.customer_vat_id)
        buyer.tax_registrations.add(reg)

    # --- Delivery date ---
    doc.trade.delivery.event.occurrence = _date(invoice.delivery_date)

    # --- Settlement ---
    settlement = doc.trade.settlement
    settlement.currency_code = "EUR"
    if is_storno:
        original = db_controller.get_invoice(invoice.cancels_invoice_id)
        if original:
            settlement.invoice_referenced_document.issuer_assigned_id = original.invoice_number
            settlement.invoice_referenced_document.issue_date_time = _date(original.invoice_date)

    iban = db_controller.get_setting("iban", "").replace(" ", "")
    if iban and not is_storno:
        means = PaymentMeans()
        means.type_code = "58" # SEPA credit transfer
        means.payee_account.iban = iban
        holder = db_controller.get_setting("account_holder", "")
        if holder:
            means.payee_account.account_name = holder
        bic = db_controller.get_setting("bic", "").replace(" ", "")
        if bic:
            means.payee_institution.bic = bic
        settlement.payment_means.add(means)

    if not is_storno:
        payment_days = db_controller.get_payment_terms()
        terms = PaymentTerms()
        terms.description = f"Zahlbar innerhalb von {payment_days} Tagen ohne Abzug."
        terms.due = _date(invoice.invoice_date + timedelta(days=payment_days))
        settlement.terms.add(terms)

    reason = invoice.tax_exemption_reason or ""
    credit = abs(invoice.credit_amount or 0.0)
    items = invoice.items
    breakdown = tax_breakdown([{"total_price": abs(i.total_price), "tax_percent": i.tax_percent} for i in items], credit)

    # One tax group per rate
    for rate, (basis, tax_amount) in sorted(breakdown.items()):
        tax = ApplicableTradeTax()
        tax.calculated_amount = _dec(tax_amount)
        tax.basis_amount = _dec(basis)
        tax.type_code = "VAT"
        tax.category_code = vat_category(rate, reason)
        tax.rate_applicable_percent = Decimal(str(rate))
        if tax.category_code != "S":
            tax.exemption_reason = reason or "Steuerbefreit"
        settlement.trade_tax.add(tax)

    # The credit (Gutschrift) is a document level allowance, split over the tax rates
    if credit:
        gross_nets = tax_breakdown([{"total_price": abs(i.total_price), "tax_percent": i.tax_percent} for i in items])
        for rate in sorted(breakdown):
            share = round_money(gross_nets[rate][0] - breakdown[rate][0])
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

    # Validates against the Factur-X EN 16931 XSD
    xml_bytes = doc.serialize(schema="FACTUR-X_EN16931")
    with open(output_path, "wb") as f:
        f.write(xml_bytes)

    return output_path
