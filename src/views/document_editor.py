"""Shared editor for documents with line items (invoices and quotes)."""
from typing import Optional
from PySide6.QtCore import QLocale, QStringListModel, Qt, Signal
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import QAbstractItemView, QCompleter, QFormLayout, QHBoxLayout, QHeaderView, QVBoxLayout, QWidget
from qfluentwidgets import (BodyLabel, ComboBox, EditableComboBox, LineEdit, PrimaryPushButton, PushButton,
                            SearchLineEdit, SubtitleLabel, TableWidget)
from src.controllers.db_controller import DBController, GoBDError
from src.utils.calculations import calculate_totals, item_total
from src.utils.signal_bus import SignalBus
from src.utils.tax import (TAX_RATE_OPTIONS, EXEMPTION_REASON_PRESETS, EXEMPTION_REQUIRED_MESSAGE, format_rate,
                           has_zero_rate)
from src.views.common import fmt_money, notify_error

SMALL_BUSINESS_REASON = EXEMPTION_REASON_PRESETS[0]

COL_TITLE, COL_QTY, COL_UNIT, COL_PRICE, COL_TAX, COL_DELETE = range(6)


def _german_number(value: float) -> str:
    return f"{value:.2f}".replace('.', ',')


def _parse_number(text: str, default: float) -> float:
    try:
        return float(text.replace('.', '').replace(',', '.')) if ',' in text else float(text)
    except ValueError:
        return default


def _number_validator() -> QDoubleValidator:
    validator = QDoubleValidator(0.0, 100_000_000.0, 2)
    validator.setNotation(QDoubleValidator.StandardNotation)
    validator.setLocale(QLocale(QLocale.German, QLocale.Germany))
    return validator


