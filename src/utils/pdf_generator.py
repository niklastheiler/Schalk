import datetime
import os
from functools import lru_cache
from io import BytesIO
from xml.sax.saxutils import escape
import reportlab
import reportlab.rl_config
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.fonts import addMapping
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from src.controllers.db_controller import DBController
from src.models.database import Invoice
from src.utils.calculations import tax_breakdown
from src.utils.tax import format_rate

FONT = "Vera"
FONT_BOLD = "Vera-Bold"


@lru_cache(maxsize=1)
def _register_fonts():
    # PDF/A requires embedded fonts; the standard 14 PDF fonts (Helvetica, ...) are not embedded
    font_dir = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
    for name, filename in ((FONT, "Vera.ttf"), (FONT_BOLD, "VeraBd.ttf"), ("Vera-Italic", "VeraIt.ttf"), ("Vera-BoldItalic", "VeraBI.ttf")):
        pdfmetrics.registerFont(TTFont(name, os.path.join(font_dir, filename)))
    addMapping(FONT, 0, 0, FONT)
    addMapping(FONT, 1, 0, FONT_BOLD)
    addMapping(FONT, 0, 1, "Vera-Italic")
    addMapping(FONT, 1, 1, "Vera-BoldItalic")
    # The canvas starts with this font; it must be embedded as well
    reportlab.rl_config.canvas_basefontname = FONT


@lru_cache(maxsize=1)
def _styles():
    _register_fonts()
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = FONT_BOLD if "Heading" in style.name or style.name == "Title" else FONT
    styles.add(ParagraphStyle(name='Small', parent=styles['Normal'], fontSize=8, leading=10))
    styles.add(ParagraphStyle(name='Cell', parent=styles['Normal'], fontSize=9, leading=11))
    return styles


def _markup(text) -> str:
    """User data for a reportlab Paragraph: escaped (it is parsed as markup), line breaks kept."""
    return escape(str(text or "")).replace("\r\n", "\n").replace("\n", "<br/>")


def fmt_money(value: float) -> str:
    # German format: 1.234,56 €
    return f"{value:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_number(value: float) -> str:
    text = f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return text[:-3] if text.endswith(",00") else text


