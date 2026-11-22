"""
GoBD data export for a tax audit (Datenträgerüberlassung, Z3; GoBD Rz. 165 ff.).

Writes one ZIP file with every tax-relevant table as a CSV file and an index.xml in the description standard
of the German tax authorities (GDPdU "Beschreibungsstandard", DTD gdpdu-01-08-2002), so audit software
such as IDEA can import the data without manual work. The archived documents (issued invoices as ZUGFeRD PDF,
receipts, received invoices) can be added in the folder "belege".

CSV: UTF-8, separator ";", decimal comma, dates DD.MM.YYYY, time stamps ISO 8601 (UTC), first line = column names.
"""
import csv
import io
import os
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable, List, Optional
from xml.sax.saxutils import escape
from src.models.database import CashbookEntry, Customer, DocumentHistory, IncomingInvoice, Invoice, InvoiceItem, Payment
from src.utils import paths
from src.version import APP_NAME, APP_VERSION

# NUMBER: amounts with 2 decimals; DECIMAL4: quantities, prices and percentages with 4 decimals
TEXT, NUMBER, DECIMAL4, DATE, INTEGER = "text", "number", "decimal4", "date", "integer"


@dataclass
class _Column:
    name: str
    description: str
    kind: str
    value: Callable


@dataclass
class _Table:
    file: str
    name: str
    description: str
    model: object
    columns: List[_Column]
    date_of: Optional[Callable] = None # rows outside the chosen year are left out
    foreign_keys: List[tuple] = field(default_factory=list) # (column, referenced table name)


def _c(name, description, kind=TEXT, value=None):
    return _Column(name, description, kind, value or (lambda r, n=name: getattr(r, n)))


def _paid_column():
    return _c("bezahlt", "Summe der erfassten Zahlungen", NUMBER, lambda r: r.paid_amount or 0.0)


