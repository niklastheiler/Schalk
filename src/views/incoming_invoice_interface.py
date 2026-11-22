import logging
import os
from datetime import datetime
from PySide6.QtCore import QDate, QLocale, Qt
from PySide6.QtWidgets import QDialog, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QTextBrowser, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, DoubleSpinBox, FluentIcon as FIF, LineEdit, MessageBoxBase,
                            PushButton, RoundMenu, ScrollArea, SubtitleLabel)
from src.controllers.db_controller import DBController
from src.utils import paths
from src.utils.archive import is_pdf
from src.utils.einvoice_parser import EInvoiceData, read_einvoice, to_html
from src.utils.einvoice_validation import check_received
from src.utils.pdf_text_guess import guess_from_pdf
from src.utils.signal_bus import SignalBus
from src.views.common import COLOR_GREY, Column, ListPage, confirm, fmt_date, fmt_money, notify_error, notify_success, open_document
from src.views.date_picker import GermanDatePicker
from src.views.invoice_interface import add_action

logger = logging.getLogger(__name__)

class IncomingInvoiceDialog(MessageBoxBase):
    """
    Confirms the data of an uploaded invoice. Compact (labels next to the fields), so the dialog fits on small
    screens with large display scaling; notes of the rule check scroll in their own area.
    """
    MAX_NOTES = 6
    NOTES_HEIGHT = 110

    def __init__(self, parent, amount: float, date_obj, description: str, einvoice: EInvoiceData = None, notes: list = (),
                 supplier: str = "", number: str = ""):
        super().__init__(parent)
        self.viewLayout.setSpacing(10)
        self.viewLayout.addWidget(SubtitleLabel('Rechnungsdaten bestätigen', self))
        messages = []
        if einvoice:
            info = BodyLabel(f"E-Rechnung erkannt ({einvoice.format}): Die Daten wurden aus den strukturierten Rechnungsdaten übernommen.", self)
            info.setWordWrap(True)
            self.viewLayout.addWidget(info)
            if einvoice.currency != "EUR":
                messages.append(f"Achtung: Die Rechnung lautet auf {einvoice.currency}. Bitte den Betrag in Euro eintragen.")
            # Result of the rule check: the invoice is stored anyway (it was received), but the user should know
            messages += list(notes[:self.MAX_NOTES])
            if len(notes) > self.MAX_NOTES:
                messages.append(f"… und {len(notes) - self.MAX_NOTES} weitere Hinweise (Protokoll: {paths.LOG_PATH}).")
        else:
            info = BodyLabel("Aus dem Text der PDF erkannt, bitte prüfen.", self)
            self.viewLayout.addWidget(info)
        if messages:
            self._add_warnings(messages)

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.supplierEdit = self._field(form, "Lieferant", LineEdit(self), einvoice.seller_name if einvoice else supplier)
        self.numberEdit = self._field(form, "Rechnungsnummer", LineEdit(self), einvoice.number if einvoice else number)
        self.datePicker = GermanDatePicker(self)
        self.datePicker.setDate(QDate(date_obj.year, date_obj.month, date_obj.day))
        self._field(form, "Rechnungsdatum", self.datePicker)
        self.amountSpin = DoubleSpinBox(self)
        self.amountSpin.setLocale(QLocale(QLocale.German, QLocale.Germany))
        self.amountSpin.setRange(-9_999_999.99, 9_999_999.99)
        self.amountSpin.setDecimals(2)
        self.amountSpin.setGroupSeparatorShown(True)
        self.amountSpin.setSuffix(" €")
        self.amountSpin.setValue(amount)
        self._field(form, "Betrag brutto", self.amountSpin)
        self.descEdit = self._field(form, "Beschreibung", LineEdit(self), description)
        self.viewLayout.addLayout(form)
        self.yesButton.setText("Speichern")
        self.cancelButton.setText("Abbrechen")
        self.widget.setMinimumWidth(520)

    def _add_warnings(self, messages: list):
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 8, 0)
        for text in messages:
            warning = BodyLabel(text, box)
            warning.setWordWrap(True)
            warning.setStyleSheet("color: #C42B1C;")
            layout.addWidget(warning)
        scroll = ScrollArea(self)
        scroll.setWidget(box)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        scroll.setMaximumHeight(self.NOTES_HEIGHT)
        self.notesArea = scroll
        self.viewLayout.addWidget(scroll)

    def _field(self, form: QFormLayout, label, widget, text=None):
        form.addRow(BodyLabel(label, self), widget)
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
        original.clicked.connect(lambda: open_document(self, original_path))
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
            Column("Betrag", lambda i: fmt_money(i.amount), sort=lambda i: i.amount, width=120, descending=True),
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
        open_document(self, paths.resolve(path))

    def open_invoice(self, invoice):
        path = paths.resolve(invoice.file_path)
        data = None
        if invoice.einvoice_format and os.path.isfile(path):
            try:
                data = read_einvoice(path)
            except Exception:
                logger.exception("E-Rechnung %s konnte nicht gelesen werden", path)
        if data:
            EInvoiceViewer(data, path, self.window()).exec()
        else:
            self.open_file(path)

    def cancel(self, invoice_id):
        if confirm(self, "Rechnung stornieren",
                   "Die Rechnung wird als storniert markiert und nicht mehr exportiert. "
                   "Datensatz und Datei bleiben gemäß GoBD aufbewahrt.\n\nFortfahren?"):
            if self.db_controller.cancel_incoming_invoice(invoice_id):
                notify_success(self, "Storniert", "Rechnung storniert.")

    def upload(self):
        filepaths, _ = QFileDialog.getOpenFileNames(self, "Rechnungen auswählen", paths.downloads_dir(), "Rechnungen als PDF oder XRechnung (*.pdf *.xml)")
        imported = 0
        for filepath in filepaths:
            if not filepath.lower().endswith(".xml") and not is_pdf(filepath):
                notify_error(self, "Kein PDF", f"{os.path.basename(filepath)} ist weder ein PDF noch eine XRechnung (XML).")
                continue
            try:
                einvoice = read_einvoice(filepath)
            except ValueError as e: # too large for reading the structured data
                if filepath.lower().endswith(".xml"):
                    notify_error(self, "Nicht eingelesen", f"{os.path.basename(filepath)}: {e}")
                    continue
                logger.info("%s: %s; wird als PDF ohne strukturierte Daten erfasst", filepath, e)
                einvoice = None
            except Exception:
                logger.exception("E-Rechnung %s konnte nicht gelesen werden", filepath)
                einvoice = None
            notes = []
            if einvoice:
                try:
                    notes = check_received(einvoice)
                except Exception:
                    logger.exception("Prüfung der E-Rechnung %s fehlgeschlagen", filepath)
                    notes = ["Die Rechnung konnte nicht gegen die EN-16931-Regeln geprüft werden (Details im Protokoll)."]
                if notes:
                    logger.info("Prüfung der E-Rechnung %s: %s", filepath, notes)
            if einvoice is None and filepath.lower().endswith(".xml"):
                notify_error(self, "Keine E-Rechnung", f"{os.path.basename(filepath)} ist keine lesbare XRechnung/ZUGFeRD-Datei.")
                continue
            supplier = number = ""
            if einvoice:
                amount = einvoice.payable_amount or einvoice.gross_amount
                if einvoice.is_credit_note:
                    amount = -abs(amount)
                date_obj = einvoice.issue_date or datetime.now().date()
                description = f"{einvoice.seller_name} {einvoice.number}".strip()
            else:
                seller = self.db_controller.current_seller()
                own = [seller.get("company_name"), f"{seller.get('first_name', '')} {seller.get('last_name', '')}".strip()]
                guess = guess_from_pdf(filepath, own)
                amount, date_obj = guess.amount, guess.invoice_date or datetime.now().date()
                supplier, number = guess.supplier, guess.number
                description = f"{supplier} {number}".strip() or os.path.basename(filepath)

            dialog = IncomingInvoiceDialog(self.window(), amount, date_obj, description, einvoice, notes, supplier, number)
            if not dialog.exec():
                continue
            data = dialog.get_data()
            # The same invoice entered twice would be booked twice
            duplicate = self.db_controller.find_duplicate_incoming(filepath, data["supplier_name"], data["invoice_number"])
            if duplicate and not confirm(
                    self, "Rechnung bereits erfasst",
                    f"{os.path.basename(filepath)} ist bereits als „{duplicate.description}“ vom "
                    f"{fmt_date(duplicate.date)} gespeichert.\n\nTrotzdem noch einmal speichern?"):
                continue
            try:
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
                    check_result=self._check_result(einvoice, notes),
                )
            except (OSError, ValueError) as e:
                logger.exception("Eingangsrechnung %s konnte nicht gespeichert werden", filepath)
                notify_error(self, "Nicht gespeichert", f"{os.path.basename(filepath)}: {e}")
                continue
            imported += 1
        if imported:
            notify_success(self, "Erfolg", f"{imported} Eingangsrechnung(en) gespeichert.")

    @staticmethod
    def _check_result(einvoice, notes: list) -> str:
        """Documented in the history: what was checked on receipt and with which result."""
        if not einvoice:
            return "Keine strukturierten Rechnungsdaten (PDF/Scan), nicht geprüft"
        if not notes:
            return "E-Rechnung geprüft (EN 16931): keine Beanstandungen"
        return "E-Rechnung geprüft: " + " | ".join(notes)

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