class PDFGenerator:
    def __init__(self, db_controller: DBController):
        self.db_controller = db_controller
        self.styles = _styles()

    def _p(self, text, style='Normal', bold=False):
        content = _markup(text)
        if bold:
            content = f"<b>{content}</b>"
        return Paragraph(content, self.styles[style])

    def _doc(self, target, title: str):
        seller = self.db_controller.current_seller()
        return SimpleDocTemplate(target, pagesize=A4, rightMargin=20 * mm, leftMargin=20 * mm, topMargin=20 * mm,
                                 bottomMargin=20 * mm, title=title, author=seller.get("company_name") or "", creator="Schalk")

    def _company_header(self, elements, seller: dict):
        name = seller.get("company_name") or f"{seller.get('first_name', '')} {seller.get('last_name', '')}".strip()
        header = [self._p(name, 'Heading1', bold=True),
                  self._p(f"{seller.get('address', '')} | {seller.get('postal_code', '')} {seller.get('city', '')}")]
        contact = " | ".join(v for v in (seller.get("phone"), seller.get("email")) if v)
        if contact:
            header.append(self._p(contact, 'Small'))
        tax_ids = []
        if seller.get("tax_id"):
            tax_ids.append(f"Steuernummer: {seller['tax_id']}")
        if seller.get("vat_id"):
            tax_ids.append(f"USt-IdNr.: {seller['vat_id']}")
        if tax_ids:
            header.append(self._p(" | ".join(tax_ids), 'Small'))

        logo_path = self.db_controller.get_setting("logo_path")
        if logo_path and os.path.isfile(logo_path):
            logo = Image(logo_path)
            logo._restrictSize(50 * mm, 25 * mm)
            table = Table([[header, logo]], colWidths=[120 * mm, 50 * mm])
            table.setStyle(TableStyle([('FONTNAME', (0, 0), (-1, -1), FONT), ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
                                       ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0)]))
            elements.append(table)
        else:
            elements.extend(header)
        elements.append(Spacer(1, 30))

    def _customer_block(self, elements, buyer: dict):
        elements.append(self._p(buyer.get("name"), bold=True))
        if buyer.get("address"):
            elements.append(self._p(buyer["address"]))
        if buyer.get("postal_code") or buyer.get("city"):
            elements.append(self._p(f"{buyer.get('postal_code') or ''} {buyer.get('city') or ''}"))
        country = (buyer.get("country") or "DE").upper()
        if country != "DE":
            elements.append(self._p(country))
        elements.append(Spacer(1, 40))

    @staticmethod
    def _buyer_from_customer(customer) -> dict:
        return {"name": customer.display_name, "address": customer.address, "postal_code": customer.postal_code,
                "city": customer.city, "country": customer.country}

    def _bank_info(self, elements, seller: dict):
        if not seller.get("iban"):
            return
        parts = [f"Bankverbindung: {seller.get('bank_name') or ''}".rstrip(), f"IBAN: {seller['iban']}"]
        if seller.get("bic"):
            parts.append(f"BIC: {seller['bic']}")
        if seller.get("account_holder"):
            parts.append(f"Kontoinhaber: {seller['account_holder']}")
        elements.append(Spacer(1, 10))
        elements.append(self._p(" | ".join(parts), 'Small'))

    def _items_table(self, items, net_amount, tax_amount, gross_amount, credit_amount=0.0, credit_desc=""):
        data = [['Pos.', 'Bezeichnung', 'Menge', 'Einzelpreis', 'MwSt.', 'Gesamtpreis']]

        for i, item in enumerate(items, 1):
            title = _markup(item.title)
            if item.description:
                title += f"<br/><font size=8>{_markup(item.description)}</font>"
            if item.discount_percent:
                title += f"<br/><font size=8>abzgl. {fmt_number(item.discount_percent)} % Rabatt</font>"
            data.append([
                str(i),
                Paragraph(title, self.styles['Cell']),
                f"{fmt_number(item.quantity)} {item.unit}",
                fmt_money(item.unit_price),
                format_rate(item.tax_percent),
                fmt_money(item.total_price)
            ])

        item_rows = len(data)
        data.append(['', '', '', '', 'Nettobetrag:', fmt_money(net_amount)])
        if credit_amount:
            desc = credit_desc or 'Gutschrift'
            if len(desc) > 15: desc = desc[:12] + "..."
            data.append(['', '', '', '', f"abzgl. {desc}:", fmt_money(-credit_amount)])

        # One VAT line per tax rate (§ 14 Abs. 4 Nr. 8 UStG)
        for rate, (_, tax) in sorted(tax_breakdown(items, credit_amount).items(), reverse=True):
            data.append(['', '', '', '', f"MwSt. {format_rate(rate)}:", fmt_money(tax)])
        data.append(['', '', '', '', 'Gesamtbetrag:', fmt_money(gross_amount)])

        table = Table(data, colWidths=[12 * mm, 62 * mm, 22 * mm, 25 * mm, 25 * mm, 24 * mm], repeatRows=1)
        table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (1, 1), (1, -1), 'LEFT'),
            ('ALIGN', (3, 1), (-1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, 0), FONT_BOLD),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('GRID', (0, 0), (-1, item_rows - 1), 0.5, colors.black),
            ('LINEABOVE', (4, item_rows), (-1, -1), 0.5, colors.black),
            ('FONTNAME', (4, -1), (-1, -1), FONT_BOLD),
        ]))
        return table

    def render_invoice(self, invoice: Invoice) -> bytes:
        buffer = BytesIO()
        seller = self.db_controller.seller_of(invoice)
        is_draft = self.db_controller.is_draft_number(invoice.invoice_number)
        doc = self._doc(buffer, f"Rechnung {invoice.invoice_number}")

        elements = []
        self._company_header(elements, seller)
        self._customer_block(elements, self.db_controller.buyer_of(invoice))

        if is_draft:
            elements.append(self._p("ENTWURF – keine gültige Rechnung", 'Heading2', bold=True))
        elif invoice.cancels_invoice_id:
            original = self.db_controller.get_invoice_header(invoice.cancels_invoice_id)
            ref = f" zu Rechnung Nr. {original.invoice_number} vom {original.invoice_date.strftime('%d.%m.%Y')}" if original else ""
            elements.append(self._p(f"Stornorechnung Nr. {invoice.invoice_number}{ref}", 'Heading2', bold=True))
        else:
            elements.append(self._p(f"Rechnung Nr. {invoice.invoice_number}", 'Heading2', bold=True))
        elements.append(self._p(f"Rechnungsdatum: {invoice.invoice_date.strftime('%d.%m.%Y')}"))
        elements.append(self._p(f"Leistungsdatum: {invoice.delivery_date.strftime('%d.%m.%Y')}"))
        buyer = self.db_controller.buyer_of(invoice)
        if buyer.get("vat_id"):
            elements.append(self._p(f"USt-IdNr. des Leistungsempfängers: {buyer['vat_id']}"))
        if buyer.get("buyer_reference"):
            elements.append(self._p(f"Ihre Referenz: {buyer['buyer_reference']}"))
        elements.append(Spacer(1, 16))

        elements.append(self._items_table(
            invoice.items, invoice.net_amount, invoice.tax_amount, invoice.gross_amount,
            invoice.credit_amount or 0.0, invoice.credit_desc
        ))
        elements.append(Spacer(1, 16))
        if invoice.tax_exemption_reason:
            elements.append(self._p(f"Hinweis: {invoice.tax_exemption_reason}"))
            elements.append(Spacer(1, 8))

        if invoice.cancels_invoice_id:
            elements.append(self._p("Mit dieser Stornorechnung wird die oben genannte Rechnung vollständig aufgehoben."))
        else:
            due = self.db_controller.get_due_date(invoice)
            terms = self.db_controller.payment_terms_of(invoice)
            elements.append(self._p(f"Bitte überweisen Sie den Betrag innerhalb von {terms} Tagen ohne Abzug bis zum "
                                    f"{due.strftime('%d.%m.%Y')} unter Angabe der Rechnungsnummer."))

        self._bank_info(elements, seller)
        doc.build(elements)
        return buffer.getvalue()

    def generate_invoice_pdf(self, invoice: Invoice, filepath: str):
        with open(filepath, "wb") as f:
            f.write(self.render_invoice(invoice))

    def generate_quote_pdf(self, quote, filepath: str):
        seller = self.db_controller.current_seller()
        doc = self._doc(filepath, f"Angebot {quote.quote_number}")
        elements = []
        self._company_header(elements, seller)
        self._customer_block(elements, self._buyer_from_customer(self.db_controller.get_customer(quote.customer_id)))

        elements.append(self._p(f"Angebot Nr. {quote.quote_number}", 'Heading2', bold=True))
        elements.append(self._p(f"Angebotsdatum: {quote.quote_date.strftime('%d.%m.%Y')}"))
        elements.append(Spacer(1, 16))

        elements.append(self._items_table(quote.items, quote.net_amount, quote.tax_amount, quote.gross_amount))
        elements.append(Spacer(1, 16))
        if quote.tax_exemption_reason:
            elements.append(self._p(f"Hinweis: {quote.tax_exemption_reason}"))
            elements.append(Spacer(1, 8))
        elements.append(self._p("Wir hoffen, dass Ihnen dieses Angebot zusagt und stehen für Rückfragen gerne zur Verfügung."))
        elements.append(self._p("Das Angebot ist 14 Tage gültig."))

        doc.build(elements)

    def generate_reminder_pdf(self, invoice: Invoice, filepath: str, level: int = 1):
        seller = self.db_controller.current_seller()
        doc = self._doc(filepath, f"{level}. Mahnung {invoice.invoice_number}")
        elements = []
        self._company_header(elements, seller)
        # Reminders go to the customer's current address
        self._customer_block(elements, self._buyer_from_customer(self.db_controller.get_customer(invoice.customer_id)))

        elements.append(self._p(f"{level}. Mahnung - Rechnung Nr. {invoice.invoice_number}", 'Heading2', bold=True))
        elements.append(self._p(f"Datum der Mahnung: {datetime.date.today().strftime('%d.%m.%Y')}"))
        elements.append(Spacer(1, 16))

        elements.append(self._p("Sehr geehrte Damen und Herren,"))
        elements.append(Spacer(1, 10))

        inv_ref = f"Rechnung Nr. {invoice.invoice_number} vom {invoice.invoice_date.strftime('%d.%m.%Y')} über {fmt_money(invoice.gross_amount)}"
        if level == 1:
            texts = [f"leider konnten wir bis heute keinen Zahlungseingang für unsere {inv_ref} feststellen.",
                     "Wir bitten Sie, den fälligen Betrag umgehend, spätestens jedoch innerhalb der nächsten 14 Tage, auf unser unten stehendes Konto zu überweisen."]
        elif level == 2:
            texts = [f"trotz unserer ersten Zahlungserinnerung konnten wir bisher noch keinen Zahlungseingang für unsere {inv_ref} feststellen.",
                     "Wir bitten Sie nun nachdrücklich, den ausstehenden Betrag innerhalb der nächsten 14 Tage zu begleichen."]
        else:
            texts = [f"hiermit fordern wir Sie letztmalig auf, unsere {inv_ref} zu begleichen.",
                     "Sollte der Betrag nicht innerhalb von 14 Tagen auf unserem Konto eingehen, sehen wir uns gezwungen, rechtliche Schritte einzuleiten."]
        texts.append("Sollte sich diese Zahlung mit diesem Schreiben gekreuzt haben, so betrachten Sie diese Mahnung bitte als gegenstandslos.")
        for text in texts:
            elements.append(self._p(text))
            elements.append(Spacer(1, 10))

        self._bank_info(elements, seller)
        doc.build(elements)
