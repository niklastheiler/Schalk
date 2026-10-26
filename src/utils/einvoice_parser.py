"""
Reads received e-invoices (E-Rechnungspflicht: every business must be able to receive and process them):
- XRechnung / EN 16931 in CII syntax (also embedded in ZUGFeRD / Factur-X PDFs)
- XRechnung / EN 16931 in UBL syntax (Invoice and CreditNote)
"""
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from html import escape
from typing import List, Optional
from lxml import etree

# XXE protection: never resolve entities or load external resources from received files
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)


@dataclass
class EInvoiceLine:
    name: str
    quantity: float
    unit: str
    net_price: float
    line_total: float
    tax_rate: Optional[float]


@dataclass
class EInvoiceData:
    format: str
    type_code: str = ""
    number: str = ""
    issue_date: Optional[date] = None
    due_date: Optional[date] = None
    currency: str = "EUR"
    seller_name: str = ""
    seller_vat_id: str = ""
    seller_address: str = ""
    buyer_name: str = ""
    buyer_reference: str = ""
    net_amount: float = 0.0
    tax_amount: float = 0.0
    gross_amount: float = 0.0
    payable_amount: float = 0.0
    iban: str = ""
    payment_terms: str = ""
    notes: List[str] = field(default_factory=list)
    lines: List[EInvoiceLine] = field(default_factory=list)

    @property
    def is_credit_note(self) -> bool:
        return self.type_code in ("381", "CreditNote")


def _first(node, path: str) -> str:
    result = node.xpath(path)
    if not result:
        return ""
    value = result[0]
    text = value.text if hasattr(value, "text") else str(value)
    return (text or "").strip()


def _float(text: str) -> float:
    try:
        return float(text)
    except (TypeError, ValueError):
        return 0.0


def _ln(*names) -> str:
    """Namespace independent XPath: _ln('a', 'b') -> /*[local-name()='a']/*[local-name()='b']"""
    return "".join(f"/*[local-name()='{n}']" for n in names)


def _parse_cii_date(text: str) -> Optional[date]:
    try:
        return datetime.strptime(text[:8], "%Y%m%d").date() if text else None
    except ValueError:
        return None


def _parse_iso_date(text: str) -> Optional[date]:
    try:
        return date.fromisoformat(text[:10]) if text else None
    except ValueError:
        return None


def _parse_cii(root, source_is_pdf: bool) -> EInvoiceData:
    guideline = _first(root, "." + _ln("ExchangedDocumentContext", "GuidelineSpecifiedDocumentContextParameter", "ID"))
    if "xrechnung" in guideline.lower():
        fmt = "XRechnung (CII)"
    elif source_is_pdf:
        fmt = "ZUGFeRD / Factur-X"
    else:
        fmt = "E-Rechnung (CII)"
    doc = "." + _ln("ExchangedDocument")
    trade = "." + _ln("SupplyChainTradeTransaction")
    agreement = trade + _ln("ApplicableHeaderTradeAgreement")
    settlement = trade + _ln("ApplicableHeaderTradeSettlement")
    summation = settlement + _ln("SpecifiedTradeSettlementHeaderMonetarySummation")
    seller = agreement + _ln("SellerTradeParty")
    address = seller + _ln("PostalTradeAddress")

    data = EInvoiceData(
        format=fmt,
        type_code=_first(root, doc + _ln("TypeCode")),
        number=_first(root, doc + _ln("ID")),
        issue_date=_parse_cii_date(_first(root, doc + _ln("IssueDateTime", "DateTimeString"))),
        due_date=_parse_cii_date(_first(root, settlement + _ln("SpecifiedTradePaymentTerms", "DueDateDateTime", "DateTimeString"))),
        currency=_first(root, settlement + _ln("InvoiceCurrencyCode")) or "EUR",
        seller_name=_first(root, seller + _ln("Name")),
        seller_vat_id=_first(root, seller + "/*[local-name()='SpecifiedTaxRegistration']/*[local-name()='ID'][@schemeID='VA']"),
        seller_address=" ".join(filter(None, [_first(root, address + _ln("LineOne")), _first(root, address + _ln("PostcodeCode")), _first(root, address + _ln("CityName"))])),
        buyer_name=_first(root, agreement + _ln("BuyerTradeParty", "Name")),
        buyer_reference=_first(root, agreement + _ln("BuyerReference")),
        net_amount=_float(_first(root, summation + _ln("TaxBasisTotalAmount"))),
        tax_amount=_float(_first(root, summation + _ln("TaxTotalAmount"))),
        gross_amount=_float(_first(root, summation + _ln("GrandTotalAmount"))),
        payable_amount=_float(_first(root, summation + _ln("DuePayableAmount"))),
        iban=_first(root, settlement + _ln("SpecifiedTradeSettlementPaymentMeans", "PayeePartyCreditorFinancialAccount", "IBANID")),
        payment_terms=_first(root, settlement + _ln("SpecifiedTradePaymentTerms", "Description")),
        notes=[n.text.strip() for n in root.xpath(doc + _ln("IncludedNote", "Content")) if n.text],
    )
    for line in root.xpath(trade + _ln("IncludedSupplyChainTradeLineItem")):
        quantity = line.xpath("." + _ln("SpecifiedLineTradeDelivery", "BilledQuantity"))
        rate = _first(line, "." + _ln("SpecifiedLineTradeSettlement", "ApplicableTradeTax", "RateApplicablePercent"))
        data.lines.append(EInvoiceLine(
            name=_first(line, "." + _ln("SpecifiedTradeProduct", "Name")),
            quantity=_float(quantity[0].text) if quantity else 0.0,
            unit=quantity[0].get("unitCode", "") if quantity else "",
            net_price=_float(_first(line, "." + _ln("SpecifiedLineTradeAgreement", "NetPriceProductTradePrice", "ChargeAmount"))),
            line_total=_float(_first(line, "." + _ln("SpecifiedLineTradeSettlement", "SpecifiedTradeSettlementLineMonetarySummation", "LineTotalAmount"))),
            tax_rate=_float(rate) if rate else None,
        ))
    return data


