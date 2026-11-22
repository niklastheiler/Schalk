import logging
import os
import shutil
import sys
import threading
from datetime import datetime
from PySide6.QtCore import QProcess, Qt, Signal
from PySide6.QtGui import QImageReader, QIntValidator, QPixmap
from PySide6.QtWidgets import QApplication, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, CheckBox, ComboBox, LineEdit, MessageBoxBase, Pivot, PrimaryPushButton, PushButton,
                            SubtitleLabel)
from stdnum import bic as stdnum_bic, iban as stdnum_iban
from stdnum.eu import vat as stdnum_vat
from src.utils.validation import (attach_tax_number_format, contact_problems, german_postal_code_validator,
                                  is_valid_tax_number, phone_validator)
from src.controllers.db_controller import DBController, DEFAULT_PAYMENT_TERMS
from src.utils import paths
from src.utils.backup import create_backup, restore_backup
from src.utils.pdf_generator import DEFAULT_DOCUMENT_COLOR, DOCUMENT_COLORS
from src.utils.signal_bus import SignalBus
from src.version import APP_AUTHOR, APP_NAME, APP_VERSION
from src.views.common import confirm, make_scrollable, notify_error, notify_success, show_message

logger = logging.getLogger(__name__)

BACKUP_FILTER = "Schalk-Backup (*.backup)"
LOGO_PREVIEW_WIDTH, LOGO_PREVIEW_HEIGHT = 240, 72
# Input fields of the company and bank data: wide enough for names and an IBAN, no full-width bars
FIELD_WIDTH = 260

FIRM_FIELDS = [
    ("company_name", "Firmenname"),
    ("first_name", "Vorname"),
    ("last_name", "Nachname"),
    ("address", "Straße & Hausnummer"),
    ("postal_code", "PLZ"),
    ("city", "Ort"),
    ("email", "E-Mail"),
    ("phone", "Telefon"),
    ("tax_id", "Steuernummer"),
    ("vat_id", "USt-IdNr."),
]
BANK_FIELDS = [
    ("bank_name", "Bankname"),
    ("iban", "IBAN"),
    ("bic", "BIC"),
    ("account_holder", "Kontoinhaber"),
]


ALL_YEARS = "Alle Jahre"


class GoBDExportDialog(MessageBoxBase):
    def __init__(self, years: list, parent=None):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel("GoBD-Datenexport", self))
        text = BodyLabel("Für die Betriebsprüfung (Datenträgerüberlassung): alle steuerrelevanten Daten als CSV mit "
                         "Beschreibung (index.xml) für Prüfsoftware.", self)
        text.setWordWrap(True)
        self.viewLayout.addWidget(text)
        self.yearCombo = ComboBox(self)
        self.yearCombo.addItems([str(y) for y in years] + [ALL_YEARS])
        self.viewLayout.addWidget(self.yearCombo)
        self.documentsCheck = CheckBox("Archivierte Belege mitexportieren (Rechnungs-PDFs, Kassenbelege, Eingangsrechnungen)", self)
        self.documentsCheck.setChecked(True)
        self.viewLayout.addWidget(self.documentsCheck)
        self.yesButton.setText("Exportieren")
        self.cancelButton.setText("Abbrechen")
        self.widget.setMinimumWidth(460)

    def year(self):
        text = self.yearCombo.currentText()
        return None if text == ALL_YEARS else int(text)