class DocumentEditor(QWidget):
    saved = Signal(int)
    canceled = Signal()

    NEW_TITLE = ""
    SAVE_TEXT = "Speichern"

    def __init__(self, db_controller: DBController, parent=None):
        super().__init__(parent=parent)
        self.db_controller = db_controller
        self.current_id: Optional[int] = None
        self.customer_id: Optional[int] = None
        self._read_only = False
        self._customer_entries = {}
        self.init_ui()
        SignalBus.get().customersChanged.connect(self._reload_customer_completer)
        self._reload_customer_completer()

    # --- UI ---
    def init_ui(self):
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(24, 24, 24, 24)

        headerLayout = QHBoxLayout()
        self.backBtn = PushButton("Zurück")
        self.backBtn.clicked.connect(self.canceled.emit)
        self.titleLabel = SubtitleLabel(self.NEW_TITLE)
        self.saveBtn = PrimaryPushButton(self.SAVE_TEXT)
        self.saveBtn.clicked.connect(self.save)
        headerLayout.addWidget(self.backBtn)
        headerLayout.addStretch(1)
        headerLayout.addWidget(self.titleLabel)
        headerLayout.addStretch(1)
        headerLayout.addWidget(self.saveBtn)
        self.vBoxLayout.addLayout(headerLayout)

        formLayout = QHBoxLayout()
        customerForm = QFormLayout()
        customerForm.setSpacing(10)
        self.customerSearch = SearchLineEdit()
        self.customerSearch.setPlaceholderText("Bestehenden Kunden suchen (leer = neuer Kunde)...")
        self._completer_model = QStringListModel(self)
        self._completer = QCompleter(self._completer_model, self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchContains)
        self._completer.setMaxVisibleItems(12)
        self._completer.activated.connect(self._on_customer_chosen)
        self.customerSearch.setCompleter(self._completer)
        self.customerSearch.textEdited.connect(self._on_customer_search_edited)
        customerForm.addRow("Kunde", self.customerSearch)

        self.companyEdit = self._line_edit("Firma", customerForm)
        self.nameEdit = self._line_edit("Vor- und Nachname", customerForm)
        self.addressEdit = self._line_edit("Straße und Hausnummer", customerForm)
        self.postalCodeEdit = self._line_edit("PLZ", customerForm)
        self.cityEdit = self._line_edit("Ort", customerForm)
        self.emailEdit = self._line_edit("E-Mail (für E-Rechnung)", customerForm)
        self.vatIdEdit = self._line_edit("USt-IdNr. des Kunden (optional)", customerForm)

        self.documentForm = QFormLayout()
        self.documentForm.setSpacing(10)
        self.add_document_fields(self.documentForm)
        self.exemptionLabel = BodyLabel("Befreiungsgrund")
        self.exemptionEdit = EditableComboBox()
        self.exemptionEdit.addItems(EXEMPTION_REASON_PRESETS)
        self.exemptionEdit.setPlaceholderText("Pflicht bei 0 % MwSt., z. B. § 19 UStG")
        self.exemptionEdit.setText("")
        self.documentForm.addRow(self.exemptionLabel, self.exemptionEdit)
        self.exemptionLabel.hide()
        self.exemptionEdit.hide()

        formLayout.addLayout(customerForm, 1)
        formLayout.addLayout(self.documentForm, 1)
        self.vBoxLayout.addLayout(formLayout)

        self.vBoxLayout.addSpacing(16)
        tableHeaderLayout = QHBoxLayout()
        tableHeaderLayout.addWidget(SubtitleLabel("Positionen"))
        tableHeaderLayout.addStretch(1)
        self.addItemBtn = PushButton("Position hinzufügen")
        self.addItemBtn.clicked.connect(lambda: self.add_item_row())
        tableHeaderLayout.addWidget(self.addItemBtn)
        self.vBoxLayout.addLayout(tableHeaderLayout)

        self.table = TableWidget(self)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(['Bezeichnung', 'Menge', 'Einheit', 'Einzelpreis (€)', 'MwSt.', ''])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_TITLE, QHeaderView.Stretch)
        for col, width in ((COL_QTY, 110), (COL_UNIT, 100), (COL_PRICE, 140), (COL_TAX, 110), (COL_DELETE, 56)):
            self.table.setColumnWidth(col, width)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(45)
        self.vBoxLayout.addWidget(self.table)

        self.netTotalLabel = self._total_label()
        self.creditTotalLabel = self._total_label()
        self.taxLabel = self._total_label()
        self.grossTotalLabel = self._total_label()

    def _line_edit(self, placeholder: str, form: QFormLayout) -> LineEdit:
        edit = LineEdit()
        edit.setPlaceholderText(placeholder)
        form.addRow("", edit)
        return edit

    def _total_label(self) -> SubtitleLabel:
        label = SubtitleLabel("")
        label.setAlignment(Qt.AlignRight)
        self.vBoxLayout.addWidget(label)
        return label

    # --- Hooks for subclasses ---
    def add_document_fields(self, form: QFormLayout):
        pass

    def clear_document_fields(self):
        pass

    def credit_amount(self) -> float:
        return 0.0

    def persist(self, customer_id: int, items: list, exemption_reason: str) -> int:
        raise NotImplementedError

    def set_document_fields_enabled(self, enabled: bool):
        pass

    # --- Customer selection ---
    def _reload_customer_completer(self):
        self._customer_entries = {}
        for customer in self.db_controller.get_customers():
            label = f"{customer.display_name} – {customer.city or ''} (#{customer.id})"
            self._customer_entries[label] = customer.id
        self._completer_model.setStringList(list(self._customer_entries))

    def _on_customer_chosen(self, label: str):
        customer = self.db_controller.get_customer(self._customer_entries.get(label))
        if customer:
            self._fill_customer(customer)

    def _on_customer_search_edited(self, text: str):
        if not text:
            # Empty search = new customer
            self.customer_id = None

    def _fill_customer(self, customer):
        self.customer_id = customer.id
        self.customerSearch.setText(customer.display_name)
        self.companyEdit.setText(customer.company_name or "")
        self.nameEdit.setText(f"{customer.first_name or ''} {customer.last_name or ''}".strip())
        self.addressEdit.setText(customer.address or "")
        self.postalCodeEdit.setText(customer.postal_code or "")
        self.cityEdit.setText(customer.city or "")
        self.emailEdit.setText(customer.email or "")
        self.vatIdEdit.setText(customer.vat_id or "")

    def _save_customer(self) -> int:
        names = self.nameEdit.text().strip().split(" ", 1)
        fields = dict(
            company_name=self.companyEdit.text().strip(),
            first_name=names[0] if names else "",
            last_name=names[1] if len(names) > 1 else "",
            address=self.addressEdit.text().strip(),
            postal_code=self.postalCodeEdit.text().strip(),
            city=self.cityEdit.text().strip(),
            email=self.emailEdit.text().strip(),
            vat_id=self.vatIdEdit.text().strip(),
        )
        if self.customer_id and self.db_controller.get_customer(self.customer_id):
            self.db_controller.update_customer(self.customer_id, **fields)
        else:
            self.customer_id = self.db_controller.add_customer(**fields)
        return self.customer_id

    # --- Form state ---
    def clear_form(self):
        self.current_id = None
        self.customer_id = None
        self.set_read_only(False)
        self.titleLabel.setText(self.NEW_TITLE)
        for edit in (self.customerSearch, self.companyEdit, self.nameEdit, self.addressEdit, self.postalCodeEdit,
                     self.cityEdit, self.emailEdit, self.vatIdEdit):
            edit.clear()
        self.exemptionEdit.setText(SMALL_BUSINESS_REASON if self.db_controller.is_small_business() else "")
        self.table.setRowCount(0)
        self.clear_document_fields()
        self.update_totals()

    def load_items(self, document):
        customer = self.db_controller.get_customer(document.customer_id)
        if customer:
            self._fill_customer(customer)
        self.exemptionEdit.setText(document.tax_exemption_reason or "")
        self.table.setRowCount(0)
        for item in document.items:
            self.add_item_row(item)
        self.update_totals()

    def set_read_only(self, read_only: bool):
        self._read_only = read_only
        self.saveBtn.setVisible(not read_only)
        self.addItemBtn.setVisible(not read_only)
        for edit in (self.customerSearch, self.companyEdit, self.nameEdit, self.addressEdit, self.postalCodeEdit,
                     self.cityEdit, self.emailEdit, self.vatIdEdit, self.exemptionEdit):
            edit.setEnabled(not read_only)
        self.set_document_fields_enabled(not read_only)
        for row in range(self.table.rowCount()):
            for col in range(COL_DELETE):
                self.table.cellWidget(row, col).setEnabled(not read_only)
            self.table.cellWidget(row, COL_DELETE).setVisible(not read_only)

    # --- Items ---
    def add_item_row(self, item=None):
        row = self.table.rowCount()
        self.table.insertRow(row)

        title_edit = LineEdit()
        qty_edit = LineEdit()
        qty_edit.setValidator(_number_validator())
        unit_edit = LineEdit()
        price_edit = LineEdit()
        price_edit.setValidator(_number_validator())
        tax_combo = ComboBox()
        for rate in TAX_RATE_OPTIONS:
            tax_combo.addItem(format_rate(rate), userData=rate)
        delete_btn = PushButton("X")
        delete_btn.setFixedWidth(40)
        delete_btn.clicked.connect(lambda: self._delete_row(title_edit))

        if item is not None:
            title_edit.setText(item.title)
            qty_edit.setText(_german_number(item.quantity))
            unit_edit.setText(item.unit)
            price_edit.setText(_german_number(item.unit_price))
            rate = item.tax_percent
            # Fields without an input column are carried along so saving doesn't drop them
            title_edit.item_description = item.description
            title_edit.item_discount = item.discount_percent or 0.0
        else:
            qty_edit.setText("1,00")
            unit_edit.setText("Stück")
            price_edit.setText("0,00")
            rate = 0.0 if self.db_controller.is_small_business() else TAX_RATE_OPTIONS[0]
        tax_combo.setCurrentIndex(tax_combo.findData(rate))

        for col, widget in ((COL_TITLE, title_edit), (COL_QTY, qty_edit), (COL_UNIT, unit_edit), (COL_PRICE, price_edit), (COL_TAX, tax_combo)):
            widget.setEnabled(not self._read_only)
            self.table.setCellWidget(row, col, widget)
        delete_btn.setVisible(not self._read_only)
        self.table.setCellWidget(row, COL_DELETE, delete_btn)

        # Connected only now: the totals read all cells of the row
        for edit in (title_edit, qty_edit, price_edit):
            edit.textChanged.connect(self.update_totals)
        tax_combo.currentIndexChanged.connect(self.update_totals)
        self.update_totals()

    def _delete_row(self, title_edit):
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, COL_TITLE) is title_edit:
                self.table.removeRow(row)
                break
        self.update_totals()

    def collect_items(self) -> list:
        items = []
        for row in range(self.table.rowCount()):
            title_widget = self.table.cellWidget(row, COL_TITLE)
            title = title_widget.text().strip()
            if not title:
                continue
            quantity = _parse_number(self.table.cellWidget(row, COL_QTY).text(), 1.0)
            price = _parse_number(self.table.cellWidget(row, COL_PRICE).text(), 0.0)
            discount = getattr(title_widget, 'item_discount', 0.0)
            items.append({
                "title": title,
                "description": getattr(title_widget, 'item_description', None),
                "quantity": quantity,
                "unit": self.table.cellWidget(row, COL_UNIT).text().strip() or "Stück",
                "unit_price": price,
                "discount_percent": discount,
                "tax_percent": self.table.cellWidget(row, COL_TAX).currentData(),
                "total_price": item_total(quantity, price, discount),
            })
        return items

    def update_totals(self):
        if not hasattr(self, "grossTotalLabel"):
            return # still building the UI
        items = self.collect_items()
        credit = self.credit_amount()
        totals = calculate_totals(items, credit)
        self.netTotalLabel.setText(f"Nettobetrag: {fmt_money(totals['net_amount'])}")
        self.creditTotalLabel.setText(f"abzgl. Gutschrift: {fmt_money(credit)}")
        self.creditTotalLabel.setVisible(credit > 0)
        self.taxLabel.setText(f"zzgl. MwSt.: {fmt_money(totals['tax_amount'])}")
        self.grossTotalLabel.setText(f"Gesamtbetrag: {fmt_money(totals['gross_amount'])}")
        # The exemption reason is only needed (and printed) with 0 % items
        zero = has_zero_rate(items) or any(self.table.cellWidget(r, COL_TAX).currentData() == 0.0 for r in range(self.table.rowCount()))
        self.exemptionLabel.setVisible(zero)
        self.exemptionEdit.setVisible(zero)

    # --- Saving ---
    def validate(self, items: list) -> Optional[str]:
        if not self.companyEdit.text().strip() and not self.nameEdit.text().strip():
            return "Bitte geben Sie entweder eine Firma oder den Vor- und Nachnamen an."
        if not items:
            return "Bitte mindestens eine Position mit Bezeichnung erfassen."
        if has_zero_rate(items) and not self.exemptionEdit.text().strip():
            return EXEMPTION_REQUIRED_MESSAGE
        return None

    def save(self):
        items = self.collect_items()
        # Validate before touching customer data, so a failed save leaves no half-created customer
        problem = self.validate(items)
        if problem:
            notify_error(self, "Bitte prüfen", problem)
            return
        exemption = self.exemptionEdit.text().strip() if has_zero_rate(items) else ""
        try:
            customer_id = self._save_customer()
            saved_id = self.persist(customer_id, items, exemption)
        except (GoBDError, ValueError) as e:
            notify_error(self, "Nicht gespeichert", str(e))
            return
        self.current_id = saved_id
        self.saved.emit(saved_id)