TABLES = [
    _Table("rechnungen.csv", "Rechnungen", "Ausgangsrechnungen (festgeschrieben) mit eingefrorenen Empfängerdaten",
           Invoice, [
               _c("id", "Interne Nummer", INTEGER),
               _c("rechnungsnummer", "Rechnungsnummer (§ 14 Abs. 4 Nr. 4 UStG)", TEXT, lambda r: r.invoice_number),
               _c("rechnungsdatum", "Ausstellungsdatum", DATE, lambda r: r.invoice_date),
               _c("leistung_von", "Leistungsdatum bzw. Beginn des Leistungszeitraums", DATE, lambda r: r.delivery_date),
               _c("leistung_bis", "Ende des Leistungszeitraums", DATE, lambda r: r.delivery_end_date),
               _c("kunde_id", "Kundennummer", INTEGER, lambda r: r.customer_id),
               _c("kunde_name", "Name des Empfängers", TEXT, lambda r: r.customer_name),
               _c("kunde_anschrift", "Anschrift des Empfängers", TEXT,
                  lambda r: ", ".join(filter(None, [r.customer_address, r.customer_postal_code, r.customer_city]))),
               _c("kunde_land", "Land des Empfängers", TEXT, lambda r: r.customer_country),
               _c("kunde_ustid", "USt-IdNr. des Empfängers", TEXT, lambda r: r.customer_vat_id),
               _c("netto", "Summe der Positionen netto", NUMBER, lambda r: r.net_amount),
               _c("nachlass", "Nachlass / Gutschrift netto", NUMBER, lambda r: r.credit_amount or 0.0),
               _c("umsatzsteuer", "Umsatzsteuer", NUMBER, lambda r: r.tax_amount),
               _c("brutto", "Rechnungsbetrag brutto", NUMBER, lambda r: r.gross_amount),
               _c("steuerbefreiung", "Grund der Steuerbefreiung", TEXT, lambda r: r.tax_exemption_reason),
               _c("zahlungsziel_tage", "Zahlungsziel in Tagen", INTEGER, lambda r: r.payment_terms_days),
               _c("status", "Status", TEXT),
               _paid_column(),
               _c("bezahlt_am", "Datum des Zahlungseingangs", DATE, lambda r: r.paid_at if r.status == "Bezahlt" else None),
               _c("storno_zu_id", "Stornorechnung zu Rechnung (id)", INTEGER, lambda r: r.cancels_invoice_id),
               _c("festgeschrieben_am", "Zeitpunkt der Festschreibung (UTC)", TEXT, lambda r: _timestamp(r.finalized_at)),
               _c("hash", "SHA-256-Hash-Kette", TEXT, lambda r: r.hash_chain),
               _c("pdf_datei", "Archivierte Rechnung (Ordner belege)", TEXT, lambda r: _document_name(r.pdf_path)),
               _c("pdf_sha256", "SHA-256 der archivierten Rechnung", TEXT, lambda r: r.pdf_hash),
           ], date_of=lambda r: r.invoice_date),
    _Table("rechnungspositionen.csv", "Rechnungspositionen", "Positionen der Ausgangsrechnungen", InvoiceItem, [
        _c("id", "Interne Nummer", INTEGER),
        _c("rechnung_id", "Rechnung (id)", INTEGER, lambda r: r.invoice_id),
        _c("bezeichnung", "Bezeichnung", TEXT, lambda r: r.title),
        _c("beschreibung", "Beschreibung", TEXT, lambda r: r.description),
        _c("menge", "Menge", DECIMAL4, lambda r: r.quantity),
        _c("einheit", "Einheit", TEXT, lambda r: r.unit),
        _c("einzelpreis", "Einzelpreis netto", DECIMAL4, lambda r: r.unit_price),
        _c("rabatt_prozent", "Rabatt in Prozent", DECIMAL4, lambda r: r.discount_percent or 0.0),
        _c("steuersatz", "Umsatzsteuersatz in Prozent", NUMBER, lambda r: r.tax_percent),
        _c("gesamt_netto", "Positionsbetrag netto", NUMBER, lambda r: r.total_price),
    ], foreign_keys=[("rechnung_id", "Rechnungen")]),
    _Table("zahlungen.csv", "Zahlungen", "Zahlungseingänge zu Ausgangsrechnungen (negativ = Rückbuchung)", Payment, [
        _c("id", "Interne Nummer", INTEGER),
        _c("rechnung_id", "Rechnung (id)", INTEGER, lambda r: r.invoice_id),
        _c("zahlungsdatum", "Datum des Zahlungseingangs", DATE, lambda r: r.payment_date),
        _c("betrag", "Betrag", NUMBER, lambda r: r.amount),
        _c("hinweis", "Hinweis", TEXT, lambda r: r.note),
        _c("benutzer", "Erfasst von", TEXT, lambda r: r.user),
        _c("erfasst_am", "Zeitpunkt der Erfassung (UTC)", TEXT, lambda r: _timestamp(r.created_at)),
    ], date_of=lambda r: r.payment_date, foreign_keys=[("rechnung_id", "Rechnungen")]),
    _Table("kassenbuch.csv", "Kassenbuch", "Kassenbuch (festgeschriebene Buchungen und Entwürfe)", CashbookEntry, [
        _c("id", "Interne Nummer", INTEGER),
        _c("belegnummer", "Belegnummer (leer = Entwurf)", TEXT, lambda r: r.receipt_number),
        _c("datum", "Buchungsdatum", DATE, lambda r: r.entry_date),
        _c("art", "Buchungsart", TEXT, lambda r: r.entry_type),
        _c("betrag", "Betrag (Einnahme positiv, Entnahme negativ)", NUMBER,
           lambda r: r.amount if r.entry_type == "Einnahme" else -r.amount),
        _c("buchungstext", "Buchungstext", TEXT, lambda r: r.description),
        _c("kategorie", "Kategorie", TEXT, lambda r: r.category),
        _c("steuersatz", "Umsatzsteuersatz in Prozent", NUMBER, lambda r: r.tax_percent or 0.0),
        _c("storno", "Storno-Gegenbuchung (1 = ja)", INTEGER, lambda r: int(bool(r.is_storno))),
        _c("storno_zu_id", "Storniert Buchung (id)", INTEGER, lambda r: r.storno_of_id),
        _c("festgeschrieben_am", "Zeitpunkt der Festschreibung", TEXT, lambda r: _timestamp(r.finalized_at)),
        _c("hash", "SHA-256-Hash-Kette", TEXT, lambda r: r.hash_chain),
        _c("beleg_datei", "Beleg (Ordner belege)", TEXT, lambda r: _document_name(r.attachment_path)),
        _c("beleg_sha256", "SHA-256 des Belegs", TEXT, lambda r: r.attachment_hash),
    ], date_of=lambda r: r.entry_date),
    _Table("eingangsrechnungen.csv", "Eingangsrechnungen", "Erhaltene Rechnungen (Lieferanten und Sonstige)", IncomingInvoice, [
        _c("id", "Interne Nummer", INTEGER),
        _c("art", "Lieferant oder Sonstige", TEXT, lambda r: r.invoice_type),
        _c("datum", "Rechnungsdatum", DATE, lambda r: r.date),
        _c("lieferant", "Rechnungssteller", TEXT, lambda r: r.supplier_name),
        _c("rechnungsnummer", "Rechnungsnummer des Lieferanten", TEXT, lambda r: r.invoice_number),
        _c("beschreibung", "Beschreibung", TEXT, lambda r: r.description),
        _c("betrag", "Betrag brutto", NUMBER, lambda r: r.amount),
        _c("format", "Format (E-Rechnung)", TEXT, lambda r: r.einvoice_format),
        _c("storniert_am", "Storniert am (UTC)", TEXT, lambda r: _timestamp(r.cancelled_at)),
        _c("datei", "Originaldatei (Ordner belege)", TEXT, lambda r: _document_name(r.file_path)),
        _c("sha256", "SHA-256 der Originaldatei", TEXT, lambda r: r.file_hash),
        _c("erfasst_am", "Zeitpunkt der Erfassung (UTC)", TEXT, lambda r: _timestamp(r.created_at)),
    ], date_of=lambda r: r.date),
    _Table("kunden.csv", "Kunden", "Kundenstamm (aktueller Stand)", Customer, [
        _c("id", "Kundennummer", INTEGER),
        _c("firma", "Firma", TEXT, lambda r: r.company_name),
        _c("vorname", "Vorname", TEXT, lambda r: r.first_name),
        _c("nachname", "Nachname", TEXT, lambda r: r.last_name),
        _c("strasse", "Straße", TEXT, lambda r: r.address),
        _c("plz", "PLZ", TEXT, lambda r: r.postal_code),
        _c("ort", "Ort", TEXT, lambda r: r.city),
        _c("land", "Land", TEXT, lambda r: r.country),
        _c("ustid", "USt-IdNr.", TEXT, lambda r: r.vat_id),
        _c("kaeuferreferenz", "Käuferreferenz / Leitweg-ID", TEXT, lambda r: r.buyer_reference),
    ]),
    _Table("verlauf.csv", "Verlauf", "Protokoll aller Aktionen (Hash-Kette)", DocumentHistory, [
        _c("id", "Laufende Nummer", INTEGER),
        _c("zeitpunkt", "Zeitpunkt (UTC)", TEXT, lambda r: _timestamp(r.timestamp)),
        _c("benutzer", "Windows-Benutzer", TEXT, lambda r: r.user),
        _c("objekt", "Art des Datensatzes", TEXT, lambda r: r.document_type),
        _c("objekt_id", "Datensatz (id)", INTEGER, lambda r: r.document_id),
        _c("aktion", "Aktion", TEXT, lambda r: r.action),
        _c("hash", "SHA-256-Hash-Kette", TEXT, lambda r: r.hash_chain),
    ]),
]


