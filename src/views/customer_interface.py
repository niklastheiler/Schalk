from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, FluentIcon as FIF, LineEdit, PrimaryPushButton, PushButton, RoundMenu, SubtitleLabel
from stdnum.eu import vat as stdnum_vat
from src.controllers.db_controller import DBController
from src.utils.signal_bus import SignalBus
from src.utils.validation import contact_problems, german_postal_code_validator, phone_validator, postal_code_validator
from src.views.common import Column, ListPage, UnsavedChanges, ask_discard_changes, confirm, make_scrollable, notify_error, notify_success
from src.views.invoice_interface import add_action


def customer_problems(values: dict) -> list:
    """Checks the fields an e-invoice validator would reject; values are changed to their normalized form."""
    problems = []
    values["country"] = (values.get("country") or "DE").upper()
    if len(values["country"]) != 2 or not values["country"].isalpha():
        problems.append("Bitte das Land als zweistelligen ISO-Code angeben, z. B. DE, AT, FR.")
    vat_id = (values.get("vat_id") or "").strip()
    if vat_id:
        # EN 16931 (BR-CO-09): a VAT ID starts with the country code; EU numbers also have a check digit
        prefix = vat_id[:2].upper()
        if not prefix.isalpha():
            problems.append("Die USt-IdNr. muss mit dem Ländercode beginnen, z. B. DE123456789.")
        elif prefix.lower() in stdnum_vat.MEMBER_STATES or prefix == "EL":
            vat_id = vat_id.replace(" ", "").upper()
            if not stdnum_vat.is_valid(vat_id):
                problems.append("Die USt-IdNr. ist ungültig (Format/Prüfziffer).")
        values["vat_id"] = vat_id
    problems += contact_problems(values, "des Kunden", values["country"])
    return problems


class CustomerEditor(UnsavedChanges, QWidget):
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

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 8, 12, 0)
        form = QFormLayout()
        form.setSpacing(12)
        for key, label, placeholder in self.FIELDS:
            edit = LineEdit()
            edit.setPlaceholderText(placeholder)
            form.addRow(BodyLabel(label), edit)
            self.edits[key] = edit
        self.edits["phone"].setValidator(phone_validator(self))
        # German postal codes have 5 digits; other countries their own format
        self.edits["country"].textChanged.connect(self._update_postal_code_validator)
        self._update_postal_code_validator()
        content_layout.addLayout(form)
        content_layout.addStretch(1)
        layout.addWidget(make_scrollable(content))

    def _update_postal_code_validator(self):
        german = (self.edits["country"].text().strip().upper() or "DE") == "DE"
        self.edits["postal_code"].setValidator(german_postal_code_validator(self) if german else postal_code_validator(self))

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
        problems = customer_problems(values)
        if problems:
            notify_error(self, "Bitte prüfen", "\n".join(problems))
            return
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
        self.editor.canceled.connect(self.leave_editor)
        self.stackedWidget.addWidget(self.list_page)
        self.stackedWidget.addWidget(self.editor)

    def show_list(self):
        self.stackedWidget.setCurrentWidget(self.list_page)

    def show_editor(self, customer_id=None):
        if customer_id:
            self.editor.load_customer(customer_id)
        else:
            self.editor.clear_form()
        self.editor.mark_clean()
        self.stackedWidget.setCurrentWidget(self.editor)

    # --- Unsaved changes (asked by the main window before switching tabs) ---
    def has_unsaved_changes(self) -> bool:
        return self.stackedWidget.currentWidget() is self.editor and self.editor.has_unsaved_changes()

    def discard_changes(self):
        self.editor.clear_form()
        self.editor.mark_clean()
        self.show_list()

    def leave_editor(self):
        """"Zurück": asks first if something was typed."""
        if self.has_unsaved_changes() and not ask_discard_changes(self):
            return
        self.discard_changes()

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
