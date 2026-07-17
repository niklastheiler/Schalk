from PySide6.QtCore import Signal
from qfluentwidgets import InfoBar, InfoBarPosition, LineEdit, PrimaryPushButton, PushButton, SubtitleLabel
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QVBoxLayout, QWidget
from src.controllers.db_controller import DBController

class CustomerEditor(QWidget):
    saved = Signal(int)
    canceled = Signal()

    def __init__(self, db_controller: DBController, parent=None):
        super().__init__(parent=parent)
        self.db_controller = db_controller
        self.current_customer_id = None
        self.init_ui()

    def init_ui(self):
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(24, 24, 24, 24)
        
        # Header
        headerLayout = QHBoxLayout()
        self.backBtn = PushButton("Zurück")
        self.backBtn.clicked.connect(self.canceled.emit)
        
        self.titleLabel = SubtitleLabel("Neuer Kunde")
        
        self.saveBtn = PrimaryPushButton("Kunde speichern")
        self.saveBtn.clicked.connect(self.save_customer)
        
        headerLayout.addWidget(self.backBtn)
        headerLayout.addStretch(1)
        headerLayout.addWidget(self.titleLabel)
        headerLayout.addStretch(1)
        headerLayout.addWidget(self.saveBtn)
        self.vBoxLayout.addLayout(headerLayout)
        
        # Form
        formLayout = QFormLayout()
        formLayout.setSpacing(15)
        
        self.companyEdit = LineEdit()
        self.companyEdit.setPlaceholderText("Firma")
        formLayout.addRow("Firma", self.companyEdit)
        
        self.firstNameEdit = LineEdit()
        self.firstNameEdit.setPlaceholderText("Vorname")
        formLayout.addRow("Vorname", self.firstNameEdit)
        
        self.lastNameEdit = LineEdit()
        self.lastNameEdit.setPlaceholderText("Nachname")
        formLayout.addRow("Nachname", self.lastNameEdit)
        
        self.addressEdit = LineEdit()
        self.addressEdit.setPlaceholderText("Straße und Hausnummer")
        formLayout.addRow("Adresse", self.addressEdit)
        
        self.postalCodeEdit = LineEdit()
        self.postalCodeEdit.setPlaceholderText("PLZ")
        formLayout.addRow("PLZ", self.postalCodeEdit)
        
        self.cityEdit = LineEdit()
        self.cityEdit.setPlaceholderText("Ort")
        formLayout.addRow("Ort", self.cityEdit)
        
        self.emailEdit = LineEdit()
        self.emailEdit.setPlaceholderText("E-Mail")
        formLayout.addRow("E-Mail", self.emailEdit)
        
        self.phoneEdit = LineEdit()
        self.phoneEdit.setPlaceholderText("Telefon")
        formLayout.addRow("Telefon", self.phoneEdit)
        
        self.vBoxLayout.addLayout(formLayout)
        self.vBoxLayout.addStretch(1)

    def clear_form(self):
        self.current_customer_id = None
        self.titleLabel.setText("Neuer Kunde")
        self.companyEdit.clear()
        self.firstNameEdit.clear()
        self.lastNameEdit.clear()
        self.addressEdit.clear()
        self.postalCodeEdit.clear()
        self.cityEdit.clear()
        self.emailEdit.clear()
        self.phoneEdit.clear()

    def load_customer(self, customer_id: int):
        self.clear_form()
        self.current_customer_id = customer_id
        customers = self.db_controller.get_customers()
        cust = next((c for c in customers if c.id == customer_id), None)
        if not cust: return
        
        self.titleLabel.setText(f"Kunde bearbeiten")
        self.companyEdit.setText(cust.company_name or "")
        self.firstNameEdit.setText(cust.first_name or "")
        self.lastNameEdit.setText(cust.last_name or "")
        self.addressEdit.setText(cust.address or "")
        self.postalCodeEdit.setText(cust.postal_code or "")
        self.cityEdit.setText(cust.city or "")
        self.emailEdit.setText(cust.email or "")
        self.phoneEdit.setText(cust.phone or "")

    def save_customer(self):
        if not self.companyEdit.text().strip() and not (self.firstNameEdit.text().strip() or self.lastNameEdit.text().strip()):
            InfoBar.error(
                title="Fehler",
                content="Bitte geben Sie entweder eine Firma oder einen Namen an.",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self.window()
            )
            return

        kwargs = {
            "company_name": self.companyEdit.text().strip(),
            "first_name": self.firstNameEdit.text().strip(),
            "last_name": self.lastNameEdit.text().strip(),
            "address": self.addressEdit.text().strip(),
            "postal_code": self.postalCodeEdit.text().strip(),
            "city": self.cityEdit.text().strip(),
            "email": self.emailEdit.text().strip(),
            "phone": self.phoneEdit.text().strip()
        }

        if self.current_customer_id:
            self.db_controller.update_customer(self.current_customer_id, **kwargs)
            saved_id = self.current_customer_id
        else:
            saved_id = self.db_controller.add_customer(**kwargs)
            
        self.saved.emit(saved_id)

