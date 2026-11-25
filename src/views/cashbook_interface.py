import logging
import os
from datetime import datetime
from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, ComboBox, FluentIcon as FIF, LineEdit, PushButton, RoundMenu, SubtitleLabel, TransparentToolButton
from src.controllers.db_controller import CASHBOOK_TYPES, DBController, GoBDError
from src.utils import paths
from src.utils.archive import is_pdf
from src.utils.receipt_recognition import EXPENSE, INCOME, recognize_receipt
from src.utils.signal_bus import SignalBus
from src.views.common import (COLOR_GREY, Column, ListPage, UnsavedChanges, confirm, fmt_date, fmt_money, notify_error,
                              notify_success, notify_warning)
from src.views.date_picker import GermanDatePicker
from src.views.document_editor import _number_validator, _parse_number
from src.views.invoice_interface import MonthDialog, add_action

logger = logging.getLogger(__name__)


class CashbookInterface(UnsavedChanges, ListPage):
    def __init__(self, db_controller: DBController, parent=None):
        self.db_controller = c = db_controller
        self.attachment_path = ""
        self.editing_id = None
        self._cancelled = set()
        columns = [
            Column("Datum", lambda e: fmt_date(e.entry_date), sort=lambda e: (e.entry_date, e.id), width=115, descending=True),
            Column("Beleg-Nr", lambda e: e.receipt_number or "Entwurf", sort=lambda e: e.receipt_number or "~", width=140, descending=True),
            Column("Art", lambda e: e.entry_type + (" (Storno)" if e.is_storno else ""), width=170),
            Column("Beschreibung", lambda e: e.description or ""),
            Column("Betrag", lambda e: fmt_money(c.cashbook_signed_amount(e)), sort=c.cashbook_signed_amount, width=120, descending=True),
            Column("GoBD-Hash", lambda e: f"{e.hash_chain[:8]}…{e.hash_chain[-8:]}" if e.hash_chain else "–", width=170),
            Column("Beleg", lambda e: "✓" if e.attachment_path else "✗", width=90),
        ]
        super().__init__("Kassenbuch", columns, (SignalBus.get().cashbookChanged,), date_of=lambda e: e.entry_date,
                         row_color=lambda e: COLOR_GREY if e.is_storno or e.id in self._cancelled else None, parent=parent)
        self.setObjectName("CashbookInterface")
        self.datevButton = self.add_header_button("DATEV Export", self.show_datev_export_dialog)
        self.finalizeBtn = self.add_header_button("Festschreiben", self.finalize_cashbook)
        self.addBtn = self.add_header_button("Eintrag hinzufügen", self.add_entry, primary=True)
        self._build_form()
        # New or paid invoices change the selection; the chosen one stays selected
        SignalBus.get().invoicesChanged.connect(lambda: self._fill_invoice_combo(keep_id=self.invoice_id))
        self.mark_clean()

    def _build_form(self):
        form = QHBoxLayout()

        def labeled(label, widget):
            box = QVBoxLayout()
            box.addWidget(BodyLabel(label))
            box.addWidget(widget)
            form.addLayout(box)

        self.datePicker = GermanDatePicker()
        self.datePicker.setDate(QDate.currentDate())
        labeled("Datum", self.datePicker)
        self.amountEdit = LineEdit()
        self.amountEdit.setValidator(_number_validator())
        self.amountEdit.setPlaceholderText("0,00")
        self.amountEdit.setFixedWidth(110)
        labeled("Betrag (€)", self.amountEdit)
        self.descEdit = LineEdit()
        self.descEdit.setPlaceholderText("Buchungstext")
        # A short text is enough; the receipt field follows right next to it
        self.descEdit.setMinimumWidth(250)
        self.descEdit.setMaximumWidth(375)
        self.typeCombo = ComboBox()
        self.typeCombo.addItems(CASHBOOK_TYPES)
        labeled("Art", self.typeCombo)

        # Einnahme: an own invoice of this month instead of a receipt (its PDF is the receipt)
        self.invoice_id = None
        self.invoiceBox = QWidget()
        invoice_layout = QVBoxLayout(self.invoiceBox)
        invoice_layout.setContentsMargins(0, 0, 0, 0)
        invoice_layout.addWidget(BodyLabel("Rechnung"))
        self.invoiceCombo = ComboBox()
        self.invoiceCombo.setMinimumWidth(180)
        self.invoiceCombo.setMaximumWidth(260)
        self.invoiceCombo.currentIndexChanged.connect(self._on_invoice_chosen)
        invoice_layout.addWidget(self.invoiceCombo)

        # Einnahme and Barentnahme Firma: receipt required (for an invoice its PDF); Barentnahme Privat has none
        self.attachBox = QWidget()
        attach_box = QVBoxLayout(self.attachBox)
        attach_box.setContentsMargins(0, 0, 0, 0)
        attach = QHBoxLayout()
        self.attachBtn = TransparentToolButton(FIF.LINK)
        self.attachBtn.clicked.connect(self.attach_file)
        self.attachLabel = BodyLabel("Kein Anhang")
        self.attachLabel.setMaximumWidth(self.ATTACHMENT_LABEL_WIDTH + 10)
        attach.addWidget(self.attachBtn)
        attach.addWidget(self.attachLabel)
        attach_box.addWidget(BodyLabel("Beleg"))
        attach_box.addLayout(attach)
        self.typeCombo.currentTextChanged.connect(self._on_type_changed)
        self.cancelEditBtn = PushButton("Abbrechen")
        self.cancelEditBtn.clicked.connect(self.reset_form)
        self.cancelEditBtn.hide()
        form.addStretch(1)

        balance_box = QVBoxLayout()
        balance_box.addWidget(BodyLabel("Aktueller Kassenbestand"))
        self.balanceLabel = SubtitleLabel("0,00 €")
        balance_box.addWidget(self.balanceLabel)
        form.addLayout(balance_box)
        # Second row: description (stretching), invoice or receipt by type, cancel while editing
        description_box = QVBoxLayout()
        description_box.setSpacing(4)
        description_box.addWidget(BodyLabel("Beschreibung"))
        description_box.addWidget(self.descEdit)
        description_row = QHBoxLayout()
        description_row.setSpacing(16)
        description_row.addLayout(description_box)
        description_row.addWidget(self.attachBox)
        description_row.addWidget(self.invoiceBox)
        description_row.addWidget(self.cancelEditBtn, 0, Qt.AlignBottom)
        description_row.addStretch(1)
        rows = QVBoxLayout()
        rows.setSpacing(8)
        rows.addLayout(form)
        rows.addLayout(description_row)
        self.vBoxLayout.insertLayout(1, rows)
        self.vBoxLayout.insertSpacing(2, 12)
        self._fill_invoice_combo()
        self._on_type_changed(self.typeCombo.currentText())

    # --- Type and invoice ---
    def _fill_invoice_combo(self, keep_id=None):
        """Open own invoices of this month; keep_id keeps an invoice of an edited entry in the list."""
        c = self.db_controller
        invoices = c.cash_invoices()
        if keep_id and keep_id not in [i.id for i in invoices] and c.get_invoice_header(keep_id):
            invoices.insert(0, c.get_invoice_header(keep_id))
        self.invoiceCombo.blockSignals(True)
        self.invoiceCombo.clear()
        self.invoiceCombo.addItem("Ohne Rechnung", userData=None)
        for invoice in invoices:
            self.invoiceCombo.addItem(f"{invoice.invoice_number} – {c.customer_display_name(invoice)} "
                                      f"({fmt_money(c.outstanding_amount(invoice))})", userData=invoice.id)
        index = self.invoiceCombo.findData(keep_id) if keep_id else 0
        self.invoiceCombo.setCurrentIndex(max(index, 0))
        self.invoiceCombo.blockSignals(False)

    def _on_type_changed(self, entry_type: str):
        income = entry_type == INCOME
        self.invoiceBox.setVisible(income)
        self.attachBox.setVisible(income or entry_type == EXPENSE)
        if not income and self.invoice_id:
            self.invoiceCombo.setCurrentIndex(0)
        if entry_type == "Barentnahme Privat" and self.attachment_path:
            # A private withdrawal has no receipt
            self.attachment_path = ""
            self._show_attachment("")

    ATTACHMENT_LABEL_WIDTH = 220

    def _show_attachment(self, path: str, name: str = None):
        """Short name of the receipt next to the button (archived names are long), the full path as tooltip."""
        if not path:
            self.attachLabel.setText("Kein Anhang")
            self.attachLabel.setToolTip("")
            return
        name = name or os.path.basename(path)
        metrics = QFontMetrics(self.attachLabel.font())
        self.attachLabel.setText(metrics.elidedText(name, Qt.ElideMiddle, self.ATTACHMENT_LABEL_WIDTH))
        self.attachLabel.setToolTip(path)

    def _on_invoice_chosen(self, index: int):
        """Takes over amount, text and the invoice PDF (as receipt) of the chosen invoice."""
        invoice_id = self.invoiceCombo.itemData(index)
        previous, self.invoice_id = self.invoice_id, invoice_id
        if not invoice_id:
            if previous: # the PDF of the deselected invoice is no receipt any more
                self.attachment_path = ""
                self._show_attachment("")
            return
        c = self.db_controller
        invoice = c.get_invoice(invoice_id)
        self.amountEdit.setText(f"{c.outstanding_amount(invoice):.2f}".replace(".", ","))
        self.descEdit.setText(f"Rechnung {invoice.invoice_number} – {c.customer_display_name(invoice)}")
        try:
            self.attachment_path = c.get_archived_invoice_pdf(invoice) or ""
        except GoBDError:
            self.attachment_path = ""
        self._show_attachment(self.attachment_path, f"Rechnung {invoice.invoice_number}.pdf")

    def records(self) -> list:
        return self.db_controller.get_cashbook_entries()

    # --- Unsaved changes: only the entry form counts, not search and filters ---
    def unsaved_fields(self) -> list:
        return [self.datePicker, self.amountEdit, self.descEdit, self.typeCombo]

    def extra_state(self) -> tuple:
        return (self.attachment_path, self.invoice_id)

    def discard_changes(self):
        self.datePicker.setDate(QDate.currentDate())
        self.reset_form()

    def on_refreshed(self, records: list):
        from src.utils.datev_generator import DatevGenerator
        exportable = DatevGenerator.exportable_cashbook_entries(self.db_controller, records)
        self.set_export_enabled(self.datevButton, any(e.attachment_path for e in exportable),
                                "Keine festgeschriebenen Buchungen mit Beleg (stornierte zählen nicht)")
        self._cancelled = self.db_controller.cancelled_cashbook_ids()
        self.balanceLabel.setText(fmt_money(self.db_controller.get_cashbook_balance()))
        drafts = self.db_controller.cashbook_draft_count()
        self.finalizeBtn.setEnabled(drafts > 0)
        self.finalizeBtn.setText(f"Festschreiben ({drafts})" if drafts else "Festschreiben")
        self.finalizeBtn.setToolTip("Alle Entwürfe festschreiben: danach sind sie nicht mehr änderbar (GoBD)")
        if self.editing_id is not None and self.db_controller.get_cashbook_entry(self.editing_id) is None:
            self.reset_form()

    def on_activated(self, entry):
        if not entry.finalized_at:
            self.edit_entry(entry)
        elif entry.attachment_path:
            self.open_attachment(entry.attachment_path)

    def fill_context_menu(self, menu: RoundMenu, entry):
        if entry.attachment_path:
            add_action(menu, FIF.DOCUMENT, "Beleg öffnen", lambda: self.open_attachment(entry.attachment_path))
        if not entry.finalized_at:
            add_action(menu, FIF.EDIT, "Bearbeiten", lambda: self.edit_entry(entry))
            add_action(menu, FIF.DELETE, "Löschen", lambda: self.delete_entry(entry.id))
        elif not entry.is_storno and entry.id not in self._cancelled:
            add_action(menu, FIF.CANCEL, "Stornieren (Gegenbuchung)", lambda: self.storno_entry(entry.id))

    def open_attachment(self, path):
        """Shows the receipt in Schalk (no PDF program, no attachment panel)."""
        from src.views.document_viewer import PdfViewer
        resolved = paths.resolve(path)
        if not resolved or not os.path.isfile(resolved):
            notify_error(self, "Beleg fehlt im Archiv",
                         "Die archivierte Datei ist nicht mehr vorhanden. Bitte unter Einstellungen → Sicherheit & GoBD "
                         "ein Backup einspielen: Fehlende Belege werden daraus wiederhergestellt.")
            return
        PdfViewer(resolved, "Kassenbeleg", os.path.basename(resolved), self.window()).exec()

    def attach_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Beleg auswählen", paths.downloads_dir(), "PDF-Dokumente (*.pdf)")
        if path and not is_pdf(path):
            notify_error(self, "Kein PDF", f"{os.path.basename(path)} ist keine PDF-Datei. Als Beleg sind nur PDFs erlaubt.")
            return
        if path:
            self.attachment_path = path
            self._show_attachment(path)
            self.fill_from_receipt(path)

    def fill_from_receipt(self, path: str):
        """
        Takes amount, description and type from the receipt: an invoice issued by Schalk is income, everything else
        an expense. Values the user already typed are kept; the type always follows the receipt.
        """
        try:
            guess = recognize_receipt(self.db_controller, path)
        except Exception:
            logger.exception("Beleg %s konnte nicht ausgewertet werden", path)
            return
        if guess.invoice_id:
            # Linked first: switching the type to Einnahme keeps the receipt of a linked invoice
            self._fill_invoice_combo(keep_id=guess.invoice_id)
            self.invoice_id = guess.invoice_id
        self.typeCombo.setCurrentText(guess.entry_type)
        if guess.amount > 0 and not _parse_number(self.amountEdit.text(), 0.0):
            self.amountEdit.setText(f"{guess.amount:.2f}".replace(".", ","))
        if guess.description and not self.descEdit.text().strip():
            self.descEdit.setText(guess.description)
        if guess.receipt_date and self.editing_id is None:
            self.datePicker.setDate(QDate(guess.receipt_date.year, guess.receipt_date.month, guess.receipt_date.day))
        kind = "Einnahme aus eigener Rechnung" if guess.entry_type == INCOME else "Ausgabe"
        notify_success(self, "Beleg ausgewertet", f"{kind} erkannt. Bitte Betrag und Beschreibung prüfen.")

    def add_entry(self):
        amount = _parse_number(self.amountEdit.text(), 0.0)
        date_obj = self.datePicker.date.toPython()
        fields = dict(
            entry_date=datetime.combine(date_obj, datetime.min.time()),
            amount=amount,
            description=self.descEdit.text().strip(),
            entry_type=self.typeCombo.currentText(),
            attachment_source=self.attachment_path or None,
            invoice_id=self.invoice_id if self.typeCombo.currentText() == INCOME else None,
        )
        try:
            # The controller archives the receipt read-only under a unique name and checks the balance
            if self.editing_id is None:
                self.db_controller.add_cashbook_entry(category="Allgemein", tax_percent=19.0, **fields)
            else:
                self.db_controller.update_cashbook_entry(self.editing_id, **fields)
        except (GoBDError, ValueError, OSError) as e:
            notify_error(self, "Fehler", str(e))
            return
        notify_success(self, "Gespeichert", "Der Eintrag ist bis zum Festschreiben änderbar.")
        self.reset_form()

    def edit_entry(self, entry):
        self.editing_id = entry.id
        d = entry.entry_date
        self.datePicker.setDate(QDate(d.year, d.month, d.day))
        self.amountEdit.setText(f"{entry.amount:.2f}".replace(".", ","))
        self.descEdit.setText(entry.description or "")
        self.typeCombo.setCurrentText(entry.entry_type)
        self._fill_invoice_combo(keep_id=entry.invoice_id)
        self.invoice_id = entry.invoice_id
        self.attachment_path = ""
        self._show_attachment(entry.attachment_path or "")
        self.addBtn.setText("Änderung speichern")
        self.cancelEditBtn.show()
        self.amountEdit.setFocus()
        self.mark_clean()

    def reset_form(self):
        self.editing_id = None
        self.invoice_id = None
        self._fill_invoice_combo()
        self.amountEdit.clear()
        self.descEdit.clear()
        self.attachment_path = ""
        self._show_attachment("")
        self.addBtn.setText("Eintrag hinzufügen")
        self.cancelEditBtn.hide()
        self.mark_clean()

    def delete_entry(self, entry_id):
        entry = self.db_controller.get_cashbook_entry(entry_id)
        if not confirm(self, "Entwurf löschen", f"Den Eintrag „{entry.description}“ wirklich löschen?"):
            return
        try:
            self.db_controller.delete_cashbook_entry(entry_id)
        except (GoBDError, ValueError) as e:
            notify_error(self, "Fehler", str(e))
            return
        notify_success(self, "Gelöscht", "Der Entwurf wurde gelöscht.")

    def finalize_cashbook(self):
        drafts = self.db_controller.cashbook_draft_count()
        if not drafts:
            return
        if not confirm(self, "Kassenbuch festschreiben",
                       f"{drafts} Eintrag/Einträge werden festgeschrieben. Sie erhalten eine fortlaufende Belegnummer "
                       "und werden in die GoBD-Hash-Kette aufgenommen.\n\nDanach sind sie nicht mehr änderbar, "
                       "Korrekturen sind nur noch per Storno möglich. Fortfahren?"):
            return
        count = self.db_controller.finalize_cashbook()
        self.reset_form()
        notify_success(self, "Festgeschrieben", f"{count} Eintrag/Einträge wurden festgeschrieben.")

    def storno_entry(self, entry_id):
        entry = self.db_controller.get_cashbook_entry(entry_id)
        if not confirm(self, "Eintrag stornieren",
                       f"Für {entry.receipt_number} wird eine Storno-Gegenbuchung mit heutigem Datum erstellt. "
                       "Der ursprüngliche Eintrag bleibt unverändert erhalten.\n\nFortfahren?"):
            return
        try:
            self.db_controller.storno_cashbook_entry(entry_id)
        except (GoBDError, ValueError) as e:
            notify_error(self, "Fehler", str(e))
            return
        notify_success(self, "Storniert", "Die Storno-Gegenbuchung wurde erstellt.")

    def show_datev_export_dialog(self):
        from src.utils.datev_generator import DatevGenerator
        # Only finalized entries have a receipt number and may leave the system
        entries = [e for e in self.db_controller.get_cashbook_entries() if e.finalized_at]
        # Only months with receipts for DATEV (cancelled entries and their stornos do not count)
        months = sorted({e.entry_date.strftime("%Y-%m") for e in DatevGenerator.exportable_cashbook_entries(
            self.db_controller, entries) if e.attachment_path}, reverse=True)
        if not months:
            notify_error(self, "Keine Daten", "Es gibt keine festgeschriebenen Kassenbucheinträge zum Exportieren.")
            return
        dialog = MonthDialog("DATEV Monats-Export (Kassenbelege)", months, self.window())
        if not dialog.exec():
            return
        selected = dialog.monthCombo.currentText()
        month = [e for e in entries if e.entry_date.strftime("%Y-%m") == selected]
        export = DatevGenerator.exportable_cashbook_entries(self.db_controller, month)
        # A cancellation of an entry that already went to the tax advisor must be reported to them
        storno_ids = {e.storno_of_id for e in month if e.is_storno}
        cancelled_earlier = DatevGenerator.exported_before(
            self.db_controller, [e for e in self.db_controller.get_cashbook_entries() if e.id in storno_ids])
        if cancelled_earlier:
            numbers = ", ".join(e.receipt_number for e in cancelled_earlier)
            notify_warning(self, "Storno bereits exportierter Belege",
                           f"{numbers} wurde(n) schon früher an DATEV übergeben und in diesem Monat storniert. "
                           "Bitte dem Steuerberater mitteilen.", duration=-1)
        if not [e for e in export if e.attachment_path]:
            notify_error(self, "Kein Export", "In diesem Monat gibt es keine Belege für DATEV: Stornierte Buchungen "
                                              "und ihre Storno-Gegenbuchungen werden nicht exportiert.")
            return
        target, _ = QFileDialog.getSaveFileName(self, "DATEV-Export speichern",
                                                paths.desktop_path(f"DATEV_Export_Kassenbuch_{selected.replace('-', '_')}.zip"), "ZIP (*.zip)")
        if not target:
            return
        if DatevGenerator(self.db_controller).generate_cashbook_export(export, target):
            self.db_controller.log_actions("Cashbook", [e.id for e in export], "DATEV Export")
            notify_success(self, "DATEV Export erfolgreich", target, duration=5000)
        else:
            notify_error(self, "Kein Export", "Für diesen Monat sind keine Belegdateien vorhanden.")
