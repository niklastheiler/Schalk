"""
Reads supplier, invoice number, invoice date and gross amount from the text of a PDF invoice without structured
data (scans with a text layer, invoices from programs without ZUGFeRD). Only a suggestion: the user confirms or
corrects every value in the upload dialog.
"""
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Optional
from pypdf import PdfReader

logger = logging.getLogger(__name__)

PAGES = 3
_MONEY = r"(-?\d{1,3}(?:[.,' ]\d{3})+[.,]\d{2}|-?\d+[.,]\d{2})"
# Labels of the amount to pay, most specific first: "Summe netto" or "Betrag" alone come last
_AMOUNT_LABELS = [
    r"Gesamtbetrag", r"Rechnungsbetrag", r"Endbetrag", r"Zahlbetrag", r"zu zahlen(?:der Betrag)?", r"Bruttobetrag",
    r"(?:Gesamt)?summe\s+brutto", r"Brutto(?:summe)?", r"Total(?:\s+amount)?|Amount\s+due",
]
# Generic labels only count at the start of a line ("Summe: 119,00 €"), not inside a sentence like
# "Leistungen bis zu einem Betrag von 100.000,00 €" of a letter without an amount to pay
_GENERIC_AMOUNT_LABELS = [r"Gesamt", r"Summe", r"Betrag"]
# Amounts that are limits or insured sums, never the amount of an invoice
_NOT_AN_INVOICE_AMOUNT = re.compile(
    r"versicherungssumme|deckungssumme|höchst|maximal|bis\s+zu|selbstbeteiligung|stammkapital|grundkapital|"
    r"kreditlimit|limit", re.IGNORECASE)
_NUMBER_LABEL = (r"(?:Rechnungs?[- ]?(?:nummer|nr\.?|no\.?)|Rechnung\s+(?:Nr\.?|Nummer)|Re\.?-?\s?Nr\.?|"
                 r"Beleg(?:nummer|-?nr\.?)|Invoice\s*(?:No\.?|Number|#))")
