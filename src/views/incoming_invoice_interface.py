import logging
import os
import re
from datetime import datetime
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QTextBrowser, QVBoxLayout
from pypdf import PdfReader
from qfluentwidgets import (BodyLabel, DoubleSpinBox, FluentIcon as FIF, LineEdit, MessageBoxBase,
                            PushButton, RoundMenu, SubtitleLabel)
from src.controllers.db_controller import DBController
from src.utils import paths
from src.utils.einvoice_parser import EInvoiceData, read_einvoice, to_html
from src.utils.signal_bus import SignalBus
from src.views.common import COLOR_GREY, Column, ListPage, confirm, fmt_date, fmt_money, notify_error, notify_success
from src.views.date_picker import GermanDatePicker
from src.views.invoice_interface import RIGHT, add_action

logger = logging.getLogger(__name__)

_AMOUNT_RE = re.compile(r'(?:Gesamtbetrag|Rechnungsbetrag|Endbetrag|Zahlbetrag|Summe|Total|Betrag)[\s\S]{0,30}?(\d{1,3}(?:[.,]\d{3})+[.,]\d{2}|\d+[.,]\d{2})', re.IGNORECASE)
_DATE_RE = re.compile(r'(?:Rechnungsdatum|Datum|Leistungsdatum|Lieferdatum)[\s\S]{0,30}?(\d{2}\.\d{2}\.\d{4})', re.IGNORECASE)


def guess_from_pdf_text(path: str):
    """Fallback for PDFs without structured data: amount and date from the text layer."""
    amount, date_obj = 0.0, datetime.now().date()
    try:
        text = "\n".join((page.extract_text() or "") for page in PdfReader(path).pages[:3])
        match = _AMOUNT_RE.search(text)
        if match:
            # The last separator is the decimal separator: 1.234,56 (DE) or 1,234.56 (EN)
            value = match.group(1)
            dec_pos = max(value.rfind(','), value.rfind('.'))
            amount = float(re.sub(r'[.,]', '', value[:dec_pos]) + '.' + value[dec_pos + 1:])
        match = _DATE_RE.search(text)
        if match:
            date_obj = datetime.strptime(match.group(1), '%d.%m.%Y').date()
    except Exception:
        logger.info("Text der PDF %s konnte nicht ausgewertet werden", path, exc_info=True)
    return amount, date_obj


class IncomingInvoiceDialog(MessageBoxBase):
    def __init__(self, parent, amount: float, date_obj, description: str, einvoice: EInvoiceData = None):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel('Rechnungsdaten bestätigen', self))
        if einvoice:
            info = BodyLabel(f"E-Rechnung erkannt ({einvoice.format}): Die Daten wurden aus den strukturierten Rechnungsdaten übernommen.", self)
            info.setWordWrap(True)
            self.viewLayout.addWidget(info)
        self.supplierEdit = self._field("Lieferant", LineEdit(self), einvoice.seller_name if einvoice else "")
        self.numberEdit = self._field("Rechnungsnummer", LineEdit(self), einvoice.number if einvoice else "")
        self.descEdit = self._field("Beschreibung", LineEdit(self), description)
        self.datePicker = GermanDatePicker(self)
        self.datePicker.setDate(QDate(date_obj.year, date_obj.month, date_obj.day))
        self._field("Rechnungsdatum", self.datePicker)
        self.amountSpin = DoubleSpinBox(self)
        self.amountSpin.setRange(-9_999_999.99, 9_999_999.99)
        self.amountSpin.setDecimals(2)
        self.amountSpin.setValue(amount)
        self._field("Betrag brutto (€)", self.amountSpin)
        self.widget.setMinimumWidth(420)

    def _field(self, label, widget, text=None):
        self.viewLayout.addWidget(BodyLabel(label, self))
        self.viewLayout.addWidget(widget)
        if text is not None:
            widget.setText(text)
        return widget

    def get_data(self):
        return {
            "description": self.descEdit.text().strip(),
            "date": datetime.combine(self.datePicker.date.toPython(), datetime.min.time()),
            "amount": self.amountSpin.value(),
            "supplier_name": self.supplierEdit.text().strip(),
            "invoice_number": self.numberEdit.text().strip(),
        }


class EInvoiceViewer(QDialog):
    """Human readable view of a received e-invoice (pure XML cannot be read otherwise)."""

    def __init__(self, data: EInvoiceData, original_path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"E-Rechnung {data.number}")
        self.resize(820, 760)
        layout = QVBoxLayout(self)
        browser = QTextBrowser(self)
        browser.setHtml(to_html(data))
        layout.addWidget(browser)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        original = PushButton("Originaldatei öffnen", self)
        original.clicked.connect(lambda: os.startfile(original_path))
        close = PushButton("Schließen", self)
        close.clicked.connect(self.accept)
        buttons.addWidget(original)
        buttons.addWidget(close)
        layout.addLayout(buttons)


