from qfluentwidgets import InfoBar, InfoBarPosition, LineEdit, PrimaryPushButton, SubtitleLabel
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QVBoxLayout, QWidget
from src.controllers.db_controller import DBController
from src.utils.signal_bus import SignalBus


class BankDataInterface(QWidget):
    def __init__(self, db_controller: DBController, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("BankDataInterface")
        self.db_controller = db_controller
        
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(36, 36, 36, 36)
        
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
        self.titleLabel = SubtitleLabel("Bankdaten", self)
        self.vBoxLayout.addWidget(self.titleLabel)
        
        self.vBoxLayout.addSpacing(24)
        
        self.formLayout = QFormLayout()
        self.formLayout.setSpacing(16)
        
        self.bankNameEdit = LineEdit(self)
        self.bankNameEdit.setPlaceholderText("Bankinstitut")
        self.formLayout.addRow("Bankname", self.bankNameEdit)
        
        self.ibanEdit = LineEdit(self)
        self.ibanEdit.setPlaceholderText("IBAN")
        self.formLayout.addRow("IBAN", self.ibanEdit)
        
        self.bicEdit = LineEdit(self)
        self.bicEdit.setPlaceholderText("BIC")
        self.formLayout.addRow("BIC", self.bicEdit)
        
        self.accountHolderEdit = LineEdit(self)
        self.accountHolderEdit.setPlaceholderText("Empfängername")
        self.formLayout.addRow("Kontoinhaber", self.accountHolderEdit)
        
        self.vBoxLayout.addLayout(self.formLayout)
        
        self.saveBtn = PrimaryPushButton("Bankdaten speichern", self)
        self.saveBtn.clicked.connect(self.save_settings)
        
        btnLayout = QHBoxLayout()
        btnLayout.addStretch(1)
        btnLayout.addWidget(self.saveBtn)
        self.vBoxLayout.addLayout(btnLayout)
        
        self.vBoxLayout.addStretch(1)

    def load_settings(self):
        self.bankNameEdit.setText(self.db_controller.get_setting("bank_name"))
        self.ibanEdit.setText(self.db_controller.get_setting("iban"))
        self.bicEdit.setText(self.db_controller.get_setting("bic"))
        self.accountHolderEdit.setText(self.db_controller.get_setting("account_holder"))

    def save_settings(self):
        iban = self.ibanEdit.text().strip()
        account_holder = self.accountHolderEdit.text().strip()
        bic = self.bicEdit.text().strip()
        bank_name = self.bankNameEdit.text().strip()
        
        if iban or account_holder or bic or bank_name:
            if not iban or not account_holder:
                InfoBar.error(
                    title="Fehler",
                    content="Für die Bankdaten müssen mindestens IBAN und Kontoinhaber ausgefüllt sein.",
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=4000,
                    parent=self.window()
                )
                return
            
            if not iban.upper().startswith("DE") and not bic:
                InfoBar.error(
                    title="Fehler",
                    content="Bei einer ausländischen IBAN (nicht DE) muss der BIC ausgefüllt werden.",
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=4000,
                    parent=self.window()
                )
                return

        self.db_controller.set_setting("bank_name", self.bankNameEdit.text())
        self.db_controller.set_setting("iban", self.ibanEdit.text())
        self.db_controller.set_setting("bic", self.bicEdit.text())
        self.db_controller.set_setting("account_holder", self.accountHolderEdit.text())
        
        InfoBar.success(
            title="Gespeichert",
            content="Die Bankdaten wurden erfolgreich gespeichert.",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self.window()
        )