_NUMBER_VALUE = r"([A-Za-z0-9][A-Za-z0-9\-/_.]*\d[A-Za-z0-9\-/_]*)"
_DATE_LABELS = [r"Rechnungsdatum", r"Belegdatum", r"Invoice\s+date", r"Datum", r"Date"]
_MONTHS = {"januar": 1, "jänner": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4, "mai": 5, "juni": 6, "juli": 7,
           "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12}
_DATE = (r"(\d{1,2}\.\s?\d{1,2}\.\s?(?:\d{4}|\d{2})(?!\d)|\d{4}-\d{2}-\d{2}|"
         r"\d{1,2}\.\s*(?:" + "|".join(_MONTHS) + r")\s+\d{4})")
# Legal forms that mark a company name
_LEGAL_FORM = re.compile(r"\b(GmbH|mbH|AG|UG|KG|OHG|GbR|e\.\s?K\.|e\.\s?V\.|KGaA|SE|Ltd\.?|Inc\.?|LLC|S\.?A\.?R\.?L\.?|B\.?V\.?)(\b|$)")
# Sender line above the address (DIN 5008): "Firma · Straße 1 · 12345 Ort"
_SENDER_SEPARATORS = re.compile(r"\s+[·•|–-]\s+|\s*[·•|]\s*")


@dataclass
class PdfGuess:
    amount: float = 0.0
    invoice_date: Optional[date] = None
    number: str = ""
    supplier: str = ""


def _to_float(text: str) -> float:
    """1.234,56 / 1,234.56 / 1 234,56 / 1234.56 -> 1234.56 (the last separator is the decimal separator)."""
    text = text.replace(" ", "").replace("'", "")
    decimal = max(text.rfind(","), text.rfind("."))
    return float(re.sub(r"[.,]", "", text[:decimal]) + "." + text[decimal + 1:])


def _parse_date(text: str) -> Optional[date]:
    text = text.strip().lower()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return date.fromisoformat(text)
        match = re.fullmatch(r"(\d{1,2})\.\s*([a-zä]+)\s+(\d{4})", text)
        if match:
            return date(int(match.group(3)), _MONTHS[match.group(2)], int(match.group(1)))
        day, month, year = (int(p) for p in re.split(r"\.\s?", text))
        return date(year + 2000 if year < 100 else year, month, day)
    except (ValueError, KeyError):
        return None


def guess_amount(text: str) -> float:
    """The amount to pay; 0 if none is recognized (the user enters it then)."""
    patterns = [rf"\b(?:{label})[^\d\n-]{{0,40}}(?:\n[^\d\n-]{{0,40}})?{_MONEY}" for label in _AMOUNT_LABELS]
    patterns += [rf"^[ \t]*(?:{label})\b[^\d\n-]{{0,40}}{_MONEY}" for label in _GENERIC_AMOUNT_LABELS]
    for pattern in patterns:
        # Whole words: "Subtotal" is no "Total", "Zwischensumme" no "Summe"
        for match in re.finditer(pattern, text, re.IGNORECASE | re.MULTILINE):
            line_start = text.rfind("\n", 0, match.start()) + 1
            line_end = text.find("\n", match.end())
            if _NOT_AN_INVOICE_AMOUNT.search(text[line_start:line_end if line_end >= 0 else len(text)]):
                continue
            try:
                return _to_float(match.group(1))
            except ValueError:
                continue
    return 0.0


def guess_number(text: str) -> str:
    match = re.search(rf"{_NUMBER_LABEL}[\s:#.]{{0,30}}{_NUMBER_VALUE}", text, re.IGNORECASE)
    if not match:
        # Title like "Rechnung RE-2026-0042"
        match = re.search(rf"\bRechnung\s+{_NUMBER_VALUE}", text)
    return match.group(1).rstrip(".-/") if match else ""


def guess_date(text: str) -> Optional[date]:
    for label in _DATE_LABELS:
        for match in re.finditer(rf"\b{label}\b[^\d\n]{{0,30}}\n?[^\d\n]{{0,10}}{_DATE}", text, re.IGNORECASE):
            value = _parse_date(match.group(1))
            if value:
                return value
    # Otherwise the first date on the invoice (usually in the header)
    for match in re.finditer(_DATE, text, re.IGNORECASE):
        value = _parse_date(match.group(1))
        if value:
            return value
    return None


def _is_own(line: str, own_names: Iterable[str]) -> bool:
    folded = line.casefold()
    return any(name and name.casefold() in folded for name in own_names)


def guess_supplier(text: str, own_names: Iterable[str] = (), author: str = "") -> str:
    """
    The company that issued the invoice. own_names (the user's company and name) are skipped: the address block
    of a received invoice is the user's own address.
    """
    own_names = [n.strip() for n in own_names if n and n.strip()]
    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    # 1. Sender line above the address window (DIN 5008): "Firma · Straße · PLZ Ort"
    for line in lines[:25]:
        parts = [p.strip() for p in _SENDER_SEPARATORS.split(line) if p.strip()]
        # A postal code followed by a town marks the address part, a table row (1 | Bretter | 3 Stück) has none
        name = parts[0] if parts else ""
        if len(parts) >= 3 and re.search(r"\b\d{4,5}\s+[A-ZÄÖÜ]", line) and re.match(r"[^\W\d_]{2}", name) \
                and not _is_own(name, own_names):
            return name[:80]
    # 2. A company name with legal form near the top
    for line in lines[:15]:
        if _LEGAL_FORM.search(line) and len(line) <= 80 and not _is_own(line, own_names):
            return line
    # 3. The author in the PDF properties, if it is not a program name
    if author and not _is_own(author, own_names) and not re.search(r"word|office|pdf|print|writer|acrobat|reportlab|scan",
                                                                    author, re.IGNORECASE):
        return author.strip()[:80]
    # 4. Legal form anywhere (e.g. only in the footer)
    for line in lines:
        if _LEGAL_FORM.search(line) and len(line) <= 80 and not _is_own(line, own_names):
            return line
    return ""


def read_pdf_text(path: str) -> tuple:
    """(text of the first pages, author from the PDF properties); empty if the PDF cannot be read."""
    try:
        reader = PdfReader(path)
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:PAGES])
        return text, str((reader.metadata or {}).get("/Author") or "")
    except Exception:
        logger.info("Text der PDF %s konnte nicht gelesen werden", path, exc_info=True)
        return "", ""


def guess_from_text(text: str, own_names: Iterable[str] = (), author: str = "") -> PdfGuess:
    guess = PdfGuess(amount=guess_amount(text), invoice_date=guess_date(text), number=guess_number(text),
                     supplier=guess_supplier(text, own_names, author))
    if guess.invoice_date and guess.invoice_date > datetime.now().date():
        guess.invoice_date = None # an invoice date in the future is a misreading (e.g. the due date)
    return guess


def guess_from_pdf(path: str, own_names: Iterable[str] = ()) -> PdfGuess:
    """All values that can be found; missing ones stay empty (date: None, amount: 0)."""
    text, author = read_pdf_text(path)
    return guess_from_text(text, own_names, author) if text or author else PdfGuess()