def _timestamp(value) -> str:
    return value.replace(tzinfo=None).isoformat(timespec="seconds") if value else ""


def _document_name(stored: str) -> str:
    return os.path.basename(stored) if stored else ""


def _format(value, kind: str) -> str:
    if value is None or value == "":
        return ""
    if kind == DATE:
        return value.strftime("%d.%m.%Y") if isinstance(value, (date, datetime)) else str(value)
    if kind in (NUMBER, DECIMAL4):
        return f"{float(value) + 0.0:.{2 if kind == NUMBER else 4}f}".replace(".", ",")
    if kind == INTEGER:
        return str(int(value))
    return str(value)


def _rows(session, table: _Table, year: Optional[int]) -> list:
    records = session.query(table.model).order_by(table.model.id).all()
    if table.model is Invoice:
        # Drafts are not issued invoices; they are neither numbered nor tax-relevant
        records = [r for r in records if r.finalized_at]
    if year is not None and table.date_of:
        records = [r for r in records if table.date_of(r) and table.date_of(r).year == year]
    return records


def _csv(table: _Table, records: list) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", quotechar='"', quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow([c.name for c in table.columns])
    for record in records:
        # Line breaks inside a text would end the record for the audit software
        writer.writerow([_format(c.value(record), c.kind).replace("\r", " ").replace("\n", " ") for c in table.columns])
    return buffer.getvalue().encode("utf-8")


def _column_xml(column: _Column) -> str:
    kinds = {
        TEXT: "<AlphaNumeric/>",
        NUMBER: "<Numeric><Accuracy>2</Accuracy></Numeric>",
        DECIMAL4: "<Numeric><Accuracy>4</Accuracy></Numeric>",
        INTEGER: "<Numeric/>",
        DATE: "<Date><Format>DD.MM.YYYY</Format></Date>",
    }
    return f"<Name>{escape(column.name)}</Name><Description>{escape(column.description)}</Description>{kinds[column.kind]}"


