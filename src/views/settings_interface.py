from qfluentwidgets import Pivot
from qfluentwidgets import BodyLabel, InfoBar, InfoBarPosition, LineEdit, PrimaryPushButton, PushButton, SubtitleLabel
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget
from src.controllers.db_controller import DBController
import os
from src.utils.signal_bus import SignalBus
from src.utils import paths


class SettingsInterface(QWidget):
    def __init__(self, db_controller: DBController, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("SettingsInterface")
        self.db_controller = db_controller
        
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        
        self.init_ui()
        self.load_settings()
        self._needs_reload = True
        SignalBus.get().dataChanged.connect(self.mark_dirty)

    def mark_dirty(self):
        self._needs_reload = True

    def showEvent(self, event):
        super().showEvent(event)
        self.load_settings()

    def init_ui(self):
        # Header area with Pivot
        headerLayout = QVBoxLayout()
        headerLayout.setContentsMargins(36, 36, 36, 12)
        
        self.titleLabel = SubtitleLabel("Einstellungen", self)
        headerLayout.addWidget(self.titleLabel)
        
        self.pivot = Pivot(self)
        headerLayout.addWidget(self.pivot)
        self.vBoxLayout.addLayout(headerLayout)
        
        self.stackedWidget = QStackedWidget(self)
        self.vBoxLayout.addWidget(self.stackedWidget)
        
        # Firmendaten Tab
        self.firmTab = QWidget()
        firmLayout = QVBoxLayout(self.firmTab)
        firmLayout.setContentsMargins(36, 12, 36, 36)
        
        self.formLayout = QFormLayout()
        self.formLayout.setSpacing(16)
        
        self.companyNameEdit = LineEdit(self)
        self.formLayout.addRow(BodyLabel("Firmenname"), self.companyNameEdit)
        
        self.firstNameEdit = LineEdit(self)
        self.formLayout.addRow(BodyLabel("Vorname"), self.firstNameEdit)
        
        self.lastNameEdit = LineEdit(self)
        self.formLayout.addRow(BodyLabel("Nachname"), self.lastNameEdit)
        
        self.addressEdit = LineEdit(self)
        self.formLayout.addRow(BodyLabel("Straße & Hausnummer"), self.addressEdit)
        
        self.postalCodeEdit = LineEdit(self)
        self.formLayout.addRow(BodyLabel("PLZ"), self.postalCodeEdit)
        
        self.cityEdit = LineEdit(self)
        self.formLayout.addRow(BodyLabel("Ort"), self.cityEdit)
        
        self.emailEdit = LineEdit(self)
        self.formLayout.addRow(BodyLabel("E-Mail"), self.emailEdit)
        
        self.phoneEdit = LineEdit(self)
        self.formLayout.addRow(BodyLabel("Telefon"), self.phoneEdit)
        
        self.taxIdEdit = LineEdit(self)
        self.formLayout.addRow(BodyLabel("Steuernummer"), self.taxIdEdit)
        
        self.vatIdEdit = LineEdit(self)
        self.formLayout.addRow(BodyLabel("USt-IdNr."), self.vatIdEdit)
        
        # Logo Select
        logoLayout = QHBoxLayout()
        self.logoPathEdit = LineEdit(self)
        self.logoPathEdit.setReadOnly(True)
        self.logoPathEdit.setPlaceholderText("Kein Logo ausgewählt")
        self.logoBtn = PushButton("Auswählen", self)
        self.logoBtn.clicked.connect(self.select_logo)
        self.logoClearBtn = PushButton("Entfernen", self)
        self.logoClearBtn.clicked.connect(lambda: self.logoPathEdit.clear())
        logoLayout.addWidget(self.logoPathEdit)
        logoLayout.addWidget(self.logoBtn)
        logoLayout.addWidget(self.logoClearBtn)
        self.formLayout.addRow(BodyLabel("Logo"), logoLayout)
        
        firmLayout.addLayout(self.formLayout)
        firmLayout.addStretch(1)
        
        # Bankdaten Tab
        self.bankTab = QWidget()
        bankLayout = QVBoxLayout(self.bankTab)
        bankLayout.setContentsMargins(36, 12, 36, 36)
        
        self.bankFormLayout = QFormLayout()
        self.bankFormLayout.setSpacing(16)
        
        self.bankNameEdit = LineEdit(self)
        self.bankFormLayout.addRow(BodyLabel("Bankname"), self.bankNameEdit)
        
        self.ibanEdit = LineEdit(self)
        self.bankFormLayout.addRow(BodyLabel("IBAN"), self.ibanEdit)
        
        self.bicEdit = LineEdit(self)
        self.bankFormLayout.addRow(BodyLabel("BIC"), self.bicEdit)
        
        self.accountHolderEdit = LineEdit(self)
        self.bankFormLayout.addRow(BodyLabel("Kontoinhaber"), self.accountHolderEdit)
        
        bankLayout.addLayout(self.bankFormLayout)
        bankLayout.addStretch(1)
        
        # Zahlungsziel Tab
        self.paymentTab = QWidget()
        paymentLayout = QVBoxLayout(self.paymentTab)
        paymentLayout.setContentsMargins(36, 12, 36, 36)
        
        self.paymentFormLayout = QFormLayout()
        self.paymentFormLayout.setSpacing(16)
        
        from qfluentwidgets import SpinBox
        self.paymentTermsSpin = SpinBox(self)
        self.paymentTermsSpin.setMinimum(0)
        self.paymentTermsSpin.setMaximum(365)
        self.paymentTermsSpin.setValue(14)
        self.paymentFormLayout.addRow(BodyLabel("Standard Zahlungsziel (Tage)"), self.paymentTermsSpin)
        
        paymentLayout.addLayout(self.paymentFormLayout)
        paymentLayout.addStretch(1)
        
        self.stackedWidget.addWidget(self.firmTab)
        self.stackedWidget.addWidget(self.bankTab)
        self.stackedWidget.addWidget(self.paymentTab)
        
        # DATEV Tab
        self.datevTab = QWidget()
        datevLayout = QVBoxLayout(self.datevTab)
        datevLayout.setContentsMargins(36, 12, 36, 36)
        
        self.datevFormLayout = QFormLayout()
        self.datevFormLayout.setSpacing(16)
        
        self.datevBeraterEdit = LineEdit(self)
        self.datevBeraterEdit.setPlaceholderText("z.B. 123456")
        self.datevFormLayout.addRow(BodyLabel("DATEV Beraternummer"), self.datevBeraterEdit)
        
        self.datevMandantEdit = LineEdit(self)
        self.datevMandantEdit.setPlaceholderText("z.B. 12345")
        self.datevFormLayout.addRow(BodyLabel("DATEV Mandantennummer"), self.datevMandantEdit)
        
        self.datevAccount19Edit = LineEdit(self)
        self.datevAccount19Edit.setPlaceholderText("z.B. 8400 (SKR03) oder 4400 (SKR04)")
        self.datevFormLayout.addRow(BodyLabel("Erlöskonto (19% MwSt.)"), self.datevAccount19Edit)
        
        self.datevAccountKasseEdit = LineEdit(self)
        self.datevAccountKasseEdit.setPlaceholderText("z.B. 1000 (SKR03) oder 1600 (SKR04)")
        self.datevFormLayout.addRow(BodyLabel("Kassen-Konto"), self.datevAccountKasseEdit)
        
        datevLayout.addLayout(self.datevFormLayout)
        datevLayout.addStretch(1)
        
        self.stackedWidget.addWidget(self.datevTab)
        
        # Backup Tab
        self.backupTab = QWidget()
        backupLayout = QVBoxLayout(self.backupTab)
        backupLayout.setContentsMargins(36, 12, 36, 36)
        
        backupTitle = SubtitleLabel("Backup & Wiederherstellung")
        backupDesc = BodyLabel("Exportiere alle Daten (inkl. Datenbank und PDFs) als ZIP-Archiv oder stelle ein Backup wieder her.\n"
                               "Die Datenbank im Backup wird mit einem Backup-Passwort verschlüsselt und lässt sich damit auf jedem Computer einspielen.\n"
                               "Wichtig: Der Datenbankschlüssel ist an dieses Windows-Benutzerkonto gebunden. Bei Neuinstallation oder PC-Wechsel sind die Daten nur über ein Backup wiederherstellbar.\n"
                               "Achtung: Beim Import werden alle bestehenden Daten überschrieben und das Programm startet neu!")
        
        btnLayout = QHBoxLayout()
        self.exportBtn = PrimaryPushButton("Backup erstellen (Export)")
        self.exportBtn.clicked.connect(self.export_backup)
        
        self.importBtn = PushButton("Backup einspielen (Import)")
        self.importBtn.clicked.connect(self.import_backup)
        
        btnLayout.addWidget(self.exportBtn)
        btnLayout.addWidget(self.importBtn)
        btnLayout.addStretch(1)
        
        backupLayout.addWidget(backupTitle)
        backupLayout.addWidget(backupDesc)
        backupLayout.addSpacing(16)
        backupLayout.addLayout(btnLayout)
        backupLayout.addStretch(1)
        
        self.stackedWidget.addWidget(self.backupTab)
        
        # Sicherheit & GoBD Tab
        self.securityTab = QWidget()
        securityLayout = QVBoxLayout(self.securityTab)
        securityLayout.setContentsMargins(36, 12, 36, 36)
        
        securityLayout.addWidget(SubtitleLabel("GoBD-Integritätsprüfung"))
        securityLayout.addWidget(BodyLabel("Prüft die Hash-Ketten von Rechnungen und Kassenbuch sowie alle archivierten Dateien auf Veränderungen."))
        checkBtnLayout = QHBoxLayout()
        self.integrityBtn = PushButton("Integrität prüfen")
        self.integrityBtn.clicked.connect(self.check_integrity)
        checkBtnLayout.addWidget(self.integrityBtn)
        checkBtnLayout.addStretch(1)
        securityLayout.addLayout(checkBtnLayout)
        securityLayout.addStretch(1)
        
        self.stackedWidget.addWidget(self.securityTab)
        
        # Link pivot to stackedWidget
        self.pivot.addItem("firm", "Firmendaten", lambda: self.stackedWidget.setCurrentIndex(0))
        self.pivot.addItem("bank", "Bankdaten", lambda: self.stackedWidget.setCurrentIndex(1))
        self.pivot.addItem("payment", "Zahlungsziel", lambda: self.stackedWidget.setCurrentIndex(2))
        self.pivot.addItem("datev", "DATEV", lambda: self.stackedWidget.setCurrentIndex(3))
        self.pivot.addItem("backup", "Backup", lambda: self.stackedWidget.setCurrentIndex(4))
        self.pivot.addItem("security", "Sicherheit & GoBD", lambda: self.stackedWidget.setCurrentIndex(5))
        self._pivot_items = ["firm", "bank", "payment", "datev", "backup", "security"]
        self.pivot.setCurrentItem("firm")
        self.stackedWidget.currentChanged.connect(lambda i: self.pivot.setCurrentItem(self._pivot_items[i]))
        
        # Speichern Button Bottom
        bottomLayout = QHBoxLayout()
        bottomLayout.setContentsMargins(36, 12, 36, 36)
        self.saveBtn = PrimaryPushButton("Einstellungen speichern", self)
        self.saveBtn.clicked.connect(self.save_settings)
        bottomLayout.addStretch(1)
        bottomLayout.addWidget(self.saveBtn)
        self.vBoxLayout.addLayout(bottomLayout)

    def load_settings(self):
        self.companyNameEdit.setText(self.db_controller.get_setting("company_name"))
        self.firstNameEdit.setText(self.db_controller.get_setting("first_name"))
        self.lastNameEdit.setText(self.db_controller.get_setting("last_name"))
        self.addressEdit.setText(self.db_controller.get_setting("address"))
        self.postalCodeEdit.setText(self.db_controller.get_setting("postal_code"))
        self.cityEdit.setText(self.db_controller.get_setting("city"))
        self.taxIdEdit.setText(self.db_controller.get_setting("tax_id"))
        self.vatIdEdit.setText(self.db_controller.get_setting("vat_id"))
        self.emailEdit.setText(self.db_controller.get_setting("email"))
        self.phoneEdit.setText(self.db_controller.get_setting("phone"))
        self.logoPathEdit.setText(self.db_controller.get_setting("logo_path"))
        
        self.bankNameEdit.setText(self.db_controller.get_setting("bank_name"))
        self.ibanEdit.setText(self.db_controller.get_setting("iban"))
        self.bicEdit.setText(self.db_controller.get_setting("bic"))
        self.accountHolderEdit.setText(self.db_controller.get_setting("account_holder"))
        
        payment_terms = self.db_controller.get_setting("payment_terms_days")
        if payment_terms:
            try:
                self.paymentTermsSpin.setValue(int(payment_terms))
            except ValueError:
                self.paymentTermsSpin.setValue(14)
        else:
            self.paymentTermsSpin.setValue(14)
            
        self.datevBeraterEdit.setText(self.db_controller.get_setting("datev_berater"))
        self.datevMandantEdit.setText(self.db_controller.get_setting("datev_mandant"))
        self.datevAccount19Edit.setText(self.db_controller.get_setting("datev_account_19"))
        
        kasse = self.db_controller.get_setting("datev_account_kasse")
        self.datevAccountKasseEdit.setText(kasse if kasse else "1000")

    def save_settings(self):
        import shutil
        # Handle logo
        logo_path = self.logoPathEdit.text()
        if logo_path and os.path.exists(logo_path) and not os.path.abspath(logo_path).startswith(paths.ASSETS_DIR):
            # Copy to assets folder to ensure it stays available
            os.makedirs(paths.ASSETS_DIR, exist_ok=True)
            ext = os.path.splitext(logo_path)[1]
            new_path = os.path.join(paths.ASSETS_DIR, f"logo{ext}")
            try:
                shutil.copy2(logo_path, new_path)
                logo_path = new_path
                self.logoPathEdit.setText(logo_path)
            except Exception as e:
                print(f"Error copying logo: {e}")
                
        # One save for all values (each save re-encrypts the whole database)
        self.db_controller.set_settings({
            "company_name": self.companyNameEdit.text(),
            "first_name": self.firstNameEdit.text(),
            "last_name": self.lastNameEdit.text(),
            "address": self.addressEdit.text(),
            "postal_code": self.postalCodeEdit.text(),
            "city": self.cityEdit.text(),
            "tax_id": self.taxIdEdit.text(),
            "vat_id": self.vatIdEdit.text(),
            "email": self.emailEdit.text(),
            "phone": self.phoneEdit.text(),
            "logo_path": logo_path,
            "bank_name": self.bankNameEdit.text(),
            "iban": self.ibanEdit.text(),
            "bic": self.bicEdit.text(),
            "account_holder": self.accountHolderEdit.text(),
            "payment_terms_days": str(self.paymentTermsSpin.value()),
            "datev_berater": self.datevBeraterEdit.text(),
            "datev_mandant": self.datevMandantEdit.text(),
            "datev_account_19": self.datevAccount19Edit.text(),
            "datev_account_kasse": self.datevAccountKasseEdit.text(),
        })
        
        InfoBar.success(
            title="Gespeichert",
            content="Die Einstellungen wurden erfolgreich gespeichert.",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self.window()
        )

    def select_logo(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Logo auswählen",
            "",
            "Bilder (*.png *.jpg *.jpeg)"
        )
        if path:
            self.logoPathEdit.setText(path)

    def export_backup(self):
        from PySide6.QtWidgets import QFileDialog
        from datetime import datetime
        import shutil
        import tempfile
        import os
        
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Backup speichern unter...",
            f"Schalk_Backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
            "ZIP-Archiv (*.zip)"
        )
        if not path:
            return
            
        from src.views.backup_password_dialog import BackupPasswordDialog
        dialog = BackupPasswordDialog("create", parent=self.window())
        if not dialog.exec():
            return
            
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                # Database encrypted with the backup password (portable to other computers)
                self.db_controller.db.export_backup(os.path.join(tmpdir, "schalk.backup"), dialog.password())
                
                # Copy app_data if exists
                if os.path.exists(paths.APP_DATA_DIR):
                    shutil.copytree(paths.APP_DATA_DIR, os.path.join(tmpdir, "app_data"))
                    
                # Copy assets if exists (for logos)
                if os.path.exists(paths.ASSETS_DIR):
                    shutil.copytree(paths.ASSETS_DIR, os.path.join(tmpdir, "assets"))
                
                # Zip it
                base_name = os.path.splitext(path)[0]
                shutil.make_archive(base_name, 'zip', tmpdir)
                
            InfoBar.success(
                title="Backup erstellt",
                content=f"Das Backup wurde erfolgreich unter {path} gespeichert.",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=4000,
                parent=self.window()
            )
        except Exception as e:
            InfoBar.error(
                title="Fehler beim Export",
                content=str(e),
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self.window()
            )

    def import_backup(self):
        from PySide6.QtWidgets import QFileDialog
        from qfluentwidgets import MessageBox
        import shutil
        import tempfile
        import sys
        import os
        
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Backup auswählen",
            "",
            "ZIP-Archiv (*.zip)"
        )
        if not path:
            return
            
        # Warning Dialog
        w = MessageBox(
            "Backup einspielen",
            "Achtung: Dies überschreibt alle aktuellen Daten unwiderruflich!\nDas Programm wird nach dem Import automatisch neu gestartet.\n\nMöchtest du fortfahren?",
            self.window()
        )
        w.yesButton.setText("Ja")
        w.cancelButton.setText("Nein")
        if not w.exec():
            return
            
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                shutil.unpack_archive(path, tmpdir)
                
                # Verify valid backup
                db_file = os.path.join(tmpdir, "schalk.backup")
                if not os.path.exists(db_file):
                    raise Exception("Die ZIP-Datei enthält keine gültige Datenbank (schalk.backup).")
                with open(db_file, "rb") as f:
                    data = f.read()
                    
                from src.models.database import WrongPasswordError
                from src.views.backup_password_dialog import BackupPasswordDialog
                import time
                message = ""
                while True:
                    dialog = BackupPasswordDialog("unlock", message, parent=self.window())
                    if not dialog.exec():
                        return
                    try:
                        # Keep the current database as a backup copy instead of deleting it
                        if os.path.exists(paths.DB_PATH):
                            shutil.copy2(paths.DB_PATH, f"{paths.DB_PATH}.bak.{int(time.time())}")
                        self.db_controller.db.restore_backup(data, dialog.password())
                        break
                    except WrongPasswordError as e:
                        message = str(e)
                
                def copy_missing(src, dst):
                    # Archived documents are read-only and must not be overwritten
                    if not os.path.exists(dst):
                        shutil.copy2(src, dst)
                
                # Restore app_data and assets
                for folder, target in (("app_data", paths.APP_DATA_DIR), ("assets", paths.ASSETS_DIR)):
                    if os.path.exists(os.path.join(tmpdir, folder)):
                        try:
                            shutil.copytree(os.path.join(tmpdir, folder), target, dirs_exist_ok=True, copy_function=copy_missing)
                        except Exception as e:
                            print(f"Ignored error copying {folder}:", e)
                    
            # Restart Application
            os.execv(sys.executable, [sys.executable] + sys.argv)
            
        except Exception as e:
            InfoBar.error(
                title="Fehler beim Import",
                content=str(e),
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self.window()
            )

    def check_integrity(self):
        from qfluentwidgets import MessageBox
        problems = self.db_controller.verify_integrity()
        if problems:
            text = "\n".join(problems[:20])
            if len(problems) > 20:
                text += f"\n… und {len(problems) - 20} weitere"
            box = MessageBox("Integritätsprüfung: Abweichungen gefunden", text, self.window())
        else:
            box = MessageBox("Integritätsprüfung", "Alle Hash-Ketten und archivierten Dateien sind unverändert.", self.window())
        box.cancelButton.hide()
        box.exec()