def _parse_ubl(root) -> EInvoiceData:
    customization = _first(root, "." + _ln("CustomizationID"))
    fmt = "XRechnung (UBL)" if "xrechnung" in customization.lower() else "E-Rechnung (UBL)"
    is_credit = etree.QName(root).localname == "CreditNote"
    supplier = "." + _ln("AccountingSupplierParty", "Party")
    totals = "." + _ln("LegalMonetaryTotal")
    address = supplier + _ln("PostalAddress")
    data = EInvoiceData(
        format=fmt,
        type_code=_first(root, "." + _ln("CreditNoteTypeCode" if is_credit else "InvoiceTypeCode")) or ("381" if is_credit else "380"),
        number=_first(root, "." + _ln("ID")),
        issue_date=_parse_iso_date(_first(root, "." + _ln("IssueDate"))),
        due_date=_parse_iso_date(_first(root, "." + _ln("DueDate")) or _first(root, "." + _ln("PaymentMeans", "PaymentDueDate"))),
        currency=_first(root, "." + _ln("DocumentCurrencyCode")) or "EUR",
        seller_name=_first(root, supplier + _ln("PartyLegalEntity", "RegistrationName")) or _first(root, supplier + _ln("PartyName", "Name")),
        seller_vat_id=_first(root, supplier + _ln("PartyTaxScheme", "CompanyID")),
        seller_address=" ".join(filter(None, [_first(root, address + _ln("StreetName")), _first(root, address + _ln("PostalZone")), _first(root, address + _ln("CityName"))])),
        buyer_name=_first(root, "." + _ln("AccountingCustomerParty", "Party", "PartyLegalEntity", "RegistrationName")) or _first(root, "." + _ln("AccountingCustomerParty", "Party", "PartyName", "Name")),
        buyer_reference=_first(root, "." + _ln("BuyerReference")),
        net_amount=_float(_first(root, totals + _ln("TaxExclusiveAmount"))),
        tax_amount=_float(_first(root, "." + _ln("TaxTotal", "TaxAmount"))),
        gross_amount=_float(_first(root, totals + _ln("TaxInclusiveAmount"))),
        payable_amount=_float(_first(root, totals + _ln("PayableAmount"))),
        iban=_first(root, "." + _ln("PaymentMeans", "PayeeFinancialAccount", "ID")),
        payment_terms=_first(root, "." + _ln("PaymentTerms", "Note")),
        notes=[n.text.strip() for n in root.xpath("." + _ln("Note")) if n.text],
    )
    line_tag = "CreditNoteLine" if is_credit else "InvoiceLine"
    quantity_tag = "CreditedQuantity" if is_credit else "InvoicedQuantity"
    for line in root.xpath("." + _ln(line_tag)):
        quantity = line.xpath("." + _ln(quantity_tag))
        rate = _first(line, "." + _ln("Item", "ClassifiedTaxCategory", "Percent"))
        data.lines.append(EInvoiceLine(
            name=_first(line, "." + _ln("Item", "Name")),
            quantity=_float(quantity[0].text) if quantity else 0.0,
            unit=quantity[0].get("unitCode", "") if quantity else "",
            net_price=_float(_first(line, "." + _ln("Price", "PriceAmount"))),
            line_total=_float(_first(line, "." + _ln("LineExtensionAmount"))),
            tax_rate=_float(rate) if rate else None,
        ))
    return data