class IncomingInvoiceInterface(ListPage):
    TITLES = {"Lieferant": "Lieferantenrechnungen", "Sonstige": "Sonstige Rechnungen"}

    def __init__(self, db_controller: DBController, invoice_type: str, parent=None):
        self.db_controller = db_controller
        self.invoice_type = invoice_type # "Lieferant" or "Sonstige"
        columns = [
            Column("Datum", lambda i: fmt_date(i.date), sort=lambda i: (i.date, i.id), width=115, descending=True),
            Column("Lieferant", lambda i: i.supplier_name or "", width=220),
            Column("Rechnungs-Nr.", lambda i: i.invoice_number or "", width=150),
            Column("Beschreibung", lambda i: i.description + (" (storniert)" if i.cancelled_at else "")),
            Column("Betrag", lambda i: fmt_money(i.amount), sort=lambda i: i.amount, width=120, align=RIGHT, descending=True),
            Column("Format", lambda i: i.einvoice_format or "PDF/Scan", width=170),
        ]
        super().__init__(self.TITLES[invoice_type], columns, (SignalBus.get().incomingInvoicesChanged,),
                         date_of=lambda i: i.date, row_color=lambda i: COLOR_GREY if i.cancelled_at else None, parent=parent)
        self.setObjectName(f"IncomingInvoiceInterface_{invoice_type}")
        self.add_header_button("DATEV Export", self.export_datev)
        self.add_header_button("Rechnungen hochladen", self.upload, primary=True)

    def records(self) -> list:
        return self.db_controller.get_incoming_invoices(self.invoice_type)

    def on_activated(self, invoice):
        self.open_invoice(invoice)

    def fill_context_menu(self, menu: RoundMenu, invoice):
        add_action(menu, FIF.VIEW, "Anzeigen", lambda: self.open_invoice(invoice))
        add_action(menu, FIF.DOCUMENT, "Originaldatei öffnen", lambda: self.open_file(invoice.file_path))
        if not invoice.cancelled_at:
            add_action(menu, FIF.CANCEL, "Stornieren", lambda: self.cancel(invoice.id))

    def open_file(self, path):
        if os.path.isfile(path):
            os.startfile(path)
        else:
            notify_error(self, "Fehler", "Datei nicht gefunden.")

    def open_invoice(self, invoice):
        data = read_einvoice(invoice.file_path) if invoice.einvoice_format and os.path.isfile(invoice.file_path) else None
        if data:
            EInvoiceViewer(data, invoice.file_path, self.window()).exec()
        else:
            self.open_file(invoice.file_path)

    def cancel(self, invoice_id):
        if confirm(self, "Rechnung stornieren",
                   "Die Rechnung wird als storniert markiert und nicht mehr exportiert. "
                   "Datensatz und Datei bleiben gemäß GoBD aufbewahrt.\n\nFortfahren?"):
            if self.db_controller.cancel_incoming_invoice(invoice_id):
                notify_success(self, "Storniert", "Rechnung storniert.")

    def upload(self):
        filepaths, _ = QFileDialog.getOpenFileNames(self, "Rechnungen auswählen", paths.downloads_dir(), "Rechnungen (*.pdf *.xml)")
        imported = 0
        for filepath in filepaths:
            try:
                einvoice = read_einvoice(filepath)
            except Exception:
                logger.exception("E-Rechnung %s konnte nicht gelesen werden", filepath)
                einvoice = None
            if einvoice is None and filepath.lower().endswith(".xml"):
                notify_error(self, "Keine E-Rechnung", f"{os.path.basename(filepath)} ist keine lesbare XRechnung/ZUGFeRD-Datei.")
                continue
            if einvoice:
                amount = einvoice.payable_amount or einvoice.gross_amount
                if einvoice.is_credit_note:
                    amount = -abs(amount)
                date_obj = einvoice.issue_date or datetime.now().date()
                description = f"{einvoice.seller_name} {einvoice.number}".strip()
            else:
                amount, date_obj = guess_from_pdf_text(filepath)
                description = os.path.basename(filepath)

            dialog = IncomingInvoiceDialog(self.window(), amount, date_obj, description, einvoice)
            if not dialog.exec():
                continue
            data = dialog.get_data()
            # The controller archives the file read-only and stores its hash (GoBD)
            self.db_controller.add_incoming_invoice(
                invoice_type=self.invoice_type,
                date=data["date"],
                amount=data["amount"],
                description=data["description"] or os.path.basename(filepath),
                source_path=filepath,
                einvoice_format=einvoice.format if einvoice else None,
                invoice_number=data["invoice_number"],
                supplier_name=data["supplier_name"],
            )
            imported += 1
        if imported:
            notify_success(self, "Erfolg", f"{imported} Eingangsrechnung(en) gespeichert.")

    def export_datev(self):
        from src.utils.datev_generator import DatevGenerator
        invoices = [i for i in self.visible_records() if not i.cancelled_at]
        if not invoices:
            notify_error(self, "Keine Daten", "Es gibt keine (gefilterten) Rechnungen für den Export.")
            return
        filepath, _ = QFileDialog.getSaveFileName(
            self, "DATEV ZIP Export speichern",
            paths.desktop_path(f"DATEV_Eingangsrechnungen_{self.invoice_type}_{datetime.now().strftime('%Y%m%d')}.zip"),
            "ZIP Dateien (*.zip)")
        if not filepath:
            return
        if DatevGenerator(self.db_controller).generate_incoming_export(invoices, filepath):
            self.db_controller.log_actions("IncomingInvoice", [i.id for i in invoices], "DATEV Export")
            notify_success(self, "Erfolg", f"DATEV Export mit {len(invoices)} Rechnungen erstellt.")
        else:
            notify_error(self, "Fehler", "Fehler beim Erstellen des DATEV Exports.")
