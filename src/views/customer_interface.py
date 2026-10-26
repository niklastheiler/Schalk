from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon as FIF, LineEdit, PrimaryPushButton, PushButton, RoundMenu, SubtitleLabel
from src.controllers.db_controller import DBController
from src.utils.signal_bus import SignalBus
from src.views.common import Column, ListPage, confirm, notify_error, notify_success
from src.views.invoice_interface import add_action


class CustomerEditor(QWidget):
    saved = Signal(int)
    canceled = Signal()

    FIELDS = [
        ("company_name", "Firma", "Firma"),
        ("first_name", "Vorname", "Vorname"),
        ("last_name", "Nachname", "Nachname"),
        ("address", "Adresse", "Straße und Hausnummer"),
        ("postal_code", "PLZ", "PLZ"),
        ("city", "Ort", "Ort"),
        ("country", "Land", "Ländercode, z. B. DE, AT, FR"),
        ("email", "E-Mail", "Empfangsadresse für E-Rechnungen"),
        ("phone", "Telefon", "Telefon"),
        ("vat_id", "USt-IdNr.", "Pflicht bei Reverse Charge / EU-Lieferung"),
        ("buyer_reference", "Käuferreferenz", "z. B. Leitweg-ID bei Behörden (XRechnung)"),
    ]

    def __init__(self, db_controller: DBController, parent=None):
        super().__init__(parent=parent)
        self.db_controller = db_controller
        self.current_customer_id = None
        self.edits = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        header = QHBoxLayout()
        back = PushButton("Zurück")
        back.clicked.connect(self.canceled.emit)
        self.titleLabel = SubtitleLabel("Neuer Kunde")
        save = PrimaryPushButton("Kunde speichern")
        save.clicked.connect(self.save_customer)
        header.addWidget(back)
        header.addStretch(1)
        header.addWidget(self.titleLabel)
        header.addStretch(1)
        header.addWidget(save)
        layout.addLayout(header)

        form = QFormLayout()
        form.setSpacing(12)
        for key, label, placeholder in self.FIELDS:
            edit = LineEdit()
            edit.setPlaceholderText(placeholder)
            form.addRow(label, edit)
            self.edits[key] = edit
        layout.addLayout(form)
        layout.addStretch(1)

    def clear_form(self):
        self.current_customer_id = None
        self.titleLabel.setText("Neuer Kunde")
        for edit in self.edits.values():
            edit.clear()
        self.edits["country"].setText("DE")

    def load_customer(self, customer_id: int):
        self.clear_form()
        customer = self.db_controller.get_customer(customer_id)
        if not customer:
            return
        self.current_customer_id = customer_id
        self.titleLabel.setText("Kunde bearbeiten")
        for key, edit in self.edits.items():
            edit.setText(getattr(customer, key) or "")

    def save_customer(self):
        values = {key: edit.text().strip() for key, edit in self.edits.items()}
        if not values["company_name"] and not (values["first_name"] or values["last_name"]):
            notify_error(self, "Fehler", "Bitte geben Sie entweder eine Firma oder einen Namen an.")
            return
        values["country"] = (values["country"] or "DE").upper()
        if self.current_customer_id:
            self.db_controller.update_customer(self.current_customer_id, **values)
            saved_id = self.current_customer_id
        else:
            saved_id = self.db_controller.add_customer(**values)
        self.saved.emit(saved_id)


class CustomerListPage(ListPage):
    def __init__(self, interface: "CustomerInterface"):
        self.interface = interface
        self.c = interface.db_controller
        columns = [
            Column("Firma", lambda c: c.company_name or ""),
            Column("Name", lambda c: f"{c.first_name or ''} {c.last_name or ''}".strip(), width=200),
            Column("Adresse", lambda c: c.address or "", width=220),
            Column("PLZ", lambda c: c.postal_code or "", width=80),
            Column("Ort", lambda c: c.city or "", width=150),
            Column("E-Mail", lambda c: c.email or "", width=200),
            Column("USt-IdNr.", lambda c: c.vat_id or "", width=130),
        ]
        super().__init__("Kunden", columns, (SignalBus.get().customersChanged,), parent=interface)
        self.add_header_button("Neuer Kunde", lambda: interface.show_editor(), primary=True)

    def records(self) -> list:
        return self.c.get_customers()

    def on_activated(self, customer):
        self.interface.show_editor(customer.id)

    def fill_context_menu(self, menu: RoundMenu, customer):
        add_action(menu, FIF.EDIT, "Bearbeiten", lambda: self.interface.show_editor(customer.id))
        add_action(menu, FIF.DELETE, "Löschen", lambda: self.interface.delete(customer.id))


class CustomerInterface(QWidget):
    def __init__(self, db_controller: DBController, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("CustomerInterface")
        self.db_controller = db_controller
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.stackedWidget = QStackedWidget(self)
        layout.addWidget(self.stackedWidget)
        self.list_page = CustomerListPage(self)
        self.editor = CustomerEditor(db_controller)
        self.editor.saved.connect(self._on_saved)
        self.editor.canceled.connect(self.show_list)
        self.stackedWidget.addWidget(self.list_page)
        self.stackedWidget.addWidget(self.editor)

    def show_list(self):
        self.stackedWidget.setCurrentWidget(self.list_page)

    def show_editor(self, customer_id=None):
        if customer_id:
            self.editor.load_customer(customer_id)
        else:
            self.editor.clear_form()
        self.stackedWidget.setCurrentWidget(self.editor)

    def _on_saved(self, customer_id):
        notify_success(self, "Gespeichert", "Kunde wurde gespeichert.")
        self.show_list()

    def delete(self, customer_id):
        if not confirm(self, "Kunde löschen", "Möchten Sie diesen Kunden wirklich löschen?"):
            return
        success, reason = self.db_controller.delete_customer(customer_id)
        if success:
            notify_success(self, "Gelöscht", "Der Kunde wurde gelöscht.")
        else:
            notify_error(self, "Fehler beim Löschen", f"Dieser Kunde kann nicht gelöscht werden, da noch {reason} mit ihm verknüpft sind.")
