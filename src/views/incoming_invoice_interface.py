import os
import shutil
import re
from datetime import datetime
from pypdf import PdfReader
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QHeaderView, QFileDialog, QTableWidgetItem
from PySide6.QtCore import Qt
from qfluentwidgets import (SubtitleLabel, PrimaryPushButton, TableWidget, InfoBar, 
                            InfoBarPosition, PushButton, MessageBoxBase, LineEdit, BodyLabel, DatePicker, DoubleSpinBox, ComboBox, SearchLineEdit)
from src.utils.signal_bus import SignalBus

class IncomingInvoiceDialog(MessageBoxBase):
    def __init__(self, parent, default_amount=0.0, default_date=None, default_desc=""):
        super().__init__(parent)
        self.titleLabel = SubtitleLabel('Rechnungsdaten bestätigen', self)
        
        # UI components
        self.descLabel = BodyLabel("Beschreibung / Dateiname", self)
        self.descEdit = LineEdit(self)
        self.descEdit.setText(default_desc)
        
        self.dateLabel = BodyLabel("Datum", self)
        self.datePicker = DatePicker(self)
        from PySide6.QtCore import QDate
        if default_date:
            self.datePicker.setDate(QDate(default_date.year, default_date.month, default_date.day))
            
        self.amountLabel = BodyLabel("Betrag (€)", self)
        self.amountSpin = DoubleSpinBox(self)
        self.amountSpin.setRange(0.0, 999999.99)
        self.amountSpin.setValue(default_amount)
        
        # Add to layout
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.descLabel)
        self.viewLayout.addWidget(self.descEdit)
        self.viewLayout.addWidget(self.dateLabel)
        self.viewLayout.addWidget(self.datePicker)
        self.viewLayout.addWidget(self.amountLabel)
        self.viewLayout.addWidget(self.amountSpin)
        
        self.widget.setMinimumWidth(350)
        
    def get_data(self):
        return {
            "description": self.descEdit.text(),
            "date": datetime.combine(self.datePicker.date.toPython(), datetime.min.time()),
            "amount": self.amountSpin.value()
        }

