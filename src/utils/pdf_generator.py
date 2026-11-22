"""
Invoices, quotes and reminders as PDF.

Layout after DIN 5008 (form B): the sender line and the recipient sit in the window of a DL or C5/6 envelope,
the information block (number, dates, customer number) on the right, fold and punch marks on the left edge.
Every page carries a footer with company, contact, bank and tax data and "Seite x von y". All fonts are
embedded, as PDF/A (ZUGFeRD) requires.
"""
import datetime
import os
from dataclasses import dataclass, field
from functools import lru_cache
from io import BytesIO
from typing import List, Optional, Tuple
from xml.sax.saxutils import escape
import reportlab.rl_config
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.fonts import addMapping
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import BaseDocTemplate, Frame, Image, KeepTogether, PageTemplate, Paragraph, Spacer, Table, TableStyle
from src.controllers.db_controller import DBController
from src.models.database import Invoice
from src.utils import paths
from src.utils.calculations import tax_breakdown
from src.utils.tax import format_rate
from src.utils.text import fmt_money, fmt_number, fmt_price, payment_terms_text

FONT = "Inter"
FONT_BOLD = "Inter-SemiBold"
FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "fonts")

PAGE_WIDTH, PAGE_HEIGHT = A4
LEFT, RIGHT = 25 * mm, 20 * mm
CONTENT_WIDTH = PAGE_WIDTH - LEFT - RIGHT
FIRST_TOP = 95 * mm # the first page starts below the address field and the information block
LATER_TOP = 25 * mm
BOTTOM = 34 * mm # room for the footer
INFO_LEFT = 125 * mm

TEXT = colors.HexColor("#1F2937")
MUTED = colors.HexColor("#6B7280")
RULE = colors.HexColor("#E5E7EB")
RULE_STRONG = colors.HexColor("#CBD0D6")
NOTE_BACKGROUND = colors.HexColor("#F4F5F7")
MARKS = colors.HexColor("#9CA3AF")
WATERMARK = colors.HexColor("#ECEEF1")

# Accent colour of titles, table head and total (Einstellungen > Firmendaten)
DOCUMENT_COLORS = {
    "Nachtblau": "#1E3A5F",
    "Anthrazit": "#374151",
    "Petrol": "#0E5E66",
    "Grün": "#2E6B3A",
    "Bordeaux": "#7A1F2B",
    "Rot": "#B3261E",
}
DEFAULT_DOCUMENT_COLOR = "Nachtblau"

COUNTRY_NAMES = {
    "AT": "Österreich", "BE": "Belgien", "BG": "Bulgarien", "CH": "Schweiz", "CY": "Zypern", "CZ": "Tschechien",
    "DK": "Dänemark", "EE": "Estland", "ES": "Spanien", "FI": "Finnland", "FR": "Frankreich", "GB": "Vereinigtes Königreich",
    "GR": "Griechenland", "HR": "Kroatien", "HU": "Ungarn", "IE": "Irland", "IT": "Italien", "LI": "Liechtenstein",
    "LT": "Litauen", "LU": "Luxemburg", "LV": "Lettland", "MT": "Malta", "NL": "Niederlande", "NO": "Norwegen",
    "PL": "Polen", "PT": "Portugal", "RO": "Rumänien", "SE": "Schweden", "SI": "Slowenien", "SK": "Slowakei",
    "TR": "Türkei", "UA": "Ukraine", "US": "Vereinigte Staaten",
}


@lru_cache(maxsize=1)
def _register_fonts():
    # PDF/A requires embedded fonts; the standard 14 PDF fonts (Helvetica, ...) are not embedded.
    # Inter has the letters of names such as Łódź, Dvořák, Wiśniewski or Şahin as well.
    for name in (FONT, FONT_BOLD):
        pdfmetrics.registerFont(TTFont(name, os.path.join(FONT_DIR, f"{name}.ttf")))
    # <b> is the semi-bold weight; documents use no italics, <i> falls back to the upright font
    addMapping(FONT, 0, 0, FONT)
    addMapping(FONT, 1, 0, FONT_BOLD)
    addMapping(FONT, 0, 1, FONT)
    addMapping(FONT, 1, 1, FONT_BOLD)
    # The canvas starts with this font; it must be embedded as well
    reportlab.rl_config.canvas_basefontname = FONT


