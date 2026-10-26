import datetime
from xml.sax.saxutils import escape
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from src.controllers.db_controller import DBController, DRAFT_PREFIX
from src.models.database import Invoice
from src.utils.calculations import tax_breakdown


def _fmt_money(value: float) -> str:
    # German format: 1.234,56 €
    return f"{value:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_number(value: float) -> str:
    text = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return text[:-3] if text.endswith(",00") else text


def _fmt_rate(rate: float) -> str:
    return f"{_fmt_number(rate)} %"


class PDFGenerator:
    def __init__(self, db_controller: DBController):
        self.db_controller = db_controller
        self.styles = getSampleStyleSheet()
        self.styles.add(ParagraphStyle(name='Right', alignment=2))
        self.styles.add(ParagraphStyle(name='Cell', parent=self.styles['Normal'], fontSize=9, leading=11))

    def _p(self, text, style='Normal', bold=False):
        # User data (names, addresses, item titles) must be escaped, reportlab parses Paragraphs as markup
        content = escape(str(text or ""))
        if bold:
            content = f"<b>{content}</b>"
        return Paragraph(content, self.styles[style])

    def _company_header(self, elements):
        company_name = self.db_controller.get_setting("company_name", "Meine Firma GmbH")
        company_address = self.db_controller.get_setting("address", "Musterstraße 1")
        company_city = f"{self.db_controller.get_setting('postal_code', '12345')} {self.db_controller.get_setting('city', 'Musterstadt')}"

        elements.append(self._p(company_name, 'Heading1', bold=True))
        elements.append(self._p(f"{company_address} | {company_city}"))

        tax_ids = []
        tax_id = self.db_controller.get_setting("tax_id", "")
        vat_id = self.db_controller.get_setting("vat_id", "")
        if tax_id:
            tax_ids.append(f"Steuernummer: {tax_id}")
        if vat_id:
            tax_ids.append(f"USt-IdNr.: {vat_id}")
        if tax_ids:
            elements.append(self._p(" | ".join(tax_ids)))
        elements.append(Spacer(1, 30))

    def _customer_block(self, elements, name, address, postal_code, city):
        elements.append(self._p(name, bold=True))
        if address:
            elements.append(self._p(address))
        if postal_code or city:
            elements.append(self._p(f"{postal_code or ''} {city or ''}"))
        elements.append(Spacer(1, 50))

    @staticmethod
    def _live_customer_fields(customer):
        name = customer.company_name if customer.company_name else f"{customer.first_name or ''} {customer.last_name or ''}".strip()
        return name, customer.address, customer.postal_code, customer.city

    def _invoice_customer_fields(self, invoice):
        # Finalized invoices use the recipient data frozen at finalization
        if invoice.customer_name:
            return invoice.customer_name, invoice.customer_address, invoice.customer_postal_code, invoice.customer_city
        return self._live_customer_fields(invoice.customer)

    def _bank_info(self, elements):
        account_holder = self.db_controller.get_setting('account_holder', '')
        bank_info = f"Bankverbindung: {self.db_controller.get_setting('bank_name', 'Musterbank')} | IBAN: {self.db_controller.get_setting('iban', 'DE12 3456 7890 1234 5678 90')} | BIC: {self.db_controller.get_setting('bic', 'MUSTERDEF1')}"
        if account_holder:
            bank_info += f" | Kontoinhaber: {account_holder}"
        elements.append(self._p(bank_info))

    def _items_table(self, items, net_amount, tax_amount, gross_amount, credit_amount=0.0, credit_desc=""):
        data = [['Pos.', 'Bezeichnung', 'Menge', 'Einzelpreis', 'MwSt.', 'Gesamtpreis']]

        for i, item in enumerate(items, 1):
            title = escape(item.title or "")
            if item.description:
                title += f"<br/><font size=8>{escape(item.description)}</font>"
            if item.discount_percent:
                title += f"<br/><font size=8>abzgl. {_fmt_number(item.discount_percent)} % Rabatt</font>"
            data.append([
                str(i),
                Paragraph(title, self.styles['Cell']),
                f"{_fmt_number(item.quantity)} {item.unit}",
                _fmt_money(item.unit_price),
                _fmt_rate(item.tax_percent),
                _fmt_money(item.total_price)
            ])

        item_rows = len(data)
        data.append(['', '', '', '', 'Nettobetrag:', _fmt_money(net_amount)])
        if credit_amount:
            desc = credit_desc or 'Gutschrift'
            if len(desc) > 15: desc = desc[:12] + "..."
            data.append(['', '', '', '', f"abzgl. {desc}:", _fmt_money(-credit_amount)])

        # One VAT line per tax rate (required when several rates are used)
        breakdown = tax_breakdown(items, credit_amount)
        if len(breakdown) <= 1:
            rate = next(iter(breakdown), 19.0)
            data.append(['', '', '', '', f"MwSt. {_fmt_rate(rate)}:", _fmt_money(tax_amount)])
        else:
            for rate, (_, tax) in sorted(breakdown.items()):
                data.append(['', '', '', '', f"MwSt. {_fmt_rate(rate)}:", _fmt_money(tax)])
        data.append(['', '', '', '', 'Gesamtbetrag:', _fmt_money(gross_amount)])

        table = Table(data, colWidths=[30, 170, 55, 70, 70, 75])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (1, 1), (1, -1), 'LEFT'),
            ('ALIGN', (3, 1), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, item_rows - 1), 1, colors.black),
            ('LINEABOVE', (4, item_rows), (-1, -1), 1, colors.black),
            ('FONTNAME', (4, -1), (-1, -1), 'Helvetica-Bold'),
        ]))
        return table

    def generate_invoice_pdf(self, invoice: Invoice, filepath: str):
        doc = SimpleDocTemplate(filepath, pagesize=A4,
                                rightMargin=60, leftMargin=60,
                                topMargin=72, bottomMargin=18)

        elements = []
        self._company_header(elements)
        self._customer_block(elements, *self._invoice_customer_fields(invoice))

        # Invoice Header
        is_draft = invoice.invoice_number.startswith(DRAFT_PREFIX)
        if is_draft:
            elements.append(self._p("ENTWURF – keine gültige Rechnung", 'Heading2', bold=True))
        elif invoice.cancels_invoice_id:
            original = self.db_controller.get_invoice(invoice.cancels_invoice_id)
            ref = f" zu Rechnung Nr. {original.invoice_number}" if original else ""
            elements.append(self._p(f"Stornorechnung Nr. {invoice.invoice_number}{ref}", 'Heading2', bold=True))
        else:
            elements.append(self._p(f"Rechnung Nr. {invoice.invoice_number}", 'Heading2', bold=True))
        elements.append(self._p(f"Rechnungsdatum: {invoice.invoice_date.strftime('%d.%m.%Y')}"))
        elements.append(self._p(f"Leistungsdatum: {invoice.delivery_date.strftime('%d.%m.%Y')}"))
        if invoice.customer_vat_id:
            elements.append(self._p(f"USt-IdNr. des Leistungsempfängers: {invoice.customer_vat_id}"))
        elements.append(Spacer(1, 20))

        elements.append(self._items_table(
            invoice.items, invoice.net_amount, invoice.tax_amount, invoice.gross_amount,
            invoice.credit_amount or 0.0, invoice.credit_desc
        ))
        elements.append(Spacer(1, 40))

        if invoice.cancels_invoice_id:
            elements.append(self._p("Mit dieser Stornorechnung wird die oben genannte Rechnung vollständig aufgehoben."))
        else:
            payment_terms = self.db_controller.get_payment_terms()
            elements.append(self._p(f"Bitte überweisen Sie den fälligen Betrag innerhalb von {payment_terms} Tagen ohne Abzug."))

        self._bank_info(elements)
        doc.build(elements)

    def generate_quote_pdf(self, quote, filepath: str):
        doc = SimpleDocTemplate(filepath, pagesize=A4, rightMargin=60, leftMargin=60, topMargin=72, bottomMargin=18)
        elements = []
        self._company_header(elements)
        self._customer_block(elements, *self._live_customer_fields(quote.customer))

        elements.append(self._p(f"Angebot Nr. {quote.quote_number}", 'Heading2', bold=True))
        elements.append(self._p(f"Angebotsdatum: {quote.quote_date.strftime('%d.%m.%Y')}"))
        elements.append(Spacer(1, 20))

        elements.append(self._items_table(quote.items, quote.net_amount, quote.tax_amount, quote.gross_amount))
        elements.append(Spacer(1, 40))
        elements.append(self._p("Wir hoffen, dass Ihnen dieses Angebot zusagt und stehen für Rückfragen gerne zur Verfügung."))
        elements.append(self._p("Das Angebot ist 14 Tage gültig."))

        doc.build(elements)

    def generate_reminder_pdf(self, invoice: Invoice, filepath: str, level: int = 1):
        doc = SimpleDocTemplate(filepath, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)
        elements = []
        self._company_header(elements)
        # Reminders go to the customer's current address
        self._customer_block(elements, *self._live_customer_fields(invoice.customer))

        elements.append(self._p(f"{level}. Mahnung - Rechnung Nr. {invoice.invoice_number}", 'Heading2', bold=True))
        elements.append(self._p(f"Datum der Mahnung: {datetime.date.today().strftime('%d.%m.%Y')}"))
        elements.append(Spacer(1, 20))

        elements.append(self._p("Sehr geehrte Damen und Herren,"))
        elements.append(Spacer(1, 10))

        inv_ref = f"Rechnung Nr. {invoice.invoice_number} vom {invoice.invoice_date.strftime('%d.%m.%Y')} über {_fmt_money(invoice.gross_amount)}"
        if level == 1:
            elements.append(self._p(f"leider konnten wir bis heute keinen Zahlungseingang für unsere {inv_ref} feststellen."))
            elements.append(Spacer(1, 10))
            elements.append(self._p("Wir bitten Sie, den fälligen Betrag umgehend, spätestens jedoch innerhalb der nächsten 14 Tage, auf unser unten stehendes Konto zu überweisen."))
        elif level == 2:
            elements.append(self._p(f"trotz unserer ersten Zahlungserinnerung konnten wir bisher noch keinen Zahlungseingang für unsere {inv_ref} feststellen."))
            elements.append(Spacer(1, 10))
            elements.append(self._p("Wir bitten Sie nun nachdrücklich, den ausstehenden Betrag innerhalb der nächsten 14 Tage zu begleichen."))
        else:
            elements.append(self._p(f"hiermit fordern wir Sie letztmalig auf, unsere {inv_ref} zu begleichen."))
            elements.append(Spacer(1, 10))
            elements.append(self._p("Sollte der Betrag nicht innerhalb von 14 Tagen auf unserem Konto eingehen, sehen wir uns gezwungen, rechtliche Schritte einzuleiten."))

        elements.append(Spacer(1, 10))
        elements.append(self._p("Sollte sich diese Zahlung mit diesem Schreiben gekreuzt haben, so betrachten Sie diese Mahnung bitte als gegenstandslos."))

        self._bank_info(elements)
        doc.build(elements)