def index_xml(seller: dict, year: Optional[int]) -> str:
    """Description of all tables (GDPdU Beschreibungsstandard)."""
    period = ""
    if year is not None:
        period = (f"<Validity><Range><From>01.01.{year}</From><To>31.12.{year}</To></Range>"
                  "<Format>DD.MM.YYYY</Format></Validity>")
    tables = []
    for table in TABLES:
        key, *columns = table.columns
        foreign = "".join(f"<ForeignKey><Name>{escape(column)}</Name><References>{escape(ref)}</References></ForeignKey>"
                          for column, ref in table.foreign_keys)
        tables.append(
            f"<Table><URL>{table.file}</URL><Name>{escape(table.name)}</Name><Description>{escape(table.description)}</Description>"
            f"{period if table.date_of else ''}<UTF8/><DecimalSymbol>,</DecimalSymbol><DigitGroupingSymbol>.</DigitGroupingSymbol>"
            "<Range><From>2</From></Range>" # the first line holds the column names
            '<VariableLength><ColumnDelimiter>;</ColumnDelimiter><RecordDelimiter>&#13;&#10;</RecordDelimiter>'
            '<TextEncapsulator>"</TextEncapsulator>'
            f"<VariablePrimaryKey>{_column_xml(key)}</VariablePrimaryKey>"
            + "".join(f"<VariableColumn>{_column_xml(c)}</VariableColumn>" for c in columns)
            + f"{foreign}</VariableLength></Table>")
    name = seller.get("company_name") or f"{seller.get('first_name', '')} {seller.get('last_name', '')}".strip()
    location = " ".join(filter(None, [seller.get("address"), seller.get("postal_code"), seller.get("city")]))
    comment = f"Erstellt mit {APP_NAME} {APP_VERSION} am {datetime.now():%d.%m.%Y %H:%M}" + (f", Jahr {year}" if year else ", alle Jahre")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE DataSet SYSTEM "gdpdu-01-08-2002.dtd">\n'
            f"<DataSet><Version>1.0</Version><DataSupplier><Name>{escape(name)}</Name><Location>{escape(location)}</Location>"
            f"<Comment>{escape(comment)}</Comment></DataSupplier><Media><Name>{APP_NAME} GoBD-Datenexport</Name>"
            + "".join(tables) + "</Media></DataSet>\n")


README = """GoBD-Datenexport (Datenträgerüberlassung)

Die Tabellen liegen als CSV-Dateien vor (UTF-8, Trennzeichen Semikolon, Dezimalkomma, Datum TT.MM.JJJJ,
erste Zeile = Spaltennamen). index.xml beschreibt sie im Beschreibungsstandard der Finanzverwaltung (GDPdU)
und kann von Prüfsoftware wie IDEA direkt eingelesen werden. Zeitpunkte sind in UTC angegeben.

Im Ordner "belege" liegen, falls mit exportiert, die archivierten Dokumente unverändert: ausgestellte Rechnungen
(ZUGFeRD-PDF mit eingebettetem XML), Kassenbelege und erhaltene Rechnungen. Ihr SHA-256-Hash steht jeweils in
der zugehörigen Tabelle und lässt sich z. B. mit "certutil -hashfile <Datei> SHA256" nachprüfen.
"""


def export_gobd(controller, target: str, year: Optional[int] = None, include_documents: bool = True) -> dict:
    """
    Writes the export ZIP. year=None exports all years. Returns {table name: number of rows}.
    The ZIP is written to a temporary name first, so an interrupted export never leaves a half file behind.
    """
    counts, documents = {}, {}
    temp = target + ".tmp"
    try:
        with zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as zipf:
            with controller.get_session() as session:
                for table in TABLES:
                    records = _rows(session, table, year)
                    if table.model is InvoiceItem:
                        invoice_ids = {r.id for r in _rows(session, TABLES[0], year)}
                        records = [r for r in records if r.invoice_id in invoice_ids]
                    zipf.writestr(table.file, _csv(table, records))
                    counts[table.name] = len(records)
                    if include_documents:
                        for record in records:
                            for attribute in ("pdf_path", "attachment_path", "file_path"):
                                stored = getattr(record, attribute, None)
                                if stored:
                                    documents[_document_name(stored)] = paths.resolve(stored)
            zipf.writestr("index.xml", index_xml(controller.current_seller(), year))
            zipf.writestr("LIESMICH.txt", README)
            for name, source in sorted(documents.items()):
                if os.path.isfile(source):
                    zipf.write(source, f"belege/{name}")
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.remove(temp)
    counts["Belege"] = len(documents)
    return counts
