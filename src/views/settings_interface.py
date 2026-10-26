import logging
import os
import shutil
import sys
import tempfile
import zipfile
from datetime import datetime
from PySide6.QtCore import QProcess, Qt, Signal
from PySide6.QtWidgets import QApplication, QFileDialog, QFormLayout, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CheckBox, LineEdit, Pivot, PrimaryPushButton, PushButton, SpinBox, SubtitleLabel
from stdnum import bic as stdnum_bic, iban as stdnum_iban
from stdnum.eu import vat as stdnum_vat
from src.controllers.db_controller import DBController, DEFAULT_PAYMENT_TERMS
from src.models.database import WrongPasswordError
from src.utils import paths
from src.utils.signal_bus import SignalBus
from src.views.backup_password_dialog import BackupPasswordDialog
from src.views.common import confirm, notify_error, notify_success, show_message

logger = logging.getLogger(__name__)

FIRM_FIELDS = [
    ("company_name", "Firmenname"),
    ("first_name", "Ansprechpartner Vorname"),
    ("last_name", "Ansprechpartner Nachname"),
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


class SettingsInterface(QWidget):
    integrityChecked = Signal(list)

    def __init__(self, db_controller: DBController, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("SettingsInterface")
        self.db_controller = db_controller
        self.edits = {}
        self._dirty = True
        SignalBus.get().settingsChanged.connect(self._mark_dirty)
        self.integrityChecked.connect(self._show_integrity_result)

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
        self._add_tab("bank", "Bankdaten", self._form_tab(BANK_FIELDS))
        self._add_tab("payment", "Zahlungsziel", self._build_payment_tab())
        self._add_tab("backup", "Backup", self._build_backup_tab())
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
        self.stackedWidget.addWidget(widget)
        self.pivot.addItem(key, title, lambda: self.stackedWidget.setCurrentWidget(widget))

    def _form_tab(self, fields, extra=None) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(36, 12, 36, 36)
        form = QFormLayout()
        form.setSpacing(14)
        for key, label in fields:
            edit = LineEdit(tab)
            form.addRow(BodyLabel(label), edit)
            self.edits[key] = edit
        if extra:
            extra(form, tab)
        layout.addLayout(form)
        layout.addStretch(1)
        return tab

    def _build_firm_tab(self) -> QWidget:
        def extra(form, tab):
            logo = QHBoxLayout()
            self.logoPathEdit = LineEdit(tab)
            self.logoPathEdit.setReadOnly(True)
            self.logoPathEdit.setPlaceholderText("Kein Logo ausgewählt")
            choose = PushButton("Auswählen", tab)
            choose.clicked.connect(self.select_logo)
            remove = PushButton("Entfernen", tab)
            remove.clicked.connect(self.logoPathEdit.clear)
            logo.addWidget(self.logoPathEdit)
            logo.addWidget(choose)
            logo.addWidget(remove)
            form.addRow(BodyLabel("Logo"), logo)
            self.smallBusinessCheck = CheckBox("Kleinunternehmer gemäß § 19 UStG (keine Umsatzsteuer, neue Positionen mit 0 %)", tab)
            form.addRow(BodyLabel("Besteuerung"), self.smallBusinessCheck)
        return self._form_tab(FIRM_FIELDS, extra)

    def _build_payment_tab(self) -> QWidget:
        def extra(form, tab):
            self.paymentTermsSpin = SpinBox(tab)
            self.paymentTermsSpin.setRange(0, 365)
            form.addRow(BodyLabel("Standard-Zahlungsziel (Tage)"), self.paymentTermsSpin)
        return self._form_tab([], extra)

    def _build_backup_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(36, 12, 36, 36)
        layout.addWidget(SubtitleLabel("Backup & Wiederherstellung"))
        text = BodyLabel(
            "Exportiere alle Daten (Datenbank, archivierte Rechnungen, Belege) als ZIP-Archiv oder stelle ein Backup wieder her.\n"
            "Die Datenbank im Backup wird mit einem Backup-Passwort verschlüsselt und lässt sich damit auf jedem Computer einspielen.\n"
            "Wichtig: Der Datenbankschlüssel ist an dieses Windows-Benutzerkonto gebunden. Bei Neuinstallation oder PC-Wechsel "
            "sind die Daten nur über ein Backup wiederherstellbar – bitte regelmäßig sichern.\n"
            "Achtung: Beim Import werden alle bestehenden Daten überschrieben und das Programm startet neu!")
        text.setWordWrap(True)
        layout.addWidget(text)
        layout.addSpacing(16)
        buttons = QHBoxLayout()
        export_btn = PrimaryPushButton("Backup erstellen (Export)")
        export_btn.clicked.connect(self.export_backup)
        import_btn = PushButton("Backup einspielen (Import)")
        import_btn.clicked.connect(self.import_backup)
        buttons.addWidget(export_btn)
        buttons.addWidget(import_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addStretch(1)
        return tab

    def _build_security_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(36, 12, 36, 36)
        layout.addWidget(SubtitleLabel("GoBD-Integritätsprüfung"))
        text = BodyLabel("Prüft die Hash-Ketten von Rechnungen und Kassenbuch sowie alle archivierten Dateien "
                         "(Rechnungs-PDFs, Belege, Eingangsrechnungen) auf Veränderungen.")
        text.setWordWrap(True)
        layout.addWidget(text)
        buttons = QHBoxLayout()
        self.integrityBtn = PushButton("Integrität prüfen")
        self.integrityBtn.clicked.connect(self.check_integrity)
        buttons.addWidget(self.integrityBtn)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addSpacing(16)
        layout.addWidget(SubtitleLabel("Datenablage"))
        location = BodyLabel(f"Datenordner: {paths.DATA_DIR}\nProtokoll: {paths.LOG_PATH}")
        location.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(location)
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
        self.logoPathEdit.setText(self.db_controller.get_setting("logo_path"))
        self.smallBusinessCheck.setChecked(self.db_controller.is_small_business())
        self.paymentTermsSpin.setValue(self.db_controller.get_payment_terms())

    def _validate(self, values: dict) -> list:
        problems = []
        if values["iban"] and not stdnum_iban.is_valid(values["iban"]):
            problems.append("Die IBAN ist ungültig (Prüfziffer).")
        if values["bic"] and not stdnum_bic.is_valid(values["bic"]):
            problems.append("Die BIC ist ungültig.")
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
        if logo_path and os.path.isfile(logo_path) and not os.path.abspath(logo_path).startswith(paths.ASSETS_DIR):
            # Copy into the data folder so the logo stays available
            os.makedirs(paths.ASSETS_DIR, exist_ok=True)
            new_path = os.path.join(paths.ASSETS_DIR, f"logo{os.path.splitext(logo_path)[1].lower()}")
            shutil.copyfile(logo_path, new_path)
            logo_path = new_path
            self.logoPathEdit.setText(logo_path)

        values.update({
            "logo_path": logo_path,
            "small_business": "1" if self.smallBusinessCheck.isChecked() else "0",
            "payment_terms_days": str(self.paymentTermsSpin.value() if self.paymentTermsSpin.value() is not None else DEFAULT_PAYMENT_TERMS),
        })
        # One save for all values (each save re-encrypts the whole database)
        self.db_controller.set_settings(values)
        notify_success(self, "Gespeichert", "Die Einstellungen wurden gespeichert.")

    def select_logo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Logo auswählen", "", "Bilder (*.png *.jpg *.jpeg)")
        if path:
            self.logoPathEdit.setText(path)

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
    def export_backup(self):
        path, _ = QFileDialog.getSaveFileName(self, "Backup speichern unter...",
                                              paths.desktop_path(f"Schalk_Backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"),
                                              "ZIP-Archiv (*.zip)")
        if not path:
            return
        dialog = BackupPasswordDialog("create", parent=self.window())
        if not dialog.exec():
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                db_file = os.path.join(tmpdir, "schalk.backup")
                self.db_controller.db.export_backup(db_file, dialog.password())
                with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zipf:
                    zipf.write(db_file, "schalk.backup")
                    for folder, name in ((paths.APP_DATA_DIR, "app_data"), (paths.ASSETS_DIR, "assets")):
                        for root, _, files in os.walk(folder):
                            for file in files:
                                full = os.path.join(root, file)
                                zipf.write(full, os.path.join(name, os.path.relpath(full, folder)))
        except Exception as e:
            logger.exception("Backup fehlgeschlagen")
            notify_error(self, "Fehler beim Export", str(e))
            return
        finally:
            QApplication.restoreOverrideCursor()
        notify_success(self, "Backup erstellt", path, duration=5000)

    def import_backup(self):
        path, _ = QFileDialog.getOpenFileName(self, "Backup auswählen", "", "ZIP-Archiv (*.zip)")
        if not path or not confirm(self, "Backup einspielen",
                                   "Achtung: Dies überschreibt alle aktuellen Daten!\n"
                                   "Die bisherige Datenbank wird als .bak-Datei aufbewahrt. Das Programm startet danach neu.\n\n"
                                   "Möchtest du fortfahren?"):
            return
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                with zipfile.ZipFile(path) as zipf:
                    zipf.extractall(tmpdir)
                db_file = os.path.join(tmpdir, "schalk.backup")
                if not os.path.exists(db_file):
                    raise ValueError("Die ZIP-Datei enthält keine gültige Datenbank (schalk.backup).")
                with open(db_file, "rb") as f:
                    data = f.read()

                message = ""
                while True:
                    dialog = BackupPasswordDialog("unlock", message, parent=self.window())
                    if not dialog.exec():
                        return
                    try:
                        # The writer is flushed first so the .bak copy is complete
                        self.db_controller.db.flush()
                        if os.path.exists(paths.DB_PATH):
                            shutil.copy2(paths.DB_PATH, f"{paths.DB_PATH}.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}")
                        self.db_controller.db.restore_backup(data, dialog.password())
                        break
                    except WrongPasswordError as e:
                        message = str(e)

                def copy_missing(src, dst):
                    # Archived documents are read-only and must not be overwritten
                    if not os.path.exists(dst):
                        shutil.copy2(src, dst)
                for folder, target in (("app_data", paths.APP_DATA_DIR), ("assets", paths.ASSETS_DIR)):
                    if os.path.isdir(os.path.join(tmpdir, folder)):
                        shutil.copytree(os.path.join(tmpdir, folder), target, dirs_exist_ok=True, copy_function=copy_missing)
        except Exception as e:
            logger.exception("Backup-Import fehlgeschlagen")
            notify_error(self, "Fehler beim Import", str(e))
            return

        # Restart: the running instance must not write its old state over the restored database
        arguments = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
        QProcess.startDetached(sys.executable, arguments)
        QApplication.quit()