class SettingsInterface(QWidget):
    integrityChecked = Signal(list)
    updateCheckRequested = Signal()
    backupFinished = Signal(str, str) # path, error message ("" = success)

    def __init__(self, db_controller: DBController, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("SettingsInterface")
        self.db_controller = db_controller
        self.edits = {}
        self._dirty = True
        SignalBus.get().settingsChanged.connect(self._mark_dirty)
        self.integrityChecked.connect(self._show_integrity_result)
        self.backupFinished.connect(self._on_backup_finished)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QVBoxLayout()
        header.setContentsMargins(36, 36, 36, 12)
        header.addWidget(SubtitleLabel("Einstellungen", self))
        self.pivot = Pivot(self)
        header.addWidget(self.pivot)
        layout.addLayout(header)

        self.stackedWidget = QStackedWidget(self)
        layout.addWidget(self.stackedWidget)
        self._add_tab("firm", "Firmendaten", self._build_firm_tab())
        self._add_tab("bank", "Bankdaten && Zahlungsziel", self._build_bank_tab())
        self._add_tab("security", "Sicherheit && GoBD", self._build_security_tab())
        self.pivot.setCurrentItem("firm")

        bottom = QHBoxLayout()
        bottom.setContentsMargins(36, 12, 36, 36)
        bottom.addStretch(1)
        self.saveBtn = PrimaryPushButton("Einstellungen speichern", self)
        self.saveBtn.clicked.connect(self.save_settings)
        bottom.addWidget(self.saveBtn)
        layout.addLayout(bottom)

    # --- UI ---
    def _add_tab(self, key: str, title: str, widget: QWidget):
        page = make_scrollable(widget)
        self.stackedWidget.addWidget(page)
        self.pivot.addItem(key, title, lambda: self.stackedWidget.setCurrentWidget(page))

    def _form_tab(self, fields, extra=None) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(36, 12, 36, 36)
        form = QFormLayout()
        form.setSpacing(14)
        for key, label in fields:
            edit = LineEdit(tab)
            edit.setFixedWidth(FIELD_WIDTH)
            form.addRow(BodyLabel(label), edit)
            self.edits[key] = edit
        if extra:
            # bandit B610 is a false positive: a local callback, not Django's QuerySet.extra
            extra(form, tab)  # nosec B610
        layout.addLayout(form)
        layout.addStretch(1)
        return tab

    def _build_firm_tab(self) -> QWidget:
        def extra(form, tab):
            logo = QHBoxLayout()
            self.logoPathEdit = LineEdit(tab)
            self.logoPathEdit.setReadOnly(True)
            self.logoPathEdit.setPlaceholderText("Kein Logo ausgewählt")
            self.logoPathEdit.setFixedWidth(FIELD_WIDTH)
            choose = PushButton("Auswählen", tab)
            choose.clicked.connect(self.select_logo)
            remove = PushButton("Entfernen", tab)
            remove.clicked.connect(self.logoPathEdit.clear)
            logo.addWidget(self.logoPathEdit)
            logo.addWidget(choose)
            logo.addWidget(remove)
            logo.addStretch(1)
            form.addRow(BodyLabel("Logo"), logo)
            # The own logo as it will appear on the documents
            self.logoPreview = QLabel(tab)
            self.logoPreview.setFixedHeight(LOGO_PREVIEW_HEIGHT)
            self.logoPreview.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.logoPathEdit.textChanged.connect(self._show_logo_preview)
            form.addRow(BodyLabel(""), self.logoPreview)
            self._show_logo_preview("")
            self.documentColorCombo = ComboBox(tab)
            self.documentColorCombo.setFixedWidth(FIELD_WIDTH)
            self.documentColorCombo.addItems(list(DOCUMENT_COLORS))
            self.documentColorCombo.setToolTip("Farbe des Programms und von Überschrift, Tabellenkopf und Gesamtbetrag "
                                               "in Rechnungen, Angeboten und Mahnungen")
            form.addRow(BodyLabel("Farbe (Programm und Dokumente)"), self.documentColorCombo)
            self.smallBusinessCheck = CheckBox("Kleinunternehmer gemäß § 19 UStG (keine Umsatzsteuer, neue Positionen mit 0 %)", tab)
            form.addRow(BodyLabel("Besteuerung"), self.smallBusinessCheck)
        tab = self._form_tab(FIRM_FIELDS, extra)
        # Own company: always in Germany
        self.edits["postal_code"].setValidator(german_postal_code_validator(self))
        self.edits["phone"].setValidator(phone_validator(self))
        self.edits["tax_id"].setPlaceholderText("z. B. 12/345/67890")
        # The slashes of the tax office format are inserted automatically
        attach_tax_number_format(self.edits["tax_id"])
        self.edits["vat_id"].setPlaceholderText("z. B. DE123456789")
        return tab

    def _build_bank_tab(self) -> QWidget:
        def extra(form, tab):
            # A plain field: in the spin box typed digits were appended to the shown value and refused above 365
            self.paymentTermsEdit = LineEdit(tab)
            self.paymentTermsEdit.setFixedWidth(FIELD_WIDTH)
            self.paymentTermsEdit.setValidator(QIntValidator(0, 365, self.paymentTermsEdit))
            self.paymentTermsEdit.setPlaceholderText(f"{DEFAULT_PAYMENT_TERMS} (0 = sofort)")
            form.addRow(BodyLabel("Standard-Zahlungsziel (Tage)"), self.paymentTermsEdit)
        return self._form_tab(BANK_FIELDS, extra)

    def _add_backup_section(self, layout: QVBoxLayout):
        layout.addWidget(SubtitleLabel("Backup & Wiederherstellung"))
        text = BodyLabel(
            "Exportiere alle Daten (Datenbank, archivierte Rechnungen, Belege) als eine .backup-Datei oder stelle ein Backup wieder her.\n"
            "Das Backup lässt sich auf jedem Computer einspielen. Bitte sicher aufbewahren (z. B. USB-Stick im Büro), "
            "es enthält alle Geschäftsdaten.\n"
            "Wichtig: Der Datenbankschlüssel ist an dieses Windows-Benutzerkonto gebunden. Bei Neuinstallation oder PC-Wechsel "
            "sind die Daten nur über ein Backup wiederherstellbar – bitte regelmäßig sichern.\n"
            "Achtung: Beim Import werden alle bestehenden Daten überschrieben und das Programm startet neu!")
        text.setWordWrap(True)
        layout.addWidget(text)
        layout.addSpacing(16)
        buttons = QHBoxLayout()
        self.exportBtn = PrimaryPushButton("Backup erstellen (Export)")
        self.exportBtn.clicked.connect(self.export_backup)
        self.importBtn = PushButton("Backup einspielen (Import)")
        self.importBtn.clicked.connect(self.import_backup)
        buttons.addWidget(self.exportBtn)
        buttons.addWidget(self.importBtn)
        buttons.addStretch(1)
        layout.addLayout(buttons)

    def _build_security_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(36, 12, 36, 36)
        layout.addWidget(SubtitleLabel("GoBD-Integritätsprüfung"))
        text = BodyLabel("Prüft die Hash-Ketten von Rechnungen, Kassenbuch und Verlauf, die Lückenlosigkeit der Rechnungs- "
                         "und Belegnummern, die erfassten Zahlungen sowie alle archivierten Dateien (Rechnungs-PDFs, Belege, "
                         "Eingangsrechnungen) auf Veränderungen.")
        text.setWordWrap(True)
        layout.addWidget(text)
        buttons = QHBoxLayout()
        self.integrityBtn = PushButton("Integrität prüfen")
        self.integrityBtn.clicked.connect(self.check_integrity)
        buttons.addWidget(self.integrityBtn)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addSpacing(24)
        layout.addWidget(SubtitleLabel("GoBD-Datenexport (Betriebsprüfung)"))
        text = BodyLabel("Exportiert Rechnungen, Positionen, Zahlungen, Kassenbuch, Eingangsrechnungen, Kunden und den "
                         "Verlauf als CSV-Dateien mit Beschreibung nach dem Standard der Finanzverwaltung (index.xml), "
                         "auf Wunsch mit allen archivierten Belegen.")
        text.setWordWrap(True)
        layout.addWidget(text)
        buttons = QHBoxLayout()
        self.gobdExportBtn = PushButton("Datenexport erstellen")
        self.gobdExportBtn.clicked.connect(self.export_gobd)
        buttons.addWidget(self.gobdExportBtn)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addSpacing(24)
        self._add_backup_section(layout)
        layout.addSpacing(24)
        layout.addWidget(SubtitleLabel("Datenablage"))
        location = BodyLabel(f"Datenordner: {paths.DATA_DIR}\nProtokoll: {paths.LOG_PATH}")
        location.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(location)
        layout.addSpacing(24)
        layout.addWidget(SubtitleLabel(f"Über {APP_NAME}"))
        self.aboutLabel = BodyLabel(f"Version {APP_VERSION}\nAutor: {APP_AUTHOR}")
        self.aboutLabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.aboutLabel)
        buttons = QHBoxLayout()
        self.updateBtn = PushButton("Nach Update suchen")
        self.updateBtn.clicked.connect(self.updateCheckRequested)
        buttons.addWidget(self.updateBtn)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addStretch(1)
        return tab

    # --- Load / save ---
    def _mark_dirty(self):
        self._dirty = True

    def showEvent(self, event):
        super().showEvent(event)
        if self._dirty:
            self.load_settings()

    def load_settings(self):
        self._dirty = False
        for key, edit in self.edits.items():
            edit.setText(self.db_controller.get_setting(key))
        self.logoPathEdit.setText(paths.resolve(self.db_controller.get_setting("logo_path")))
        self.smallBusinessCheck.setChecked(self.db_controller.is_small_business())
        color = self.db_controller.get_setting("document_color", DEFAULT_DOCUMENT_COLOR)
        self.documentColorCombo.setCurrentText(color if color in DOCUMENT_COLORS else DEFAULT_DOCUMENT_COLOR)
        self.paymentTermsEdit.setText(str(self.db_controller.get_payment_terms()))

    def _validate(self, values: dict) -> list:
        problems = []
        if values["iban"] and not stdnum_iban.is_valid(values["iban"]):
            problems.append("Die IBAN ist ungültig (Prüfziffer).")
        if values["bic"] and not stdnum_bic.is_valid(values["bic"]):
            problems.append("Die BIC ist ungültig.")
        problems += contact_problems(values, "der Firma")
        if values["tax_id"] and not is_valid_tax_number(values["tax_id"]):
            problems.append("Die Steuernummer ist ungültig (Format des Finanzamts, z. B. 12/345/67890).")
        if values["vat_id"] and not stdnum_vat.is_valid(values["vat_id"]):
            problems.append("Die USt-IdNr. ist ungültig (Format/Prüfziffer).")
        return problems

    def save_settings(self):
        values = {key: edit.text().strip() for key, edit in self.edits.items()}
        values["iban"] = stdnum_iban.compact(values["iban"]) if values["iban"] else ""
        values["vat_id"] = values["vat_id"].replace(" ", "").upper()
        problems = self._validate(values)
        if problems:
            show_message(self, "Bitte prüfen", "\n".join(problems))
            return

        logo_path = self.logoPathEdit.text()
        in_assets = os.path.normcase(os.path.abspath(logo_path)).startswith(os.path.normcase(os.path.abspath(paths.ASSETS_DIR)) + os.sep)
        if logo_path and os.path.isfile(logo_path) and not in_assets:
            # Copied into the data folder, so the logo stays available (and is part of backups). A new name each
            # time: a logo restored from a backup is read-only and must not be overwritten.
            os.makedirs(paths.ASSETS_DIR, exist_ok=True)
            new_path = os.path.join(paths.ASSETS_DIR, f"logo_{datetime.now():%Y%m%d%H%M%S}{os.path.splitext(logo_path)[1].lower()}")
            try:
                shutil.copyfile(logo_path, new_path)
            except OSError as e:
                notify_error(self, "Logo nicht übernommen", str(e))
                return
            logo_path = new_path
            self.logoPathEdit.setText(logo_path)

        values.update({
            "logo_path": logo_path,
            "small_business": "1" if self.smallBusinessCheck.isChecked() else "0",
            "document_color": self.documentColorCombo.currentText(),
            "payment_terms_days": self.paymentTermsEdit.text().strip() or str(DEFAULT_PAYMENT_TERMS),
        })
        # One save for all values (each save re-encrypts the whole database)
        self.db_controller.set_settings(values)
        notify_success(self, "Gespeichert", "Die Einstellungen wurden gespeichert.")

    def select_logo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Logo auswählen", paths.downloads_dir(), "Bilder (*.png *.jpg *.jpeg)")
        if not path:
            return
        if QImageReader(path).read().isNull():
            notify_error(self, "Kein Bild", f"{os.path.basename(path)} lässt sich nicht als Bild öffnen.")
            return
        self.logoPathEdit.setText(path)
        notify_success(self, "Logo ausgewählt", "Wird mit „Einstellungen speichern“ übernommen.")

    def _show_logo_preview(self, path: str):
        pixmap = QPixmap(path) if path and os.path.isfile(path) else QPixmap()
        self.logoPreview.setVisible(not pixmap.isNull())
        if not pixmap.isNull():
            self.logoPreview.setPixmap(pixmap.scaled(LOGO_PREVIEW_WIDTH, LOGO_PREVIEW_HEIGHT, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    # --- Integrity ---
    def check_integrity(self):
        # Hashing all archived files can take a while; the check runs in the background
        self.integrityBtn.setEnabled(False)
        self.integrityBtn.setText("Prüfung läuft...")
        self.db_controller.verify_integrity_async(self.integrityChecked.emit, check_files=True)

    def _show_integrity_result(self, problems: list):
        self.integrityBtn.setEnabled(True)
        self.integrityBtn.setText("Integrität prüfen")
        if problems:
            text = "\n".join(problems[:20])
            if len(problems) > 20:
                text += f"\n… und {len(problems) - 20} weitere"
            show_message(self, "Integritätsprüfung: Abweichungen gefunden", text)
        else:
            show_message(self, "Integritätsprüfung", "Alle Hash-Ketten und archivierten Dateien sind unverändert.")

    # --- Backup ---
    def export_gobd(self):
        from src.utils.gobd_export import export_gobd
        c = self.db_controller
        years = {datetime.now().year}
        years.update(i.invoice_date.year for i in c.get_invoices() if c.is_finalized(i))
        years.update(e.entry_date.year for e in c.get_cashbook_entries())
        years.update(i.date.year for i in c.get_incoming_invoices())
        dialog = GoBDExportDialog(sorted(years, reverse=True), self.window())
        if not dialog.exec():
            return
        year = dialog.year()
        name = f"GoBD_Export_{year or 'alle_Jahre'}_{datetime.now():%Y%m%d}.zip"
        target, _ = QFileDialog.getSaveFileName(self, "GoBD-Datenexport speichern", paths.desktop_path(name), "ZIP (*.zip)")
        if not target:
            return
        try:
            counts = export_gobd(c, target, year, dialog.documentsCheck.isChecked())
        except Exception as e:
            logger.exception("GoBD-Datenexport fehlgeschlagen")
            notify_error(self, "Export fehlgeschlagen", f"{e}\nDetails: {paths.LOG_PATH}")
            return
        summary = ", ".join(f"{name}: {count}" for name, count in counts.items())
        c.log_actions("Export", [0], f"GoBD-Datenexport ({year or 'alle Jahre'}): {summary}")
        notify_success(self, "GoBD-Datenexport erstellt", target, duration=5000)

    def _backup_folders(self) -> dict:
        return {"app_data": paths.APP_DATA_DIR, "assets": paths.ASSETS_DIR}

    def export_backup(self):
        path, _ = QFileDialog.getSaveFileName(self, "Backup speichern unter...",
                                              paths.desktop_path(f"Schalk_Backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.backup"),
                                              BACKUP_FILTER)
        if not path:
            return
        # The state of this moment; packing all documents runs in the background
        snapshot, folders = self.db_controller.db.snapshot(), self._backup_folders()
        self.exportBtn.setEnabled(False)
        self.exportBtn.setText("Backup wird erstellt...")

        def run():
            error = ""
            try:
                create_backup(snapshot, path, folders)
            except Exception as e:
                logger.exception("Backup fehlgeschlagen")
                error = str(e) or type(e).__name__
            try:
                self.backupFinished.emit(path, error)
            except RuntimeError:
                pass # window already closed; the backup itself is complete

        # Not a daemon: when Schalk is closed meanwhile, the backup is still finished
        threading.Thread(target=run, name="schalk-backup").start()

    def _on_backup_finished(self, path: str, error: str):
        if not error:
            # For the monthly backup reminder at start
            self.db_controller.set_setting("last_backup", datetime.now().isoformat(timespec="seconds"))
        self.exportBtn.setEnabled(True)
        self.exportBtn.setText("Backup erstellen (Export)")
        if error:
            notify_error(self, "Fehler beim Export", error)
        else:
            notify_success(self, "Backup erstellt", path, duration=5000)

    def import_backup(self):
        path, _ = QFileDialog.getOpenFileName(self, "Backup auswählen", paths.downloads_dir(), BACKUP_FILTER)
        if not path or not confirm(self, "Backup einspielen",
                                   "Achtung: Dies überschreibt alle aktuellen Daten!\n"
                                   "Die bisherige Datenbank wird als .bak-Datei aufbewahrt. Das Programm startet danach neu.\n\n"
                                   "Möchtest du fortfahren?"):
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            restore_backup(self.db_controller.db, path, self._backup_folders())
        except Exception as e:
            logger.exception("Backup-Import fehlgeschlagen")
            notify_error(self, "Fehler beim Import", str(e))
            return
        finally:
            QApplication.restoreOverrideCursor()

        # Restart: the running instance must not write its old state over the restored database
        arguments = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
        QProcess.startDetached(sys.executable, arguments)
        QApplication.quit()
