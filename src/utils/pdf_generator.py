import os
from datetime import datetime
from pdfrw import PdfReader, PdfWriter, PageMerge
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import tempfile
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from src.controllers.db_controller import DBController
from src.models.database import Invoice

class PDFGenerator:
    def __init__(self, db_controller: DBController):
        self.db_controller = db_controller
        self.styles = getSampleStyleSheet()
        self.styles.add(ParagraphStyle(name='Right', alignment=2))
        
    def generate_invoice_pdf(self, invoice: Invoice, filepath: str):
        doc = SimpleDocTemplate(filepath, pagesize=A4,
                                rightMargin=72, leftMargin=72,
                                topMargin=72, bottomMargin=18)
        
        elements = []
        
        # Company Info
        company_name = self.db_controller.get_setting("company_name", "Meine Firma GmbH")
        company_address = self.db_controller.get_setting("address", "Musterstraße 1")
        company_city = f"{self.db_controller.get_setting('postal_code', '12345')} {self.db_controller.get_setting('city', 'Musterstadt')}"
        
        elements.append(Paragraph(f"<b>{company_name}</b>", self.styles['Heading1']))
        elements.append(Paragraph(f"{company_address} | {company_city}", self.styles['Normal']))
        elements.append(Spacer(1, 30))
        
        # Customer Info
        customer = invoice.customer
        c_name = customer.company_name if customer.company_name else f"{customer.first_name} {customer.last_name}"
        elements.append(Paragraph(f"<b>{c_name}</b>", self.styles['Normal']))
        if customer.address:
            elements.append(Paragraph(customer.address, self.styles['Normal']))
        if customer.postal_code or customer.city:
            elements.append(Paragraph(f"{customer.postal_code or ''} {customer.city or ''}", self.styles['Normal']))
        
        elements.append(Spacer(1, 50))
        
        # Invoice Header
        elements.append(Paragraph(f"<b>Rechnung Nr. {invoice.invoice_number}</b>", self.styles['Heading2']))
        elements.append(Paragraph(f"Rechnungsdatum: {invoice.invoice_date.strftime('%d.%m.%Y')}", self.styles['Normal']))
        elements.append(Paragraph(f"Leistungsdatum: {invoice.delivery_date.strftime('%d.%m.%Y')}", self.styles['Normal']))
        elements.append(Spacer(1, 20))
        
        # Items Table
        data = [['Pos.', 'Bezeichnung', 'Menge', 'Einzelpreis', 'MwSt.', 'Gesamtpreis']]
        
        for i, item in enumerate(invoice.items, 1):
            data.append([
                str(i),
                item.title,
                f"{item.quantity} {item.unit}",
                f"{item.unit_price:.2f} €",
                f"{item.tax_percent}%",
                f"{item.total_price:.2f} €"
            ])
            
        # Totals
        if getattr(invoice, 'credit_amount', 0.0) > 0:
            desc = invoice.credit_desc or 'Gutschrift'
            if len(desc) > 15: desc = desc[:12] + "..."
            data.append(['', '', '', '', 'Nettobetrag:', f"{invoice.net_amount:.2f} €"])
            data.append(['', '', '', '', f"abzgl. {desc}:", f"-{invoice.credit_amount:.2f} €"])
            data.append(['', '', '', '', 'MwSt.:', f"{invoice.tax_amount:.2f} €"])
            totals_start = -4
        else:
            data.append(['', '', '', '', 'Nettobetrag:', f"{invoice.net_amount:.2f} €"])
            data.append(['', '', '', '', 'MwSt.:', f"{invoice.tax_amount:.2f} €"])
            totals_start = -3
            
        data.append(['', '', '', '', 'Gesamtbetrag:', f"{invoice.gross_amount:.2f} €"])
        
        table = Table(data, colWidths=[30, 180, 50, 70, 40, 80])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (1, 1), (1, -1), 'LEFT'),
            ('ALIGN', (3, 1), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, totals_start - 1), 1, colors.black),
            ('LINEABOVE', (4, totals_start), (-1, -1), 1, colors.black),
            ('FONTNAME', (4, -1), (-1, -1), 'Helvetica-Bold'),
        ]))
        
        elements.append(table)
        elements.append(Spacer(1, 40))
        
        # Payment Terms
        try:
            payment_terms = int(self.db_controller.get_setting("payment_terms_days") or 14)
        except ValueError:
            payment_terms = 14
        elements.append(Paragraph(f"Bitte überweisen Sie den fälligen Betrag innerhalb von {payment_terms} Tagen ohne Abzug.", self.styles['Normal']))
        
        # Bank Details
        account_holder = self.db_controller.get_setting('account_holder', '')
        bank_info = f"Bankverbindung: {self.db_controller.get_setting('bank_name', 'Musterbank')} | IBAN: {self.db_controller.get_setting('iban', 'DE12 3456 7890 1234 5678 90')} | BIC: {self.db_controller.get_setting('bic', 'MUSTERDEF1')}"
        if account_holder:
            bank_info += f" | Kontoinhaber: {account_holder}"
        elements.append(Paragraph(bank_info, self.styles['Normal']))
        
        doc.build(elements)

    def generate_quote_pdf(self, quote, filepath: str):
        doc = SimpleDocTemplate(filepath, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
        elements = []
        
        company_name = self.db_controller.get_setting("company_name", "Meine Firma GmbH")
        company_address = self.db_controller.get_setting("address", "Musterstraße 1")
        company_city = f"{self.db_controller.get_setting('postal_code', '12345')} {self.db_controller.get_setting('city', 'Musterstadt')}"
        
        elements.append(Paragraph(f"<b>{company_name}</b>", self.styles['Heading1']))
        elements.append(Paragraph(f"{company_address} | {company_city}", self.styles['Normal']))
        elements.append(Spacer(1, 30))
        
        customer = quote.customer
        c_name = customer.company_name if customer.company_name else f"{customer.first_name} {customer.last_name}"
        elements.append(Paragraph(f"<b>{c_name}</b>", self.styles['Normal']))
        if customer.address: elements.append(Paragraph(customer.address, self.styles['Normal']))
        if customer.postal_code or customer.city: elements.append(Paragraph(f"{customer.postal_code or ''} {customer.city or ''}", self.styles['Normal']))
        
        elements.append(Spacer(1, 50))
        
        elements.append(Paragraph(f"<b>Angebot Nr. {quote.quote_number}</b>", self.styles['Heading2']))
        elements.append(Paragraph(f"Angebotsdatum: {quote.quote_date.strftime('%d.%m.%Y')}", self.styles['Normal']))
        elements.append(Spacer(1, 20))
        
        data = [['Pos.', 'Bezeichnung', 'Menge', 'Einzelpreis', 'MwSt.', 'Gesamtpreis']]
        for i, item in enumerate(quote.items, 1):
            data.append([str(i), item.title, f"{item.quantity} {item.unit}", f"{item.unit_price:.2f} €", f"{item.tax_percent}%", f"{item.total_price:.2f} €"])
            
        data.append(['', '', '', '', 'Nettobetrag:', f"{quote.net_amount:.2f} €"])
        data.append(['', '', '', '', 'MwSt.:', f"{quote.tax_amount:.2f} €"])
        data.append(['', '', '', '', 'Gesamtbetrag:', f"{quote.gross_amount:.2f} €"])
        
        table = Table(data, colWidths=[30, 180, 50, 70, 40, 80])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (1, 1), (1, -1), 'LEFT'),
            ('ALIGN', (3, 1), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -4), 1, colors.black),
            ('LINEABOVE', (4, -3), (-1, -1), 1, colors.black),
            ('FONTNAME', (4, -1), (-1, -1), 'Helvetica-Bold'),
        ]))
        
        elements.append(table)
        elements.append(Spacer(1, 40))
        elements.append(Paragraph("Wir hoffen, dass Ihnen dieses Angebot zusagt und stehen für Rückfragen gerne zur Verfügung.", self.styles['Normal']))
        elements.append(Paragraph("Das Angebot ist 14 Tage gültig.", self.styles['Normal']))
        
        doc.build(elements)

    def generate_reminder_pdf(self, invoice: Invoice, filepath: str, level: int = 1):
        doc = SimpleDocTemplate(filepath, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
        elements = []
        
        company_name = self.db_controller.get_setting("company_name", "Meine Firma GmbH")
        company_address = self.db_controller.get_setting("address", "Musterstraße 1")
        company_city = f"{self.db_controller.get_setting('postal_code', '12345')} {self.db_controller.get_setting('city', 'Musterstadt')}"
        
        elements.append(Paragraph(f"<b>{company_name}</b>", self.styles['Heading1']))
        elements.append(Paragraph(f"{company_address} | {company_city}", self.styles['Normal']))
        elements.append(Spacer(1, 30))
        
        customer = invoice.customer
        c_name = customer.company_name if customer.company_name else f"{customer.first_name} {customer.last_name}"
        elements.append(Paragraph(f"<b>{c_name}</b>", self.styles['Normal']))
        if customer.address: elements.append(Paragraph(customer.address, self.styles['Normal']))
        if customer.postal_code or customer.city: elements.append(Paragraph(f"{customer.postal_code or ''} {customer.city or ''}", self.styles['Normal']))
        
        elements.append(Spacer(1, 50))
        
        import datetime
        elements.append(Paragraph(f"<b>{level}. Mahnung - Rechnung Nr. {invoice.invoice_number}</b>", self.styles['Heading2']))
        elements.append(Paragraph(f"Datum der Mahnung: {datetime.date.today().strftime('%d.%m.%Y')}", self.styles['Normal']))
        elements.append(Spacer(1, 20))
        
        elements.append(Paragraph("Sehr geehrte Damen und Herren,", self.styles['Normal']))
        elements.append(Spacer(1, 10))
        
        if level == 1:
            elements.append(Paragraph(f"leider konnten wir bis heute keinen Zahlungseingang für unsere Rechnung Nr. {invoice.invoice_number} vom {invoice.invoice_date.strftime('%d.%m.%Y')} über {invoice.gross_amount:.2f} € feststellen.", self.styles['Normal']))
            elements.append(Spacer(1, 10))
            elements.append(Paragraph("Wir bitten Sie, den fälligen Betrag umgehend, spätestens jedoch innerhalb der nächsten 14 Tage, auf unser unten stehendes Konto zu überweisen.", self.styles['Normal']))
        elif level == 2:
            elements.append(Paragraph(f"trotz unserer ersten Zahlungserinnerung konnten wir bisher noch keinen Zahlungseingang für unsere Rechnung Nr. {invoice.invoice_number} vom {invoice.invoice_date.strftime('%d.%m.%Y')} über {invoice.gross_amount:.2f} € feststellen.", self.styles['Normal']))
            elements.append(Spacer(1, 10))
            elements.append(Paragraph("Wir bitten Sie nun nachdrücklich, den ausstehenden Betrag innerhalb der nächsten 14 Tage zu begleichen.", self.styles['Normal']))
        else:
            elements.append(Paragraph(f"hiermit fordern wir Sie letztmalig auf, unsere Rechnung Nr. {invoice.invoice_number} vom {invoice.invoice_date.strftime('%d.%m.%Y')} über {invoice.gross_amount:.2f} € zu begleichen.", self.styles['Normal']))
            elements.append(Spacer(1, 10))
            elements.append(Paragraph("Sollte der Betrag nicht innerhalb von 14 Tagen auf unserem Konto eingehen, sehen wir uns gezwungen, rechtliche Schritte einzuleiten.", self.styles['Normal']))

        elements.append(Spacer(1, 10))
        elements.append(Paragraph("Sollte sich diese Zahlung mit diesem Schreiben gekreuzt haben, so betrachten Sie diese Mahnung bitte als gegenstandslos.", self.styles['Normal']))
        
        account_holder = self.db_controller.get_setting('account_holder', '')
        bank_info = f"Bankverbindung: {self.db_controller.get_setting('bank_name', 'Musterbank')} | IBAN: {self.db_controller.get_setting('iban', 'DE12 3456 7890 1234 5678 90')} | BIC: {self.db_controller.get_setting('bic', 'MUSTERDEF1')}"
        if account_holder:
            bank_info += f" | Kontoinhaber: {account_holder}"
        elements.append(Paragraph(bank_info, self.styles['Normal']))
        
        doc.build(elements)