def parse_einvoice_xml(xml: bytes, source_is_pdf: bool = False) -> Optional[EInvoiceData]:
    try:
        root = etree.fromstring(xml, _PARSER)
    except etree.XMLSyntaxError:
        return None
    name = etree.QName(root).localname
    if name == "CrossIndustryInvoice":
        return _parse_cii(root, source_is_pdf)
    if name in ("Invoice", "CreditNote"):
        return _parse_ubl(root)
    return None


def extract_xml(path: str) -> Optional[bytes]:
    """The structured invoice data of a file: the XML itself or the XML embedded in a ZUGFeRD PDF."""
    with open(path, "rb") as f:
        content = f.read()
    if path.lower().endswith(".xml"):
        return content
    if content.startswith(b"%PDF"):
        from facturx import get_facturx_xml_from_pdf
        try:
            _, xml = get_facturx_xml_from_pdf(content, check_xsd=False)
            return xml
        except Exception:
            return None
    return None


def read_einvoice(path: str) -> Optional[EInvoiceData]:
    xml = extract_xml(path)
    if not xml:
        return None
    return parse_einvoice_xml(xml, source_is_pdf=not path.lower().endswith(".xml"))


def _money(value: float, currency: str) -> str:
    text = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} {'€' if currency == 'EUR' else currency}"


def to_html(data: EInvoiceData) -> str:
    """Human readable view of an e-invoice (pure XML invoices cannot be opened otherwise)."""
    def d(value):
        return value.strftime("%d.%m.%Y") if value else "–"
    title = "Gutschrift / Stornorechnung" if data.is_credit_note else "Rechnung"
    rows = "".join(
        f"<tr><td>{i}</td><td>{escape(l.name)}</td><td align='right'>{l.quantity:g} {escape(l.unit)}</td>"
        f"<td align='right'>{_money(l.net_price, data.currency)}</td>"
        f"<td align='right'>{'' if l.tax_rate is None else f'{l.tax_rate:g} %'}</td>"
        f"<td align='right'>{_money(l.line_total, data.currency)}</td></tr>"
        for i, l in enumerate(data.lines, 1))
    notes = "".join(f"<p>{escape(n)}</p>" for n in data.notes)
    return f"""
    <h2>{title} {escape(data.number)}</h2>
    <p><i>{escape(data.format)}</i></p>
    <table cellpadding='3'>
      <tr><td><b>Rechnungssteller:</b></td><td>{escape(data.seller_name)}<br>{escape(data.seller_address)}</td></tr>
      <tr><td><b>USt-IdNr.:</b></td><td>{escape(data.seller_vat_id) or '–'}</td></tr>
      <tr><td><b>Empfänger:</b></td><td>{escape(data.buyer_name)}</td></tr>
      <tr><td><b>Käuferreferenz:</b></td><td>{escape(data.buyer_reference) or '–'}</td></tr>
      <tr><td><b>Rechnungsdatum:</b></td><td>{d(data.issue_date)}</td></tr>
      <tr><td><b>Fällig am:</b></td><td>{d(data.due_date)}</td></tr>
      <tr><td><b>IBAN:</b></td><td>{escape(data.iban) or '–'}</td></tr>
    </table>
    <h3>Positionen</h3>
    <table border='1' cellspacing='0' cellpadding='4' width='100%'>
      <tr><th>Pos.</th><th>Bezeichnung</th><th>Menge</th><th>Einzelpreis</th><th>MwSt.</th><th>Gesamt</th></tr>
      {rows}
    </table>
    <p align='right'>Netto: {_money(data.net_amount, data.currency)}<br>
    MwSt.: {_money(data.tax_amount, data.currency)}<br>
    <b>Brutto: {_money(data.gross_amount, data.currency)}</b><br>
    <b>Zahlbetrag: {_money(data.payable_amount, data.currency)}</b></p>
    <p>{escape(data.payment_terms)}</p>
    {notes}
    """


def is_supported_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in (".pdf", ".xml")