@lru_cache(maxsize=None)
def _styles(accent: str) -> dict:
    _register_fonts()
    accent = colors.HexColor(accent)

    def style(name, font=FONT, size=9.5, leading=None, color=TEXT, **kwargs):
        return ParagraphStyle(name, fontName=font, fontSize=size, leading=leading or size * 1.4, textColor=color, **kwargs)

    return {
        "body": style("body", leading=14.5),
        "title": style("title", FONT_BOLD, 21, 26, accent),
        "address": style("address", size=10, leading=14),
        "sender": style("sender", size=7, color=MUTED),
        "label": style("label", size=8, leading=11.5, color=MUTED),
        "value": style("value", size=8.5, leading=11.5),
        "head": style("head", FONT_BOLD, 7.5, color=MUTED),
        "head_right": style("head_right", FONT_BOLD, 7.5, color=MUTED, alignment=TA_RIGHT),
        "cell": style("cell", size=9, leading=12),
        "cell_bold": style("cell_bold", FONT_BOLD, 9, 12),
        "cell_muted": style("cell_muted", size=8, leading=11, color=MUTED),
        "cell_right": style("cell_right", size=9, leading=12, alignment=TA_RIGHT),
        "cell_bold_right": style("cell_bold_right", FONT_BOLD, 9, 12, alignment=TA_RIGHT),
        "total": style("total", size=9, leading=12, alignment=TA_RIGHT),
        "grand_total": style("grand_total", FONT_BOLD, 11, 14, accent, alignment=TA_RIGHT),
        "footer": style("footer", size=7, leading=9.4, color=MUTED),
        "footer_head": style("footer_head", FONT_BOLD, 7, 9.4, TEXT),
    }


def _table_style(commands: list) -> TableStyle:
    # Also for empty cells: without it reportlab sets the standard font Helvetica, which is not embedded (PDF/A)
    return TableStyle([("FONTNAME", (0, 0), (-1, -1), FONT)] + list(commands))


def _markup(text) -> str:
    """User data for a reportlab Paragraph: escaped (it is parsed as markup), line breaks kept."""
    return escape(str(text or "")).replace("\r\n", "\n").replace("\n", "<br/>")


def _date(value) -> str:
    return value.strftime("%d.%m.%Y") if value else ""


def _period(start, end) -> str:
    """Leistungszeitraum: 01.10.–31.10.2026, across a year 15.12.2026–15.01.2027"""
    if start.year == end.year:
        return f"{start:%d.%m.}–{_date(end)}"
    return f"{_date(start)}–{_date(end)}"


def _iban(iban: str) -> str:
    compact = (iban or "").replace(" ", "")
    return " ".join(compact[i:i + 4] for i in range(0, len(compact), 4))


def document_color(name: str) -> str:
    return DOCUMENT_COLORS.get(name) or DOCUMENT_COLORS[DEFAULT_DOCUMENT_COLOR]


@dataclass
class _Letter:
    """Everything drawn around the flowing content: letterhead, address, information block, footer."""
    title: str # also the PDF title and the header of following pages
    seller: dict
    recipient: dict
    info: List[Tuple[str, str]]
    accent: str
    logo: Optional[str] = None
    draft: bool = False
    styles: dict = field(default_factory=dict)


