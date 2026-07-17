from PySide6.QtCore import Signal
from qfluentwidgets import ComboBox, DatePicker, InfoBar, InfoBarPosition, LineEdit, PrimaryPushButton, PushButton, SubtitleLabel, TableWidget
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QFormLayout, QHBoxLayout, QHeaderView, QVBoxLayout, QWidget
from src.controllers.db_controller import DBController
from datetime import datetime, timezone

class QuoteEditor(QWidget):
    saved = Signal(int)
    canceled = Signal()

    def __init__(self, db_controller: DBController, parent=None):
        super().__init__(parent=parent)
        self.db_controller = db_controller
        self.current_quote_id = None
        self.init_ui()

    def init_ui(self):
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(24, 24, 24, 24)
        
        # Header
        headerLayout = QHBoxLayout()
        self.backBtn = PushButton("Zurück")
        self.backBtn.clicked.connect(self.canceled.emit)
        
        self.titleLabel = SubtitleLabel("Neues Angebot")
        
        self.saveBtn = PrimaryPushButton("Angebot speichern")
        self.saveBtn.clicked.connect(self.save_quote)
        
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
        self.quoteDate = DatePicker()
        self.quoteDate.setDate(QDate.currentDate())
        dateForm.addRow("Angebotsdatum", self.quoteDate)
        
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
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(['Bezeichnung', 'Menge', 'Einheit', 'Einzelpreis (€)', 'Aktion'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setColumnWidth(1, 140)
        self.table.setColumnWidth(2, 100)
        self.table.setColumnWidth(3, 180)
        self.table.setColumnWidth(4, 50)
        self.table.verticalHeader().hide()
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
        self.grossTotalLabel = SubtitleLabel("Gesamtbetrag: 0,00 €")
        self.grossTotalLabel.setAlignment(Qt.AlignRight)
        
        totalsLayout.addWidget(self.netTotalLabel)
        totalsLayout.addWidget(self.tax19Label)
        totalsLayout.addWidget(self.grossTotalLabel)
        
        self.vBoxLayout.addLayout(totalsLayout)

    def clear_form(self):
        self.current_quote_id = None
        self.set_read_only(False)
        self.titleLabel.setText("Neues Angebot")
        self.companyEdit.clear()
        self.nameEdit.clear()
        self.addressEdit.clear()
        self.postalCodeEdit.clear()
        self.cityEdit.clear()
        self.quoteDate.setDate(QDate.currentDate())
        self.table.setRowCount(0)
        self.load_customers()
        self.update_totals()

    def load_quote(self, quote_id: int):
        self.clear_form()
        self.current_quote_id = quote_id
        quote = self.db_controller.get_quote(quote_id)
        if not quote: return
        
        self.titleLabel.setText(f"Angebot {quote.quote_number} bearbeiten")
        
        for i in range(self.customerCombo.count()):
            cust = self.customerCombo.itemData(i)
            if cust and cust.id == quote.customer_id:
                self.customerCombo.setCurrentIndex(i)
                break
                
        self.quoteDate.setDate(QDate(quote.quote_date.year, quote.quote_date.month, quote.quote_date.day))
        
        self.table.setRowCount(0)
        for item in quote.items:
            self.add_item_row()
            row = self.table.rowCount() - 1
            self.table.cellWidget(row, 0).setText(item.title)
            self.table.cellWidget(row, 1).setText(f"{item.quantity:.2f}".replace('.', ','))
            self.table.cellWidget(row, 2).setText(item.unit)
            self.table.cellWidget(row, 3).setText(f"{item.unit_price:.2f}".replace('.', ','))
            
        self.update_totals()
        
        if quote.status == "Archiviert":
            self.set_read_only(True)
            self.titleLabel.setText(f"Angebot {quote.quote_number} (Archiviert)")

    def set_read_only(self, read_only: bool):
        self.saveBtn.setVisible(not read_only)
        self.addItemBtn.setVisible(not read_only)
        self.customerCombo.setEnabled(not read_only)
        self.companyEdit.setEnabled(not read_only)
        self.nameEdit.setEnabled(not read_only)
        self.addressEdit.setEnabled(not read_only)
        self.postalCodeEdit.setEnabled(not read_only)
        self.cityEdit.setEnabled(not read_only)
        self.quoteDate.setEnabled(not read_only)
        
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
        self.table.setRowHeight(row, 45)
        
        widget_height = 32
        
        title_edit = LineEdit()
        title_edit.setFixedHeight(widget_height)
        
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
        
        read_only = not self.saveBtn.isVisible()
        title_edit.setEnabled(not read_only)
        qty_spin.setEnabled(not read_only)
        unit_edit.setEnabled(not read_only)
        price_spin.setEnabled(not read_only)
        container.setVisible(not read_only)
        
        self.table.setCellWidget(row, 0, title_edit)
        self.table.setCellWidget(row, 1, qty_spin)
        self.table.setCellWidget(row, 2, unit_edit)
        self.table.setCellWidget(row, 3, price_spin)
        self.table.setCellWidget(row, 4, container)

    def delete_row(self, btn):
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, 4)
            if hasattr(widget, 'del_btn') and widget.del_btn == btn:
                self.table.removeRow(row)
                self.update_totals()
                break
            elif widget == btn:
                self.table.removeRow(row)
                self.update_totals()
                break

    def update_totals(self):
        net_total = 0.0
        tax19_total = 0.0
        tax7_total = 0.0
        
        for row in range(self.table.rowCount()):
            try:
                qty_widget = self.table.cellWidget(row, 1)
                price_widget = self.table.cellWidget(row, 3)
                if qty_widget and price_widget:
                    try:
                        qty = float(qty_widget.text().replace(',', '.'))
                    except ValueError:
                        qty = 1.0
                    try:
                        price = float(price_widget.text().replace(',', '.'))
                    except ValueError:
                        price = 0.0
                    tax = 19.0
                    
                    net = qty * price
                    net_total += net
                    
                    tax_amount = net * (tax / 100)
                    if tax == 19.0:
                        tax19_total += tax_amount
                    elif tax == 7.0:
                        tax7_total += tax_amount
            except Exception as e:
                pass
                
        gross_total = net_total + tax19_total + tax7_total
        
        self.netTotalLabel.setText(f"Nettobetrag: {net_total:.2f} €")
        
        if tax19_total > 0:
            self.tax19Label.setText(f"zzgl. 19% MwSt: {tax19_total:.2f} €")
            self.tax19Label.show()
        else:
            self.tax19Label.hide()
            
        self.grossTotalLabel.setText(f"Gesamtbetrag: {gross_total:.2f} €")

    def save_quote(self):
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
            customer_id = self.db_controller.add_customer(
                company_name=self.companyEdit.text(),
                first_name=first_name,
                last_name=last_name,
                address=address_line,
                postal_code=zip_code,
                city=city
            )
            
        items = []
        for row in range(self.table.rowCount()):
            title = self.table.cellWidget(row, 0).text()
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
            tax = 19.0
            
            items.append({
                "title": title,
                "quantity": qty,
                "unit": unit,
                "unit_price": price,
                "tax_percent": tax,
                "total_price": qty * price
            })
            
        qdate_q = self.quoteDate.date
        q_date = datetime(qdate_q.year(), qdate_q.month(), qdate_q.day(), tzinfo=timezone.utc)
        
        if self.current_quote_id:
            self.db_controller.update_quote(
                quote_id=self.current_quote_id,
                customer_id=customer_id,
                quote_date=q_date,
                items=items
            )
            saved_id = self.current_quote_id
        else:
            saved_id = self.db_controller.create_quote(
                customer_id=customer_id,
                quote_date=q_date,
                items=items
            )
        self.saved.emit(saved_id)

