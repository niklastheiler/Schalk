import os
import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal
from drafthorse.models.document import Document
from drafthorse.models.party import TaxRegistration
from drafthorse.models.tradelines import LineItem

def generate_zugferd_xml(invoice, db_controller, output_path) -> bool:
    if not invoice.items:
        return False # Signal to caller that ZUGFeRD was skipped
        
    doc = Document()
    doc.context.guideline_parameter.id = "urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:extended"
    
    doc.header.id = invoice.invoice_number
    doc.header.type_code = "380" # Commercial Invoice
    # doc.header.name = "Rechnung" # Causes XML ordering error in validation
    
    # Make sure we use a naive datetime or properly formatted date
    doc.header.issue_date_time = invoice.invoice_date.date() if isinstance(invoice.invoice_date, datetime) else invoice.invoice_date
    
    # --- Seller ---
    doc.trade.agreement.seller.name = db_controller.get_setting("company_name", "Meine Firma GmbH")
    
    doc.trade.agreement.seller.address.line_one = db_controller.get_setting("address", "Musterstraße 1")
    doc.trade.agreement.seller.address.postcode = db_controller.get_setting("postal_code", "12345")
    doc.trade.agreement.seller.address.city_name = db_controller.get_setting("city", "Musterstadt")
    doc.trade.agreement.seller.address.country_id = "DE"
    
    seller_vat = TaxRegistration()
    seller_vat.id = ("VA", db_controller.get_setting("vat_id", "DE123456789"))
    doc.trade.agreement.seller.tax_registrations.add(seller_vat)
    
    # --- Buyer ---
    customer = invoice.customer
    doc.trade.agreement.buyer.name = customer.company_name if customer.company_name else f"{customer.first_name} {customer.last_name}"
    
    doc.trade.agreement.buyer.address.line_one = customer.address if customer.address else "Unbekannt"
    doc.trade.agreement.buyer.address.postcode = customer.postal_code if customer.postal_code else "00000"
    doc.trade.agreement.buyer.address.city_name = customer.city if customer.city else "Unbekannt"
    doc.trade.agreement.buyer.address.country_id = "DE" # Defaults to DE
    
    # --- Settlement (Totals & Taxes) ---
    doc.trade.settlement.currency_code = "EUR"
    
    from drafthorse.models.accounting import ApplicableTradeTax
    tax = ApplicableTradeTax()
    tax.calculated_amount = float(invoice.tax_amount)
    tax.basis_amount = float(invoice.net_amount)
    tax.type_code = 'VAT'
    tax.category_code = 'S'
    tax.rate_applicable_percent = float(invoice.items[0].tax_percent) if invoice.items else 19.0
    doc.trade.settlement.trade_tax.add(tax)
    
    # We simplify this for the initial implementation to just match EN 16931 roughly.
    # A full mapping requires extensive trade tax lines and monetary summations.
    doc.trade.settlement.monetary_summation.line_total = float(invoice.net_amount)
    doc.trade.settlement.monetary_summation.charge_total = 0.0
    doc.trade.settlement.monetary_summation.allowance_total = 0.0
    doc.trade.settlement.monetary_summation.tax_basis_total = float(invoice.net_amount)
    doc.trade.settlement.monetary_summation.tax_total = (float(invoice.tax_amount), "EUR")
    doc.trade.settlement.monetary_summation.grand_total = float(invoice.gross_amount)
    doc.trade.settlement.monetary_summation.due_amount = float(invoice.gross_amount)
    
    # --- Items ---
    for i, item in enumerate(invoice.items, 1):
        line = LineItem()
        line.document.line_id = str(i)
        line.product.name = item.title
        
        # Agreement
        line.agreement.gross.amount = item.unit_price
        line.agreement.net.amount = item.unit_price
        
        # Delivery
        line.delivery.billed_quantity = (item.quantity, "C62") # C62 = pieces
        
        # Settlement
        line.settlement.trade_tax.type_code = "VAT"
        line.settlement.trade_tax.category_code = "S" if item.tax_percent > 0 else "E"
        line.settlement.trade_tax.rate_applicable_percent = item.tax_percent
        
        line.settlement.monetary_summation.total_amount = item.total_price
        
        doc.trade.items.add(line)
        
    xml_bytes = doc.serialize()
    with open(output_path, "wb") as f:
        f.write(xml_bytes)
    
    return output_path