def _numbered_canvas(draw_page):
    """Canvas that knows the page count when the pages are written, for "Seite x von y"."""
    class NumberedCanvas(rl_canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            for state in self._pages:
                self.__dict__.update(state)
                draw_page(self, len(self._pages))
                super().showPage()
            super().save()
    return NumberedCanvas


class PDFGenerator:
    def __init__(self, db_controller: DBController):
        self.db_controller = db_controller
        self.accent = document_color(db_controller.get_setting("document_color"))
        self.styles = _styles(self.accent)

    def _p(self, text: str, style: str = "body") -> Paragraph:
        """Paragraph of already escaped markup."""
        return Paragraph(text, self.styles[style])

    # --- Page decoration ---
    def _letter(self, title: str, seller: dict, recipient: dict, info: list, draft: bool = False) -> _Letter:
        logo = paths.resolve(self.db_controller.get_setting("logo_path"))
        return _Letter(title, seller, recipient, [(label, value) for label, value in info if value], self.accent,
                       logo if logo and os.path.isfile(logo) else None, draft, self.styles)

    @staticmethod
    def _seller_name(seller: dict) -> str:
        return seller.get("company_name") or f"{seller.get('first_name') or ''} {seller.get('last_name') or ''}".strip()

    @staticmethod
    def _contact_person(seller: dict) -> str:
        return f"{seller.get('first_name') or ''} {seller.get('last_name') or ''}".strip()

    def _draw_watermark(self, c, letter: _Letter):
        if not letter.draft:
            return
        c.saveState()
        c.setFont(FONT_BOLD, 96)
        c.setFillColor(WATERMARK)
        c.translate(PAGE_WIDTH / 2, PAGE_HEIGHT / 2)
        c.rotate(35)
        c.drawCentredString(0, -30, "ENTWURF")
        c.restoreState()

    def _draw_brand(self, c, letter: _Letter):
        """Logo, or the company name as word mark, in the top right corner."""
        right, top = PAGE_WIDTH - RIGHT, PAGE_HEIGHT - 14 * mm
        if letter.logo:
            try:
                image = Image(letter.logo)
                image._restrictSize(60 * mm, 24 * mm)
                image.drawOn(c, right - image.drawWidth, top - image.drawHeight)
                return
            except Exception:
                pass # unreadable image: the name is shown instead
        name = Paragraph(_markup(self._seller_name(letter.seller)),
                         ParagraphStyle("brand", fontName=FONT_BOLD, fontSize=17, leading=21, alignment=TA_RIGHT,
                                        textColor=colors.HexColor(letter.accent)))
        _, height = name.wrap(95 * mm, 30 * mm)
        name.drawOn(c, right - 95 * mm, top - height)

    def _draw_address(self, c, letter: _Letter):
        s = letter.styles
        seller = letter.seller
        # Return address in the window, above the recipient (DIN 5008 form B: address field 45 mm from the top)
        sender = " · ".join(v for v in (self._seller_name(seller), seller.get("address"),
                                         f"{seller.get('postal_code') or ''} {seller.get('city') or ''}".strip()) if v)
        sender_line = Paragraph(_markup(sender), s["sender"])
        _, height = sender_line.wrap(85 * mm, 10 * mm)
        y = PAGE_HEIGHT - 50 * mm
        sender_line.drawOn(c, LEFT, y)
        c.setStrokeColor(RULE_STRONG)
        c.setLineWidth(0.4)
        c.line(LEFT, y - 1.2 * mm, LEFT + 80 * mm, y - 1.2 * mm)

        recipient = letter.recipient
        lines = [recipient.get("name"), recipient.get("address"),
                 f"{recipient.get('postal_code') or ''} {recipient.get('city') or ''}".strip()]
        country = (recipient.get("country") or "DE").upper()
        if country != "DE":
            lines.append(COUNTRY_NAMES.get(country, country).upper())
        block = Paragraph("<br/>".join(_markup(line) for line in lines if line), s["address"])
        _, height = block.wrap(85 * mm, 40 * mm)
        block.drawOn(c, LEFT, PAGE_HEIGHT - 56 * mm - height)

    def _draw_info(self, c, letter: _Letter):
        s = letter.styles
        rows = [[Paragraph(_markup(label), s["label"]), Paragraph(_markup(value), s["value"])] for label, value in letter.info]
        if not rows:
            return
        table = Table(rows, colWidths=[30 * mm, PAGE_WIDTH - RIGHT - INFO_LEFT - 30 * mm])
        table.setStyle(_table_style([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                   ("TOPPADDING", (0, 0), (-1, -1), 0.6), ("BOTTOMPADDING", (0, 0), (-1, -1), 0.6),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        _, height = table.wrap(PAGE_WIDTH - RIGHT - INFO_LEFT, 50 * mm)
        table.drawOn(c, INFO_LEFT, PAGE_HEIGHT - 50 * mm - height + 3 * mm)

    @staticmethod
    def _draw_marks(c):
        # Fold marks (DIN 5008 form B: 105 and 210 mm) and the punch mark in the middle of the page
        c.setStrokeColor(MARKS)
        c.setLineWidth(0.35)
        for y, length in ((105 * mm, 4 * mm), (210 * mm, 4 * mm), (PAGE_HEIGHT / 2, 6 * mm)):
            c.line(5 * mm, PAGE_HEIGHT - y, 5 * mm + length, PAGE_HEIGHT - y)

    def _first_page(self, letter: _Letter):
        def draw(c, doc):
            c.saveState()
            self._draw_watermark(c, letter)
            self._draw_brand(c, letter)
            self._draw_address(c, letter)
            self._draw_info(c, letter)
            self._draw_marks(c)
            c.restoreState()
        return draw

    def _later_page(self, letter: _Letter):
        def draw(c, doc):
            c.saveState()
            self._draw_watermark(c, letter)
            c.setFont(FONT, 8)
            c.setFillColor(MUTED)
            c.drawString(LEFT, PAGE_HEIGHT - 15 * mm, letter.title)
            c.setStrokeColor(RULE)
            c.setLineWidth(0.5)
            c.line(LEFT, PAGE_HEIGHT - 17.5 * mm, PAGE_WIDTH - RIGHT, PAGE_HEIGHT - 17.5 * mm)
            c.restoreState()
        return draw

    def _footer_columns(self, letter: _Letter) -> list:
        seller = letter.seller
        name = self._seller_name(seller)
        columns = [
            [name, seller.get("address"), f"{seller.get('postal_code') or ''} {seller.get('city') or ''}".strip()],
            ["Kontakt", self._contact_person(seller) if seller.get("company_name") else "",
             f"Tel. {seller['phone']}" if seller.get("phone") else "", seller.get("email")],
            ["Bankverbindung", seller.get("bank_name"), f"IBAN {_iban(seller['iban'])}" if seller.get("iban") else "",
             f"BIC {seller['bic']}" if seller.get("bic") else ""],
            ["Steuern", f"Steuernr. {seller['tax_id']}" if seller.get("tax_id") else "",
             f"USt-IdNr. {seller['vat_id']}" if seller.get("vat_id") else ""],
        ]
        s = letter.styles
        cells = []
        for column in columns:
            head, *lines = column
            lines = [line for line in lines if line]
            if not lines and head != name:
                cells.append("")
                continue
            text = f"<font name='{FONT_BOLD}' color='#1F2937'>{_markup(head)}</font>" + "".join(f"<br/>{_markup(line)}" for line in lines)
            cells.append(Paragraph(text, s["footer"]))
        return cells

    def _draw_footer(self, c, letter: _Letter, page_count: int):
        c.saveState()
        c.setStrokeColor(RULE)
        c.setLineWidth(0.5)
        c.line(LEFT, 27 * mm, PAGE_WIDTH - RIGHT, 27 * mm)
        widths = [44 * mm, 41 * mm, 47 * mm, 33 * mm]
        table = Table([self._footer_columns(letter)], colWidths=widths)
        table.setStyle(_table_style([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                                   ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        _, height = table.wrap(CONTENT_WIDTH, 20 * mm)
        table.drawOn(c, LEFT, 24.5 * mm - height)
        c.setFont(FONT, 7)
        c.setFillColor(MUTED)
        c.drawRightString(PAGE_WIDTH - RIGHT, 9 * mm, f"Seite {c.getPageNumber()} von {page_count}")
        c.restoreState()

    def _build(self, target, letter: _Letter, elements: list):
        doc = BaseDocTemplate(target, pagesize=A4, leftMargin=LEFT, rightMargin=RIGHT, topMargin=LATER_TOP,
                              bottomMargin=BOTTOM, title=letter.title, author=self._seller_name(letter.seller), creator="Schalk")
        frame = dict(leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        first = Frame(LEFT, BOTTOM, CONTENT_WIDTH, PAGE_HEIGHT - FIRST_TOP - BOTTOM, id="first", **frame)
        later = Frame(LEFT, BOTTOM, CONTENT_WIDTH, PAGE_HEIGHT - LATER_TOP - BOTTOM, id="later", **frame)
        doc.addPageTemplates([
            PageTemplate("first", [first], onPage=self._first_page(letter), autoNextPageTemplate="later"),
            PageTemplate("later", [later], onPage=self._later_page(letter)),
        ])
        doc.build(elements, canvasmaker=_numbered_canvas(lambda c, count: self._draw_footer(c, letter, count)))

    # --- Content blocks ---
    def _title(self, title: str, number: str = "") -> list:
        text = escape(title)
        if number:
            text += f" <font name='{FONT}' size='12' color='#6B7280'>{escape(number)}</font>"
        return [self._p(text, "title"), Spacer(1, 5 * mm)]

    def _text(self, *paragraphs: str) -> list:
        elements = []
        for paragraph in paragraphs:
            elements += [self._p(_markup(paragraph)), Spacer(1, 2.5 * mm)]
        return elements

    def _items_table(self, items) -> Table:
        rows = [[self._p("Pos.", "head"), self._p("Bezeichnung", "head"), self._p("Menge", "head_right"),
                 self._p("Einzelpreis", "head_right"), self._p("USt.", "head_right"), self._p("Gesamt", "head_right")]]
        for i, item in enumerate(items, 1):
            description = [self._p(_markup(item.title), "cell_bold")]
            if item.description:
                description.append(self._p(_markup(item.description), "cell_muted"))
            if item.discount_percent:
                description.append(self._p(f"abzgl. {fmt_number(item.discount_percent)} % Rabatt", "cell_muted"))
            rows.append([
                self._p(str(i), "cell"),
                description,
                self._p(_markup(f"{fmt_number(item.quantity)} {item.unit}"), "cell_right"),
                self._p(fmt_price(item.unit_price), "cell_right"),
                self._p(format_rate(item.tax_percent), "cell_right"),
                self._p(fmt_money(item.total_price), "cell_right"),
            ])
        # splitInRow: a position with a very long description continues on the next page
        table = Table(rows, colWidths=[10 * mm, 71 * mm, 26 * mm, 23 * mm, 13 * mm, 22 * mm], repeatRows=1, splitInRow=1)
        table.setStyle(_table_style([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (0, -1), 0), ("RIGHTPADDING", (-1, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
            ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor(self.accent)),
            ("LINEBELOW", (0, 1), (-1, -2), 0.4, RULE),
            ("LINEBELOW", (0, -1), (-1, -1), 0.8, RULE_STRONG),
        ]))
        return table

    def _totals(self, items, net_amount, gross_amount, credit_amount=0.0, credit_desc="") -> Table:
        rows = []
        if credit_amount:
            rows += [("Summe netto", fmt_money(net_amount)), (f"abzgl. {credit_desc or 'Gutschrift'}", fmt_money(-credit_amount))]
        # One line per tax rate (§ 14 Abs. 4 Nr. 8 UStG); 0 % is explained by the exemption note
        taxes = [(f"zzgl. {format_rate(rate)} USt. auf {fmt_money(basis)}", fmt_money(tax))
                 for rate, (basis, tax) in sorted(tax_breakdown(items, credit_amount).items(), reverse=True) if rate]
        if taxes:
            rows += [("Summe netto nach Abzug" if credit_amount else "Summe netto", fmt_money(net_amount - credit_amount))] + taxes
        # Without VAT (e.g. small business, § 19 UStG) and without credit the total is all there is
        data = [[self._p(_markup(label), "total"), self._p(value, "total")] for label, value in rows]
        data.append([self._p("Gesamtbetrag", "grand_total"), self._p(fmt_money(gross_amount), "grand_total")])
        table = Table(data, colWidths=[62 * mm, 28 * mm], hAlign="RIGHT")
        style = [("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                 ("TOPPADDING", (0, 0), (-1, -1), 1.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5)]
        if rows:
            style += [("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor(self.accent)), ("TOPPADDING", (0, -1), (-1, -1), 6)]
        table.setStyle(_table_style(style))
        return table

    def _note(self, text: str) -> Table:
        """Highlighted note, e.g. the reason for a VAT exemption."""
        table = Table([[self._p(_markup(text))]], colWidths=[CONTENT_WIDTH])
        table.setStyle(_table_style([
            ("BACKGROUND", (0, 0), (-1, -1), NOTE_BACKGROUND),
            ("LINEBEFORE", (0, 0), (0, -1), 2, colors.HexColor(self.accent)),
            ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        return table

    def _closing(self, seller: dict, *texts: str) -> list:
        """The last paragraphs and the greeting; kept together, so the greeting never stands alone on a page."""
        signature = self._contact_person(seller) or self._seller_name(seller)
        lines = ["Mit freundlichen Grüßen", "", _markup(signature)]
        if seller.get("company_name") and signature != seller["company_name"]:
            lines.append(_markup(seller["company_name"]))
        return [KeepTogether(self._text(*texts) + [Spacer(1, 3 * mm), self._p("<br/>".join(lines))])]

    @staticmethod
    def _buyer_from_customer(customer) -> dict:
        return {"name": customer.display_name, "address": customer.address, "postal_code": customer.postal_code,
                "city": customer.city, "country": customer.country, "vat_id": customer.vat_id,
                "buyer_reference": customer.buyer_reference}

    def _payment_text(self, invoice: Invoice, seller: dict) -> str:
        terms = self.db_controller.payment_terms_of(invoice)
        deadline = f" bis zum {_date(self.db_controller.get_due_date(invoice))}" if terms > 0 else ""
        account = " auf das unten genannte Konto" if seller.get("iban") else ""
        return (f"Bitte überweisen Sie den Gesamtbetrag von {fmt_money(invoice.gross_amount)} {payment_terms_text(terms)} "
                f"ohne Abzug{deadline} unter Angabe der Rechnungsnummer{account}.")

    # --- Documents ---
    def render_invoice(self, invoice: Invoice) -> bytes:
        c = self.db_controller
        seller, buyer = c.seller_of(invoice), c.buyer_of(invoice)
        draft = c.is_draft_number(invoice.invoice_number)
        storno = bool(invoice.cancels_invoice_id)
        original = c.get_invoice_header(invoice.cancels_invoice_id) if storno else None
        number = "" if draft else invoice.invoice_number
        title = "Rechnungsentwurf" if draft else "Stornorechnung" if storno else "Rechnung"

        info = [("Rechnungsnr.", number or "Entwurf"), ("Rechnungsdatum", _date(invoice.invoice_date))]
        if invoice.delivery_end_date:
            info.append(("Leistungszeitraum", _period(invoice.delivery_date, invoice.delivery_end_date)))
        else:
            info.append(("Leistungsdatum", _date(invoice.delivery_date)))
        if original:
            info += [("Storno zu", original.invoice_number), ("Rechnung vom", _date(original.invoice_date))]
        elif not storno:
            info.append(("Zahlbar bis", _date(c.get_due_date(invoice))))
        info += [("Kundennr.", str(invoice.customer_id)), ("Ihre USt-IdNr.", buyer.get("vat_id")),
                 ("Ihre Referenz", buyer.get("buyer_reference")), ("Ansprechpartner", self._contact_person(seller))]
        letter = self._letter(f"{title} {number}".strip(), seller, buyer, info, draft)

        elements = self._title(title, number)
        if storno:
            reference = f" Nr. {original.invoice_number} vom {_date(original.invoice_date)}" if original else ""
            elements += self._text("Sehr geehrte Damen und Herren,",
                                   f"hiermit stornieren wir unsere Rechnung{reference} vollständig:")
        else:
            elements += self._text("Sehr geehrte Damen und Herren,",
                                   "vielen Dank für Ihren Auftrag. Wir berechnen Ihnen folgende Leistungen:")
        elements += [Spacer(1, 1 * mm), self._items_table(invoice.items), Spacer(1, 4 * mm),
                     self._totals(invoice.items, invoice.net_amount, invoice.gross_amount,
                                  invoice.credit_amount or 0.0, invoice.credit_desc),
                     Spacer(1, 7 * mm)]
        if invoice.tax_exemption_reason:
            elements += [self._note(f"Hinweis: {invoice.tax_exemption_reason}"), Spacer(1, 5 * mm)]
        if storno:
            elements += self._closing(seller, "Mit dieser Stornorechnung wird die oben genannte Rechnung vollständig "
                                              "aufgehoben. Bereits gezahlte Beträge werden verrechnet bzw. erstattet.")
        else:
            elements += self._closing(seller, self._payment_text(invoice, seller))

        buffer = BytesIO()
        self._build(buffer, letter, elements)
        return buffer.getvalue()

    def generate_invoice_pdf(self, invoice: Invoice, filepath: str):
        with open(filepath, "wb") as f:
            f.write(self.render_invoice(invoice))

    def generate_quote_pdf(self, quote, filepath: str):
        c = self.db_controller
        seller = c.current_seller()
        buyer = self._buyer_from_customer(c.get_customer(quote.customer_id))
        valid_until = quote.quote_date + datetime.timedelta(days=14)
        info = [("Angebotsnr.", quote.quote_number), ("Angebotsdatum", _date(quote.quote_date)),
                ("Gültig bis", _date(valid_until)), ("Kundennr.", str(quote.customer_id)),
                ("Ansprechpartner", self._contact_person(seller))]
        letter = self._letter(f"Angebot {quote.quote_number}", seller, buyer, info)

        elements = self._title("Angebot", quote.quote_number)
        elements += self._text("Sehr geehrte Damen und Herren,",
                               "vielen Dank für Ihre Anfrage. Gerne bieten wir Ihnen folgende Leistungen an:")
        elements += [Spacer(1, 1 * mm), self._items_table(quote.items), Spacer(1, 4 * mm),
                     self._totals(quote.items, quote.net_amount, quote.gross_amount), Spacer(1, 7 * mm)]
        if quote.tax_exemption_reason:
            elements += [self._note(f"Hinweis: {quote.tax_exemption_reason}"), Spacer(1, 5 * mm)]
        elements += self._closing(seller, f"Dieses Angebot ist gültig bis zum {_date(valid_until)}. Wir freuen uns auf "
                                          "Ihren Auftrag und stehen für Rückfragen gerne zur Verfügung.")
        self._build(filepath, letter, elements)

    def generate_reminder_pdf(self, invoice: Invoice, filepath: str, level: int = 1):
        c = self.db_controller
        seller = c.current_seller()
        # Reminders go to the customer's current address
        buyer = self._buyer_from_customer(c.get_customer(invoice.customer_id))
        today = datetime.date.today()
        due = c.get_due_date(invoice)
        info = [("Datum", _date(today)), ("Rechnungsnr.", invoice.invoice_number),
                ("Rechnungsdatum", _date(invoice.invoice_date)), ("Kundennr.", str(invoice.customer_id)),
                ("Ansprechpartner", self._contact_person(seller))]
        letter = self._letter(f"{level}. Mahnung {invoice.invoice_number}", seller, buyer, info)

        reference = f"Rechnung Nr. {invoice.invoice_number} vom {_date(invoice.invoice_date)}"
        if level == 1:
            texts = [f"leider konnten wir bis heute keinen Zahlungseingang für unsere {reference} feststellen.",
                     "Wir bitten Sie, den fälligen Betrag umgehend, spätestens jedoch innerhalb der nächsten 14 Tage, "
                     "auf unser unten genanntes Konto zu überweisen."]
        elif level == 2:
            texts = [f"trotz unserer ersten Zahlungserinnerung konnten wir bisher noch keinen Zahlungseingang für unsere "
                     f"{reference} feststellen.",
                     "Wir bitten Sie nun nachdrücklich, den ausstehenden Betrag innerhalb der nächsten 14 Tage zu begleichen."]
        else:
            texts = [f"hiermit fordern wir Sie letztmalig auf, unsere {reference} zu begleichen.",
                     "Sollte der Betrag nicht innerhalb von 14 Tagen auf unserem Konto eingehen, sehen wir uns gezwungen, "
                     "rechtliche Schritte einzuleiten."]

        elements = self._title(f"{level}. Mahnung")
        elements += self._text("Sehr geehrte Damen und Herren,", texts[0])
        # Only what is still open is demanded
        outstanding = c.outstanding_amount(invoice)
        rows = [
            [self._p("Rechnung", "head"), self._p("Rechnungsdatum", "head"), self._p("Fällig seit", "head"),
             self._p("Offener Betrag", "head_right")],
            [self._p(_markup(invoice.invoice_number), "cell"), self._p(_date(invoice.invoice_date), "cell"),
             self._p(_date(due), "cell"), self._p(fmt_money(outstanding), "cell_bold_right")],
        ]
        if invoice.paid_amount:
            rows.insert(1, [self._p("Rechnungsbetrag", "cell"), self._p("", "cell"), self._p("", "cell"),
                            self._p(fmt_money(invoice.gross_amount), "cell_right")])
            rows.insert(2, [self._p("abzgl. bereits gezahlt", "cell"), self._p("", "cell"), self._p("", "cell"),
                            self._p(fmt_money(-invoice.paid_amount), "cell_right")])
        overview = Table(rows, colWidths=[50 * mm, 40 * mm, 40 * mm, 35 * mm])
        overview.setStyle(_table_style([
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor(self.accent)),
            ("LINEBELOW", (0, -1), (-1, -1), 0.8, RULE_STRONG),
        ]))
        elements += [Spacer(1, 1 * mm), overview, Spacer(1, 6 * mm)]
        elements += self._closing(seller, *texts[1:], "Sollte sich Ihre Zahlung mit diesem Schreiben überschnitten haben, "
                                                       "betrachten Sie diese Mahnung bitte als gegenstandslos.")
        self._build(filepath, letter, elements)
