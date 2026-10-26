from PySide6.QtCore import Signal
from qfluentwidgets import BodyLabel, CheckBox
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QHeaderView, QVBoxLayout, QWidget
from qfluentwidgets import ComboBox, DatePicker, EditableComboBox, InfoBar, InfoBarPosition, LineEdit, PrimaryPushButton, PushButton, SubtitleLabel, TableWidget
from PySide6.QtCore import QDate, Qt
from src.controllers.db_controller import DBController, GoBDError, DRAFT_PREFIX
from src.utils.calculations import calculate_totals, item_total
from src.utils.tax import TAX_RATE_OPTIONS, EXEMPTION_REASON_PRESETS, EXEMPTION_REQUIRED_MESSAGE, format_rate, has_zero_rate
from datetime import datetime, timezone

class InvoiceEditor(QWidget):
    saved = Signal(int)
    canceled = Signal()

    def __init__(self, db_controller: DBController, parent=None):
        super().__init__(parent=parent)
        self.db_controller = db_controller
        self.current_invoice_id = None
        self.init_ui()

    def init_ui(self):
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(24, 24, 24, 24)
        
        # Header
        headerLayout = QHBoxLayout()
        self.backBtn = PushButton("Zurück")
        self.backBtn.clicked.connect(self.canceled.emit)
        
        self.titleLabel = SubtitleLabel("Neue Rechnung")
        
        self.saveBtn = PrimaryPushButton("Rechnung speichern")
        self.saveBtn.clicked.connect(self.save_invoice)
        
        headerLayout.addWidget(self.backBtn)
        headerLayout.addStretch(1)
        headerLayout.addWidget(self.titleLabel)
        headerLayout.addStretch(1)
        headerLayout.addWidget(self.saveBtn)
        self.vBoxLayout.addLayout(headerLayout)
        
        # Formular Layout (Kunde & Daten)
        formLayout = QHBoxLayout()
        
        # Kunde (Left)
        customerForm = QFormLayout()
        customerForm.setSpacing(10)
        self.customerCombo = ComboBox()
        self.customerCombo.setPlaceholderText("Bestehenden Kunden wählen...")
        self.customerCombo.currentIndexChanged.connect(self.on_customer_selected)
        customerForm.addRow("Kunde", self.customerCombo)
        
        self.companyEdit = LineEdit()
        self.companyEdit.setPlaceholderText("Firma")
        customerForm.addRow("", self.companyEdit)
        
        self.nameEdit = LineEdit()
        self.nameEdit.setPlaceholderText("Vor- und Nachname")
        customerForm.addRow("", self.nameEdit)
        
        self.addressEdit = LineEdit()
        self.addressEdit.setPlaceholderText("Straße und Hausnummer")
        customerForm.addRow("", self.addressEdit)
        
        self.postalCodeEdit = LineEdit()
        self.postalCodeEdit.setPlaceholderText("PLZ")
        customerForm.addRow("", self.postalCodeEdit)
        
        self.cityEdit = LineEdit()
        self.cityEdit.setPlaceholderText("Ort")
        customerForm.addRow("", self.cityEdit)
        
        # Daten (Right)
        dateForm = QFormLayout()
        dateForm.setSpacing(10)
        self.invoiceDate = DatePicker()
        self.invoiceDate.setDate(QDate.currentDate())
        dateForm.addRow("Rechnungsdatum", self.invoiceDate)
        
        self.deliveryDate = DatePicker()
        self.deliveryDate.setDate(QDate.currentDate())
        dateForm.addRow("Leistungsdatum", self.deliveryDate)
        
        self.creditCheck = CheckBox("Gutschrift")
        self.creditCheck.stateChanged.connect(self.on_credit_toggled)
        dateForm.addRow("", self.creditCheck)
        
        self.creditAmountEdit = LineEdit()
        self.creditAmountEdit.setPlaceholderText("Betrag (€)")
        self.creditAmountEdit.hide()
        self.creditAmountEdit.textChanged.connect(self.update_totals)
        
        self.creditDescEdit = LineEdit()
        self.creditDescEdit.setPlaceholderText("Beschreibung")
        self.creditDescEdit.hide()
        
        dateForm.addRow("", self.creditAmountEdit)
        dateForm.addRow("", self.creditDescEdit)
        self._create_exemption_widgets(dateForm)
        
        formLayout.addLayout(customerForm, 1)
        formLayout.addLayout(dateForm, 1)
        self.vBoxLayout.addLayout(formLayout)
        
        # Positionen Tabelle
        self.vBoxLayout.addSpacing(20)
        tableHeaderLayout = QHBoxLayout()
        tableHeaderLayout.addWidget(SubtitleLabel("Positionen"))
        tableHeaderLayout.addStretch(1)
        self.addItemBtn = PushButton("Position hinzufügen")
        self.addItemBtn.clicked.connect(self.add_item_row)
        tableHeaderLayout.addWidget(self.addItemBtn)
        self.vBoxLayout.addLayout(tableHeaderLayout)
        
        self.table = TableWidget(self)
        self.table.viewport().setMouseTracking(False)
        from PySide6.QtWidgets import QAbstractItemView
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(['Bezeichnung', 'Menge', 'Einheit', 'Einzelpreis (€)', 'MwSt.', 'Aktion'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setColumnWidth(1, 140)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 180)
        self.table.setColumnWidth(4, 110)
        self.table.setColumnWidth(5, 50)
        self.table.verticalHeader().hide() # Hide row numbers for cleaner look
        # Performance optimization for scrolling with setCellWidget
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(45)
        from PySide6.QtWidgets import QAbstractItemView
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.vBoxLayout.addWidget(self.table)
        
        # Summen (Totals Breakdown)
        totalsLayout = QVBoxLayout()
        self.netTotalLabel = SubtitleLabel("Nettobetrag: 0,00 €")
        self.netTotalLabel.setAlignment(Qt.AlignRight)
        self.tax19Label = SubtitleLabel("zzgl. 19% MwSt: 0,00 €")
        self.tax19Label.setAlignment(Qt.AlignRight)
        
        self.creditTotalLabel = SubtitleLabel("abzgl. Gutschrift: 0,00 €")
        self.creditTotalLabel.setAlignment(Qt.AlignRight)
        self.creditTotalLabel.hide()
        
        self.grossTotalLabel = SubtitleLabel("Gesamtbetrag: 0,00 €")
        self.grossTotalLabel.setAlignment(Qt.AlignRight)
        
        totalsLayout.addWidget(self.netTotalLabel)
        totalsLayout.addWidget(self.creditTotalLabel)
        totalsLayout.addWidget(self.tax19Label)
        totalsLayout.addWidget(self.grossTotalLabel)
        
        self.vBoxLayout.addLayout(totalsLayout)

    def on_credit_toggled(self, state=None):
        visible = self.creditCheck.isChecked()
        self.creditAmountEdit.setVisible(visible)
        self.creditDescEdit.setVisible(visible)
        if not visible:
            self.creditAmountEdit.clear()
            self.creditDescEdit.clear()
        self.update_totals()

    def clear_form(self):
        self.current_invoice_id = None
        self.set_read_only(False)
        self.titleLabel.setText("Neue Rechnung")
        self.companyEdit.clear()
        self.nameEdit.clear()
        self.addressEdit.clear()
        self.postalCodeEdit.clear()
        self.cityEdit.clear()
        self.invoiceDate.setDate(QDate.currentDate())
        self.deliveryDate.setDate(QDate.currentDate())
        self.creditCheck.setChecked(False)
        self.exemptionEdit.setText("")
        self.table.setRowCount(0)
        self.load_customers()
        self.update_totals()

    def load_invoice(self, invoice_id: int):
        self.clear_form()
        self.current_invoice_id = invoice_id
        invoice = self.db_controller.get_invoice(invoice_id)
        if not invoice: return
        
        if invoice.invoice_number.startswith(DRAFT_PREFIX):
            self.titleLabel.setText("Rechnungsentwurf bearbeiten")
        else:
            self.titleLabel.setText(f"Rechnung {invoice.invoice_number} bearbeiten")
        
        # Set Customer
        for i in range(self.customerCombo.count()):
            cust = self.customerCombo.itemData(i)
            if cust and cust.id == invoice.customer_id:
                self.customerCombo.setCurrentIndex(i)
                break
                
        # Set Dates
        self.invoiceDate.setDate(QDate(invoice.invoice_date.year, invoice.invoice_date.month, invoice.invoice_date.day))
        self.deliveryDate.setDate(QDate(invoice.delivery_date.year, invoice.delivery_date.month, invoice.delivery_date.day))
        
        # Set Items
        self.table.setRowCount(0)
        for item in invoice.items:
            self.add_item_row()
            row = self.table.rowCount() - 1
            self.table.cellWidget(row, 0).setText(item.title)
            self.table.cellWidget(row, 1).setText(f"{item.quantity:.2f}".replace('.', ','))
            self.table.cellWidget(row, 2).setText(item.unit)
            self.table.cellWidget(row, 3).setText(f"{item.unit_price:.2f}".replace('.', ','))
            # Fields without an input column are carried along so saving a draft doesn't drop them
            title_widget = self.table.cellWidget(row, 0)
            title_widget.item_description = item.description
            title_widget.item_discount = item.discount_percent or 0.0
            self._set_row_tax(row, item.tax_percent if item.tax_percent is not None else 19.0)
            
        if getattr(invoice, 'credit_amount', 0.0) > 0:
            self.creditCheck.setChecked(True)
            self.creditAmountEdit.setText(f"{invoice.credit_amount:.2f}".replace('.', ','))
            self.creditDescEdit.setText(invoice.credit_desc or "")
        else:
            self.creditCheck.setChecked(False)
        self.exemptionEdit.setText(invoice.tax_exemption_reason or "")
            
        self.update_totals()
        
        # GoBD: finalized invoices are immutable
        if self.db_controller.is_finalized(invoice):
            self.set_read_only(True)
            suffix = "Archiviert" if invoice.archived_at else "festgeschrieben"
            self.titleLabel.setText(f"Rechnung {invoice.invoice_number} ({suffix})")

    def set_read_only(self, read_only: bool):
        self.saveBtn.setVisible(not read_only)
        self.addItemBtn.setVisible(not read_only)
        self.customerCombo.setEnabled(not read_only)
        self.companyEdit.setEnabled(not read_only)
        self.nameEdit.setEnabled(not read_only)
        self.addressEdit.setEnabled(not read_only)
        self.postalCodeEdit.setEnabled(not read_only)
        self.cityEdit.setEnabled(not read_only)
        self.invoiceDate.setEnabled(not read_only)
        self.deliveryDate.setEnabled(not read_only)
        self.creditCheck.setEnabled(not read_only)
        self.creditAmountEdit.setEnabled(not read_only)
        self.creditDescEdit.setEnabled(not read_only)
        self.exemptionEdit.setEnabled(not read_only)
        
        for row in range(self.table.rowCount()):
            for col in range(5):
                widget = self.table.cellWidget(row, col)
                if widget: widget.setEnabled(not read_only)
            del_btn = self.table.cellWidget(row, 5)
            if del_btn: del_btn.setVisible(not read_only)

    def load_customers(self):
        self.customerCombo.clear()
        self.customerCombo.addItem("--- Neuer Kunde ---", userData=None)
        self.customers = self.db_controller.get_customers()
        for cust in self.customers:
            display_name = cust.company_name if cust.company_name else f"{cust.first_name} {cust.last_name}"
            self.customerCombo.addItem(display_name, userData=cust)

    def on_customer_selected(self, index):
        cust = self.customerCombo.itemData(index)
        if cust:
            self.companyEdit.setText(cust.company_name or "")
            self.nameEdit.setText(f"{cust.first_name or ''} {cust.last_name or ''}".strip())
            self.addressEdit.setText(cust.address or "")
            self.postalCodeEdit.setText(cust.postal_code or "")
            self.cityEdit.setText(cust.city or "")
        else:
            self.companyEdit.clear()
            self.nameEdit.clear()
            self.addressEdit.clear()
            self.postalCodeEdit.clear()
            self.cityEdit.clear()

    def add_item_row(self):
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setRowHeight(row, 45) # Ensure widgets fit nicely
        
        # Standardize height for all widgets to match
        widget_height = 32
        
        title_edit = LineEdit()
        title_edit.setFixedHeight(widget_height)
        title_edit.textChanged.connect(self.update_totals)
        
        from PySide6.QtGui import QDoubleValidator
        from PySide6.QtCore import QLocale
        qty_spin = LineEdit()
        qty_spin.setMinimumWidth(130)
        qty_spin.setFixedHeight(widget_height)
        val1 = QDoubleValidator(0.0, 1000000.0, 2)
        val1.setNotation(QDoubleValidator.StandardNotation)
        val1.setLocale(QLocale(QLocale.German, QLocale.Germany))
        qty_spin.setValidator(val1)
        qty_spin.setText("1,00")
        qty_spin.textChanged.connect(self.update_totals)
        
        unit_edit = LineEdit()
        unit_edit.setText("Stück")
        unit_edit.setFixedHeight(widget_height)
        
        price_spin = LineEdit()
        price_spin.setMinimumWidth(170)
        price_spin.setFixedHeight(widget_height)
        val2 = QDoubleValidator(0.0, 1000000.0, 2)
        val2.setNotation(QDoubleValidator.StandardNotation)
        val2.setLocale(QLocale(QLocale.German, QLocale.Germany))
        price_spin.setValidator(val2)
        price_spin.setText("0,00")
        price_spin.textChanged.connect(self.update_totals)
        
        tax_combo = ComboBox()
        tax_combo.setFixedHeight(widget_height)
        for rate in TAX_RATE_OPTIONS:
            tax_combo.addItem(format_rate(rate), userData=rate)
        tax_combo.setCurrentIndex(0)
        tax_combo.currentIndexChanged.connect(self.update_totals)
        
        del_btn = PushButton("X")
        del_btn.setFixedWidth(40)
        del_btn.setFixedHeight(widget_height)
        del_btn.clicked.connect(lambda: self.delete_row(del_btn))
        
        container = QWidget(self.table)
        lay = QHBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignCenter)
        lay.addWidget(del_btn)
        # Store a reference to the button on the container to find it later
        container.del_btn = del_btn
        
        # If in read-only mode, we disable inputs and hide delete btn
        read_only = not self.saveBtn.isVisible()
        title_edit.setEnabled(not read_only)
        qty_spin.setEnabled(not read_only)
        unit_edit.setEnabled(not read_only)
        price_spin.setEnabled(not read_only)
        tax_combo.setEnabled(not read_only)
        container.setVisible(not read_only)
        
        self.table.setCellWidget(row, 0, title_edit)
        self.table.setCellWidget(row, 1, qty_spin)
        self.table.setCellWidget(row, 2, unit_edit)
        self.table.setCellWidget(row, 3, price_spin)
        self.table.setCellWidget(row, 4, tax_combo)
        self.table.setCellWidget(row, 5, container)

    def _set_row_tax(self, row, rate):
        combo = self.table.cellWidget(row, 4)
        for i in range(combo.count()):
            if combo.itemData(i) == rate:
                combo.setCurrentIndex(i)
                return
        # Rate that is no longer offered (e.g. from an older document)
        combo.addItem(format_rate(rate), userData=rate)
        combo.setCurrentIndex(combo.count() - 1)

    def _create_exemption_widgets(self, form):
        self.exemptionLabel = BodyLabel("Befreiungsgrund")
        self.exemptionEdit = EditableComboBox()
        self.exemptionEdit.addItems(EXEMPTION_REASON_PRESETS)
        self.exemptionEdit.setPlaceholderText("Pflicht bei 0 % MwSt., z. B. § 19 UStG")
        self.exemptionEdit.setText("")
        form.addRow(self.exemptionLabel, self.exemptionEdit)
        self.exemptionLabel.hide()
        self.exemptionEdit.hide()

    def _update_exemption_visibility(self):
        # The reason is only needed (and printed) if at least one row has 0 % VAT
        visible = any(self.table.cellWidget(r, 4).currentData() == 0.0 for r in range(self.table.rowCount()) if self.table.cellWidget(r, 4))
        self.exemptionLabel.setVisible(visible)
        self.exemptionEdit.setVisible(visible)

    def _exemption_reason(self, items) -> str:
        return self.exemptionEdit.text().strip() if has_zero_rate(items) else ""

    def _check_exemption(self, items) -> bool:
        if has_zero_rate(items) and not self.exemptionEdit.text().strip():
            InfoBar.error("Befreiungsgrund fehlt", EXEMPTION_REQUIRED_MESSAGE, orient=Qt.Horizontal, isClosable=True,
                          position=InfoBarPosition.TOP, duration=5000, parent=self.window())
            return False
        return True

    def delete_row(self, btn):
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, 5)
            if hasattr(widget, 'del_btn') and widget.del_btn == btn:
                self.table.removeRow(row)
                self.update_totals()
                break
            elif widget == btn:
                self.table.removeRow(row)
                self.update_totals()
                break

    def _collect_items(self) -> list:
        items = []
        for row in range(self.table.rowCount()):
            title_widget = self.table.cellWidget(row, 0)
            title = title_widget.text()
            if not title: continue
            try:
                qty = float(self.table.cellWidget(row, 1).text().replace(',', '.'))
            except ValueError:
                qty = 1.0
            unit = self.table.cellWidget(row, 2).text()
            try:
                price = float(self.table.cellWidget(row, 3).text().replace(',', '.'))
            except ValueError:
                price = 0.0
            discount = getattr(title_widget, 'item_discount', 0.0)
            
            items.append({
                "title": title,
                "description": getattr(title_widget, 'item_description', None),
                "quantity": qty,
                "unit": unit,
                "unit_price": price,
                "discount_percent": discount,
                "tax_percent": self.table.cellWidget(row, 4).currentData(),
                "total_price": item_total(qty, price, discount)
            })
        return items

    def _credit_amount(self) -> float:
        if not self.creditCheck.isChecked():
            return 0.0
        try:
            return max(0.0, float(self.creditAmountEdit.text().replace(',', '.')))
        except ValueError:
            return 0.0

    def update_totals(self):
        # Rows without a title are ignored here exactly like when saving
        credit_amount = self._credit_amount()
        totals = calculate_totals(self._collect_items(), credit_amount)
        
        self.netTotalLabel.setText(f"Nettobetrag: {totals['net_amount']:.2f} €")
        
        if credit_amount > 0:
            self.creditTotalLabel.setText(f"abzgl. Gutschrift: {credit_amount:.2f} €")
            self.creditTotalLabel.show()
        else:
            self.creditTotalLabel.hide()
            
        if totals['tax_amount'] > 0:
            self.tax19Label.setText(f"zzgl. MwSt: {totals['tax_amount']:.2f} €")
            self.tax19Label.show()
        else:
            self.tax19Label.hide()
            
        self.grossTotalLabel.setText(f"Gesamtbetrag: {totals['gross_amount']:.2f} €")
        self._update_exemption_visibility()

    def save_invoice(self):
        if not self._check_exemption(self._collect_items()):
            return
        if not self.companyEdit.text().strip() and not self.nameEdit.text().strip():
            InfoBar.error(
                title="Fehler",
                content="Bitte geben Sie entweder eine Firma oder den Vor- und Nachnamen an.",
                orient=Qt.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self.window()
            )
            return

        address_line = self.addressEdit.text().strip()
        zip_code = self.postalCodeEdit.text().strip()
        city = self.cityEdit.text().strip()
                
        names = self.nameEdit.text().strip().split(" ", 1)
        first_name = names[0] if names else ""
        last_name = names[1] if len(names) > 1 else ""

        cust = self.customerCombo.itemData(self.customerCombo.currentIndex())
        if cust:
            customer_id = cust.id
            self.db_controller.update_customer(
                customer_id,
                company_name=self.companyEdit.text(),
                first_name=first_name,
                last_name=last_name,
                address=address_line,
                postal_code=zip_code,
                city=city
            )
        else:
            # Create new customer
            customer_id = self.db_controller.add_customer(
                company_name=self.companyEdit.text(),
                first_name=first_name,
                last_name=last_name,
                address=address_line,
                postal_code=zip_code,
                city=city
            )
            
        # 2. Collect Items
        items = self._collect_items()
            
        # 3. Create or Update Invoice
        qdate_inv = self.invoiceDate.date
        qdate_del = self.deliveryDate.date
        inv_date = datetime(qdate_inv.year(), qdate_inv.month(), qdate_inv.day(), tzinfo=timezone.utc)
        del_date = datetime(qdate_del.year(), qdate_del.month(), qdate_del.day(), tzinfo=timezone.utc)
        
        credit_amount = self._credit_amount()
        credit_desc = self.creditDescEdit.text() if credit_amount > 0 else ""
        
        try:
            saved_id = self._save(customer_id, inv_date, del_date, items, credit_amount, credit_desc)
        except (GoBDError, ValueError) as e:
            InfoBar.error("Nicht erlaubt", str(e), orient=Qt.Horizontal, isClosable=True,
                          position=InfoBarPosition.TOP, duration=6000, parent=self.window())
            return
        self.saved.emit(saved_id)

    def _save(self, customer_id, inv_date, del_date, items, credit_amount, credit_desc):
        if self.current_invoice_id:
            self.db_controller.update_invoice(
                invoice_id=self.current_invoice_id,
                customer_id=customer_id,
                invoice_date=inv_date,
                delivery_date=del_date,
                items=items,
                credit_amount=credit_amount,
                credit_desc=credit_desc,
                tax_exemption_reason=self._exemption_reason(items)
            )
            return self.current_invoice_id
        return self.db_controller.create_invoice(
            customer_id=customer_id,
            invoice_date=inv_date,
            delivery_date=del_date,
            items=items,
            credit_amount=credit_amount,
            credit_desc=credit_desc,
            tax_exemption_reason=self._exemption_reason(items)
        )

