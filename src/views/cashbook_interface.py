import os
from datetime import datetime
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout
from qfluentwidgets import BodyLabel, ComboBox, FluentIcon as FIF, LineEdit, PushButton, RoundMenu, SubtitleLabel, TransparentToolButton
from src.controllers.db_controller import CASHBOOK_TYPES, DBController, GoBDError
from src.utils import paths
from src.utils.archive import is_pdf
from src.utils.signal_bus import SignalBus
from src.views.common import COLOR_GREY, Column, ListPage, confirm, fmt_date, fmt_money, notify_error, notify_success
from src.views.date_picker import GermanDatePicker
from src.views.document_editor import _number_validator, _parse_number
from src.views.invoice_interface import RIGHT, MonthDialog, add_action


class CashbookInterface(ListPage):
    def __init__(self, db_controller: DBController, parent=None):
        self.db_controller = c = db_controller
        self.attachment_path = ""
        self.editing_id = None
        self._cancelled = set()
        columns = [
            Column("Datum", lambda e: fmt_date(e.entry_date), sort=lambda e: (e.entry_date, e.id), width=115, descending=True),
            Column("Beleg-Nr", lambda e: e.receipt_number or "Entwurf", sort=lambda e: e.receipt_number or "~", width=150, descending=True),
            Column("Art", lambda e: e.entry_type + (" (Storno)" if e.is_storno else ""), width=190),
            Column("Beschreibung", lambda e: e.description or ""),
            Column("Betrag", lambda e: fmt_money(c.cashbook_signed_amount(e)), sort=c.cashbook_signed_amount, width=120, align=RIGHT, descending=True),
            Column("GoBD-Hash", lambda e: f"{e.hash_chain[:8]}…{e.hash_chain[-8:]}" if e.hash_chain else "–", width=170),
            Column("Beleg", lambda e: "Vorhanden" if e.attachment_path else "-", width=90),
        ]
        super().__init__("Kassenbuch", columns, (SignalBus.get().cashbookChanged,), date_of=lambda e: e.entry_date,
                         row_color=lambda e: COLOR_GREY if e.is_storno or e.id in self._cancelled else None, parent=parent)
        self.setObjectName("CashbookInterface")
        self.add_header_button("DATEV Export", self.show_datev_export_dialog)
        self.finalizeBtn = self.add_header_button("Festschreiben", self.finalize_cashbook)
        self.addBtn = self.add_header_button("Eintrag hinzufügen", self.add_entry, primary=True)
        self._build_form()

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
        labeled("Betrag (€)", self.amountEdit)
        self.descEdit = LineEdit()
        self.descEdit.setPlaceholderText("Buchungstext")
        self.descEdit.setMinimumWidth(220)
        labeled("Beschreibung", self.descEdit)
        self.typeCombo = ComboBox()
        self.typeCombo.addItems(CASHBOOK_TYPES)
        labeled("Art", self.typeCombo)

        attach = QHBoxLayout()
        self.attachBtn = TransparentToolButton(FIF.LINK)
        self.attachBtn.clicked.connect(self.attach_file)
        self.attachLabel = BodyLabel("Kein Anhang")
        attach.addWidget(self.attachBtn)
        attach.addWidget(self.attachLabel)
        attach_box = QVBoxLayout()
        attach_box.addWidget(BodyLabel("Beleg (optional)"))
        attach_box.addLayout(attach)
        form.addLayout(attach_box)
        self.cancelEditBtn = PushButton("Abbrechen")
        self.cancelEditBtn.clicked.connect(self.reset_form)
        self.cancelEditBtn.hide()
        form.addWidget(self.cancelEditBtn, 0, Qt.AlignBottom)
        form.addStretch(1)

        balance_box = QVBoxLayout()
        balance_box.addWidget(BodyLabel("Aktueller Kassenbestand"))
        self.balanceLabel = SubtitleLabel("0,00 €")
        balance_box.addWidget(self.balanceLabel)
        form.addLayout(balance_box)
        self.vBoxLayout.insertLayout(1, form)
        self.vBoxLayout.insertSpacing(2, 12)

    def records(self) -> list:
        return self.db_controller.get_cashbook_entries()

    def on_refreshed(self, records: list):
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
        if os.path.isfile(path):
            os.startfile(path)
        else:
            notify_error(self, "Fehler", "Beleg-Datei nicht gefunden.")

    def attach_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Beleg auswählen", paths.downloads_dir(), "PDF-Dokumente (*.pdf)")
        if path and not is_pdf(path):
            notify_error(self, "Kein PDF", f"{os.path.basename(path)} ist keine PDF-Datei. Als Beleg sind nur PDFs erlaubt.")
            return
        if path:
            self.attachment_path = path
            self.attachLabel.setText(os.path.basename(path))

    def add_entry(self):
        amount = _parse_number(self.amountEdit.text(), 0.0)
        date_obj = self.datePicker.date.toPython()
        fields = dict(
            entry_date=datetime.combine(date_obj, datetime.min.time()),
            amount=amount,
            description=self.descEdit.text().strip(),
            entry_type=self.typeCombo.currentText(),
            attachment_source=self.attachment_path or None,
        )
        try:
            # The controller archives the receipt read-only under a unique name and checks the balance
            if self.editing_id is None:
                self.db_controller.add_cashbook_entry(category="Allgemein", tax_percent=19.0, **fields)
            else:
                self.db_controller.update_cashbook_entry(self.editing_id, **fields)
        except (GoBDError, ValueError) as e:
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
        self.attachment_path = ""
        self.attachLabel.setText(os.path.basename(entry.attachment_path) if entry.attachment_path else "Kein Anhang")
        self.addBtn.setText("Änderung speichern")
        self.cancelEditBtn.show()
        self.amountEdit.setFocus()

    def reset_form(self):
        self.editing_id = None
        self.amountEdit.clear()
        self.descEdit.clear()
        self.attachment_path = ""
        self.attachLabel.setText("Kein Anhang")
        self.addBtn.setText("Eintrag hinzufügen")
        self.cancelEditBtn.hide()

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
        months = sorted({e.entry_date.strftime("%Y-%m") for e in entries}, reverse=True)
        if not months:
            notify_error(self, "Keine Daten", "Es gibt keine festgeschriebenen Kassenbucheinträge zum Exportieren.")
            return
        dialog = MonthDialog("DATEV Monats-Export (Kassenbelege)", months, self.window())
        if not dialog.exec():
            return
        selected = dialog.monthCombo.currentText()
        export = [e for e in entries if e.entry_date.strftime("%Y-%m") == selected]
        target, _ = QFileDialog.getSaveFileName(self, "DATEV-Export speichern",
                                                paths.desktop_path(f"DATEV_Export_Kassenbuch_{selected.replace('-', '_')}.zip"), "ZIP (*.zip)")
        if not target:
            return
        if DatevGenerator(self.db_controller).generate_cashbook_export(export, target):
            self.db_controller.log_actions("Cashbook", [e.id for e in export], "DATEV Export")
            notify_success(self, "DATEV Export erfolgreich", target, duration=5000)
        else:
            notify_error(self, "Kein Export", "Für diesen Monat sind keine Belegdateien vorhanden.")