class IncomingInvoiceInterface(QWidget):
    def __init__(self, db_controller, invoice_type, parent=None):
        super().__init__(parent=parent)
        self.db_controller = db_controller
        self.invoice_type = invoice_type # "Lieferant" or "Sonstige"
        self.setObjectName(f"IncomingInvoiceInterface_{invoice_type}")
        self._needs_reload = True
        SignalBus.get().incomingInvoiceAdded.connect(self.insert_row)
        SignalBus.get().incomingInvoiceUpdated.connect(self.update_row)
        SignalBus.get().incomingInvoiceDeleted.connect(self.remove_row)
        self.init_ui()
        
    def init_ui(self):
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(24, 24, 24, 24)
        
        # Header
        headerLayout = QHBoxLayout()
        title_text = "Lieferantenrechnungen" if self.invoice_type == "Lieferant" else "Sonstige Rechnungen"
        self.titleLabel = SubtitleLabel(title_text, self)
        
        self.uploadBtn = PrimaryPushButton("PDF Hochladen", self)
        self.uploadBtn.clicked.connect(self.upload_pdf)
        
        self.exportBtn = PushButton("DATEV Export", self)
        self.exportBtn.clicked.connect(self.export_datev)
        
        self.searchLineEdit = SearchLineEdit(self)
        self.searchLineEdit.setPlaceholderText("Suchen...")
        self.searchLineEdit.setFixedWidth(200)
        self.searchLineEdit.textChanged.connect(self.filter_table)
        
        self.monthFilterCombo = ComboBox(self)
        self.monthFilterCombo.addItem("Alle Monate")
        self.monthFilterCombo.addItems([f"{i:02d}" for i in range(1, 13)])
        self.monthFilterCombo.setFixedWidth(130)
        self.monthFilterCombo.currentTextChanged.connect(self.filter_table)
        
        self.yearFilterCombo = ComboBox(self)
        self.yearFilterCombo.addItem("Alle Jahre")
        self.yearFilterCombo.setFixedWidth(130)
        self.yearFilterCombo.currentTextChanged.connect(self.filter_table)
        
        headerLayout.addWidget(self.titleLabel)
        headerLayout.addStretch(1)
        headerLayout.addWidget(self.searchLineEdit)
        headerLayout.addWidget(self.monthFilterCombo)
        headerLayout.addWidget(self.yearFilterCombo)
        headerLayout.addWidget(self.exportBtn)
        headerLayout.addWidget(self.uploadBtn)
        
        self.vBoxLayout.addLayout(headerLayout)
        
        # Table
        self.table = TableWidget(self)
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Datum", "Beschreibung", "Betrag"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(45)
        from PySide6.QtWidgets import QAbstractItemView
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.verticalHeader().hide()
        
        # Performance optimization for scrolling with setCellWidget
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(45)
        from PySide6.QtWidgets import QAbstractItemView
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.itemDoubleClicked.connect(self.on_item_double_clicked)
        
        self.vBoxLayout.addWidget(self.table)
        
        self.load_data()
        

    def showEvent(self, event):
        super().showEvent(event)
        if self._needs_reload:
            self.load_data()
            self._needs_reload = False

    def show_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item: return
        row = item.row()
        inv_id_item = self.table.item(row, 0)
        if not inv_id_item: return
        inv_id = inv_id_item.data(Qt.UserRole)
        
        # We need to get the invoice to know the path
        invoices = self.db_controller.get_incoming_invoices(self.invoice_type)
        inv = next((i for i in invoices if i.id == inv_id), None)
        if not inv: return

        from qfluentwidgets import RoundMenu, Action
        from qfluentwidgets import FluentIcon as FIF
        menu = RoundMenu(parent=self.table)
        
        view_action = Action(FIF.DOCUMENT, "Öffnen", self)
        view_action.triggered.connect(lambda: self.open_pdf(inv.file_path))
        menu.addAction(view_action)
        
        delete_action = Action(FIF.DELETE, "Löschen", self)
        delete_action.triggered.connect(lambda: self.delete_invoice(inv_id))
        menu.addAction(delete_action)
            
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def on_item_double_clicked(self, item):
        row = item.row()
        inv_id_item = self.table.item(row, 0)
        if not inv_id_item: return
        inv_id = inv_id_item.data(Qt.UserRole)
        
        invoices = self.db_controller.get_incoming_invoices(self.invoice_type)
        inv = next((i for i in invoices if i.id == inv_id), None)
        if inv:
            self.open_pdf(inv.file_path)

    def filter_table(self):
        search_text = self.searchLineEdit.text().lower()
        year_filter = self.yearFilterCombo.currentText()
        month_filter = self.monthFilterCombo.currentText()
        
        for i in range(self.table.rowCount()):
            date_item = self.table.item(i, 0)
            if not date_item: continue
            date_text = date_item.text()
            row_month = date_text[3:5] if len(date_text) >= 10 else ''
            row_year = date_text[6:10] if len(date_text) >= 10 else ''
            
            match_year = (year_filter == 'Alle Jahre' or row_year == year_filter)
            match_month = (month_filter == 'Alle Monate' or row_month == month_filter)
            match_search = False
            if not search_text: match_search = True
            else:
                for col in range(1, 4):
                    item = self.table.item(i, col)
                    if item and search_text in item.text().lower():
                        match_search = True
                        break
            self.table.setRowHidden(i, not (match_year and match_month and match_search))
            
        self.update_export_btn_state()
        
    def update_export_btn_state(self):
        visible_rows = 0
        for i in range(self.table.rowCount()):
            if not self.table.isRowHidden(i):
                visible_rows += 1
        self.exportBtn.setEnabled(visible_rows > 0)

    def load_data(self):

        invoices = self.db_controller.get_incoming_invoices(self.invoice_type)
        self.table.setRowCount(len(invoices))
        for i, inv in enumerate(invoices):
            first_item = QTableWidgetItem(inv.date.strftime('%d.%m.%Y'))
            first_item.setData(Qt.UserRole, inv.id)
            self.table.setItem(i, 0, first_item)
            self.table.setItem(i, 1, QTableWidgetItem(inv.description))
            self.table.setItem(i, 2, QTableWidgetItem(f"{inv.amount:.2f} €"))
            self.table.setRowHeight(i, 45)
            
        
        # Update year filter
        years = set()
        for inv in invoices:
            if inv.date:
                years.add(str(inv.date.year))
        
        current_year = self.yearFilterCombo.currentText()
        self.yearFilterCombo.blockSignals(True)
        self.yearFilterCombo.clear()
        self.yearFilterCombo.addItem("Alle Jahre")
        for y in sorted(list(years), reverse=True):
            self.yearFilterCombo.addItem(y)
        if current_year in years:
            self.yearFilterCombo.setCurrentText(current_year)
        self.yearFilterCombo.blockSignals(False)
        
        self.filter_table()

            
    def open_pdf(self, path):
        if os.path.exists(path):
            os.startfile(path)
        else:
            InfoBar.error("Fehler", "PDF Datei nicht gefunden.", position=InfoBarPosition.TOP, parent=self.window())
            
    def delete_invoice(self, invoice_id):
        if self.db_controller.delete_incoming_invoice(invoice_id):
            # Find and remove row instantly for performance
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item and item.data(Qt.UserRole) == invoice_id:
                    self.table.removeRow(row)
                    break
            InfoBar.success("Erfolg", "Rechnung gelöscht.", position=InfoBarPosition.TOP, parent=self.window())
            
    def extract_data_from_pdf(self, path):
        amount = 0.0
        date_obj = datetime.now().date()
        try:
            reader = PdfReader(path)
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"
                
            # Regex to find amount
            # Matches variations of Gesamtbetrag, Rechnungsbetrag, Endbetrag followed by number
            amount_match = re.search(r'(?:Gesamtbetrag|Rechnungsbetrag|Endbetrag|Summe|Total|Betrag)[\s\S]{0,30}?(\d{1,3}(?:[.,]\d{3})*[.,]\d{2})', text, re.IGNORECASE)
            if amount_match:
                amt_str = amount_match.group(1).replace('.', '').replace(',', '.')
                # If the string was something like 1.234.56, replacing . gives 123456 which is wrong if , was used for thousands.
                # Standard DE format: 1.234,56 -> 1234.56
                # If there are no dots but a comma: 1234,56 -> 1234.56
                # Let's clean it up robustly:
                val = amount_match.group(1)
                if ',' in val and '.' in val:
                    val = val.replace('.', '').replace(',', '.')
                elif ',' in val:
                    val = val.replace(',', '.')
                amount = float(val)
                
            # Regex to find date
            # Matches variations of Datum, Rechnungsdatum, Leistungsdatum
            date_match = re.search(r'(?:Datum|Rechnungsdatum|Leistungsdatum|Lieferdatum)[\s\S]{0,30}?(\d{2}\.\d{2}\.\d{4})', text, re.IGNORECASE)
            if date_match:
                date_str = date_match.group(1)
                date_obj = datetime.strptime(date_str, '%d.%m.%Y').date()
                
        except Exception as e:
            print(f"Error parsing PDF: {e}")
            
        return amount, date_obj

    def upload_pdf(self):
        filepaths, _ = QFileDialog.getOpenFileNames(
            self,
            "PDF Rechnungen auswählen",
            "",
            "PDF Dateien (*.pdf)"
        )
        if not filepaths:
            return
            
        for filepath in filepaths:
            # Parse PDF
            amount, date_obj = self.extract_data_from_pdf(filepath)
            filename = os.path.basename(filepath)
            
            # Show Dialog
            dialog = IncomingInvoiceDialog(self.window(), default_amount=amount, default_date=date_obj, default_desc=filename)
            if dialog.exec():
                data = dialog.get_data()
                
                # Save PDF internally
                dest_dir = os.path.abspath("app_data/incoming_invoices")
                os.makedirs(dest_dir, exist_ok=True)
                safe_filename = f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{filename}"
                dest_path = os.path.join(dest_dir, safe_filename)
                shutil.copy2(filepath, dest_path)
                
                # Save to DB
                self.db_controller.add_incoming_invoice(
                    invoice_type=self.invoice_type,
                    date=data["date"],
                    amount=data["amount"],
                    description=data["description"],
                    file_path=dest_path
                )
                
        self.load_data()
        InfoBar.success("Erfolg", f"{len(filepaths)} Eingangsrechnungen bearbeitet.", position=InfoBarPosition.TOP, parent=self.window())

    def export_datev(self):
        from src.utils.datev_generator import DatevGenerator
        
        # We export the currently visible invoices
        invoices = self.db_controller.get_incoming_invoices(self.invoice_type)
        if not invoices:
            InfoBar.warning("Keine Daten", "Es gibt keine Rechnungen für den Export.", position=InfoBarPosition.TOP, parent=self.window())
            return
            
        filepath, _ = QFileDialog.getSaveFileName(
            self,
            "DATEV ZIP Export speichern",
            f"DATEV_Eingangsrechnungen_{self.invoice_type}_{datetime.now().strftime('%Y%m%d')}.zip",
            "ZIP Dateien (*.zip)"
        )
        
        if filepath:
            generator = DatevGenerator(self.db_controller)
            if generator.generate_incoming_export(invoices, filepath):
                InfoBar.success("Erfolg", "DATEV Export erfolgreich erstellt.", position=InfoBarPosition.TOP, parent=self.window())
            else:
                InfoBar.error("Fehler", "Fehler beim Erstellen des DATEV Exports.", position=InfoBarPosition.TOP, parent=self.window())

    def insert_row(self, invoice_id):
        invoice = self.db_controller.get_incoming_invoice(invoice_id)
        if not invoice: return
        if invoice.invoice_type == self.invoice_type:
            self.load_data() # For incoming invoices, there are so few, load_data is very fast and we don't have to rewrite the complex PDF extraction loop

    def update_row(self, invoice_id):
        self.load_data()

    def remove_row(self, invoice_id):
        from PySide6.QtCore import Qt
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == invoice_id:
                self.table.removeRow(row)
                break
