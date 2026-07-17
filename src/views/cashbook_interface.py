from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QHeaderView, QFileDialog
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QDoubleValidator
from qfluentwidgets import SubtitleLabel, SearchLineEdit, PrimaryPushButton, BodyLabel, DatePicker, LineEdit, ComboBox, TransparentToolButton, TableWidget, InfoBar, InfoBarPosition, PushButton, FluentIcon as FIF
import os
import shutil
from datetime import datetime
from src.utils.signal_bus import SignalBus


class CashbookInterface(QWidget):
    def __init__(self, db_controller, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("CashbookInterface")
        self.db_controller = db_controller
        self.attachment_path = ""
        self.init_ui()
        SignalBus.get().cashbookAdded.connect(self.insert_row)
        SignalBus.get().cashbookUpdated.connect(self.update_row)
        SignalBus.get().cashbookDeleted.connect(self.remove_row)

    def init_ui(self):
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(24, 24, 24, 24)
        
        # Header
        headerLayout = QHBoxLayout()
        self.titleLabel = SubtitleLabel("Kassenbuch", self)
        
        self.searchLineEdit = SearchLineEdit(self)
        self.searchLineEdit.setPlaceholderText("Suchen...")
        self.searchLineEdit.setFixedWidth(200)
        self.searchLineEdit.textChanged.connect(self.filter_table)
        
        self.yearFilterCombo = ComboBox(self)
        self.yearFilterCombo.addItem("Alle Jahre")
        self.yearFilterCombo.setFixedWidth(130)
        self.yearFilterCombo.currentTextChanged.connect(self.filter_table)
        
        self.monthFilterCombo = ComboBox(self)
        self.monthFilterCombo.addItem("Alle Monate")
        self.monthFilterCombo.setFixedWidth(130)
        self.monthFilterCombo.currentTextChanged.connect(self.filter_table)
        
        self.datevExportBtn = PushButton("DATEV Export", self)
        self.datevExportBtn.clicked.connect(self.show_datev_export_dialog)
        
        self.addBtn = PrimaryPushButton("Eintrag hinzufügen")
        self.addBtn.clicked.connect(self.add_entry)
        
        headerLayout.addWidget(self.titleLabel)
        headerLayout.addStretch(1)
        headerLayout.addWidget(self.yearFilterCombo)
        headerLayout.addWidget(self.monthFilterCombo)
        headerLayout.addWidget(self.searchLineEdit)
        headerLayout.addWidget(self.datevExportBtn)
        headerLayout.addWidget(self.addBtn)
        self.vBoxLayout.addLayout(headerLayout)
        self.vBoxLayout.addSpacing(16)
        
        # Form Row
        formLayout = QHBoxLayout()
        
        # Datum
        dateLayout = QVBoxLayout()
        dateLayout.addWidget(BodyLabel("Datum"))
        self.datePicker = DatePicker()
        self.datePicker.setDate(QDate.currentDate())
        dateLayout.addWidget(self.datePicker)
        formLayout.addLayout(dateLayout)
        
        # Betrag
        amountLayout = QVBoxLayout()
        amountLayout.addWidget(BodyLabel("Betrag (€)"))
        from PySide6.QtCore import QLocale
        self.amountSpin = LineEdit()
        validator = QDoubleValidator(0.0, 10000000.0, 2)
        validator.setNotation(QDoubleValidator.StandardNotation)
        validator.setLocale(QLocale(QLocale.German, QLocale.Germany))
        self.amountSpin.setValidator(validator)
        self.amountSpin.setPlaceholderText("0,00")
        amountLayout.addWidget(self.amountSpin)
        formLayout.addLayout(amountLayout)
        
        # Art
        typeLayout = QVBoxLayout()
        typeLayout.addWidget(BodyLabel("Art"))
        self.typeCombo = ComboBox()
        self.typeCombo.addItems(["Einnahme", "Barentnahme Privat", "Barentnahme Firma"])
        typeLayout.addWidget(self.typeCombo)
        formLayout.addLayout(typeLayout)
        
        # Anhang
        attachLayout = QVBoxLayout()
        attachLayout.addWidget(BodyLabel("Beleg (Optional)"))
        attachBtnLayout = QHBoxLayout()
        self.attachBtn = TransparentToolButton(FIF.LINK)
        self.attachBtn.clicked.connect(self.attach_file)
        self.attachLabel = BodyLabel("Kein Anhang")
        attachBtnLayout.addWidget(self.attachBtn)
        attachBtnLayout.addWidget(self.attachLabel)
        attachBtnLayout.addStretch(1)
        attachLayout.addLayout(attachBtnLayout)
        formLayout.addLayout(attachLayout)
        
        formLayout.addStretch(1)
        
        # Kassenbestand
        balanceLayout = QVBoxLayout()
        balanceLayout.addWidget(BodyLabel("Aktueller Kassenbestand"))
        self.balanceLabel = SubtitleLabel("0,00 €")
        balanceLayout.addWidget(self.balanceLabel)
        
        formLayout.addLayout(balanceLayout)
        
        self.vBoxLayout.addLayout(formLayout)
        self.vBoxLayout.addSpacing(20)
        
        # Table
        self.table = TableWidget(self)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(['Datum', 'Beleg-Nr', 'Art', 'Betrag (€)', 'GoBD-Hash', 'Anhang'])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
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

    def show_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item: return
        row = item.row()
        
        # In cashbook, we don't have ID in the table directly, we'd need to match or just use the row index
        # Let's get the entries list from db to match the row
        entries = self.db_controller.get_cashbook_entries()
        if row >= len(entries): return
        entry = entries[row] # This assumes table order matches get_cashbook_entries
        
        if not (entry.description and entry.description != "Keine Angabe" and os.path.exists(entry.description)):
            return
            
        from qfluentwidgets import RoundMenu, Action
        from qfluentwidgets import FluentIcon as FIF
        menu = RoundMenu(parent=self.table)
        
        view_action = Action(FIF.DOCUMENT, "Beleg öffnen", self)
        view_action.triggered.connect(lambda: os.startfile(entry.description) if os.name == 'nt' else None)
        menu.addAction(view_action)
            
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def on_item_double_clicked(self, item):
        row = item.row()
        entries = self.db_controller.get_cashbook_entries()
        if row >= len(entries): return
        entry = entries[row]
        
        if entry.description and entry.description != "Keine Angabe" and os.path.exists(entry.description):
            if os.name == 'nt':
                os.startfile(entry.description)

    def attach_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Beleg auswählen",
            "",
            "Dokumente (*.pdf *.png *.jpg *.jpeg)"
        )
        if path:
            self.attachment_path = path
            self.attachLabel.setText(os.path.basename(path))

    def add_entry(self):
        amount_text = self.amountSpin.text().replace(',', '.')
        try:
            amount = float(amount_text)
            if amount <= 0: raise ValueError
        except ValueError:
            InfoBar.error("Fehler", "Bitte einen gültigen Betrag eingeben", position=InfoBarPosition.TOP, parent=self.window())
            return
            
        entry_type = self.typeCombo.currentText()
        
        # Check negative balance
        if entry_type != "Einnahme":
            # Calculate current total balance
            all_entries = self.db_controller.get_cashbook_entries()
            current_balance = sum([e.amount if e.entry_type == "Einnahme" else -e.amount for e in all_entries])
            if current_balance - amount < 0:
                InfoBar.error("Fehler", "Der Kassenbestand darf nicht negativ werden!", position=InfoBarPosition.TOP, parent=self.window())
                return
            
        date_obj = self.datePicker.date.toPython()
        dt = datetime.combine(date_obj, datetime.min.time())
        
        # Handle attachment
        desc = "Keine Angabe"
        if self.attachment_path and os.path.exists(self.attachment_path):
            receipts_dir = os.path.join(os.getcwd(), "assets", "receipts")
            os.makedirs(receipts_dir, exist_ok=True)
            filename = os.path.basename(self.attachment_path)
            new_path = os.path.join(receipts_dir, filename)
            shutil.copy2(self.attachment_path, new_path)
            desc = new_path
            
        self.db_controller.add_cashbook_entry(
            entry_date=dt,
            amount=amount,
            description=desc,
            category="Allgemein",
            entry_type=entry_type,
            tax_percent=19.0
        )
        
        InfoBar.success("Erfolg", "GoBD-konformer Eintrag gespeichert", position=InfoBarPosition.TOP, parent=self.window())
        self.amountSpin.setText("")
        self.attachment_path = ""
        self.attachLabel.setText("Kein Anhang")
        self.load_data()



    def update_balance(self, entries):
        balance = 0.0
        for entry in entries:
            if entry.entry_type == 'Einnahme':
                balance += entry.amount
            else:
                balance -= entry.amount
        
        self.balanceLabel.setText(f'{balance:.2f} €')

    def showEvent(self, event):

        super().showEvent(event)

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

    def load_data(self):
        from PySide6.QtWidgets import QTableWidgetItem

        self.table.setRowCount(0)
        entries = self.db_controller.get_cashbook_entries()
        
        available_years = set()
        available_months = set()
        for entry in entries:
            if entry.entry_date:
                available_years.add(entry.entry_date.strftime("%Y"))
                available_months.add(entry.entry_date.strftime("%m"))
                
        current_year = self.yearFilterCombo.currentText()
        self.yearFilterCombo.blockSignals(True)
        self.yearFilterCombo.clear()
        self.yearFilterCombo.addItem("Alle Jahre")
        for y in sorted(list(available_years), reverse=True):
            self.yearFilterCombo.addItem(y)
        if current_year in available_years or current_year == "Alle Jahre":
            self.yearFilterCombo.setCurrentText(current_year)
        self.yearFilterCombo.blockSignals(False)

        current_month = self.monthFilterCombo.currentText()
        self.monthFilterCombo.blockSignals(True)
        self.monthFilterCombo.clear()
        self.monthFilterCombo.addItem("Alle Monate")
        for m in sorted(list(available_months)):
            self.monthFilterCombo.addItem(m)
        if current_month in available_months or current_month == "Alle Monate":
            self.monthFilterCombo.setCurrentText(current_month)
        self.monthFilterCombo.blockSignals(False)
        
        current_row = 0
        for entry in entries:
            self._update_or_insert_row(current_row, entry, is_new=True)
            current_row += 1
        self.update_balance(entries)
        self.filter_table()


    def _update_or_insert_row(self, i, entry, is_new=False):
        from PySide6.QtWidgets import QTableWidgetItem, QWidget, QHBoxLayout
        from PySide6.QtCore import Qt
        from qfluentwidgets import PushButton
                
        if is_new:
            self.table.insertRow(i)
        self.table.setItem(i, 0, QTableWidgetItem(entry.entry_date.strftime("%d.%m.%Y")))
        self.table.setItem(i, 1, QTableWidgetItem(entry.receipt_number))
        self.table.setItem(i, 2, QTableWidgetItem(entry.entry_type))
        
        amount_str = f"{entry.amount:.2f}".replace(".", ",") + " €"
        if entry.entry_type in ["Ausgabe", "Barentnahme Privat", "Barentnahme Firma"]:
            amount_str = f"-{amount_str}"
        self.table.setItem(i, 3, QTableWidgetItem(amount_str))
        
        hash_abbr = f"{entry.hash_chain[:8]}...{entry.hash_chain[-8:]}" if entry.hash_chain else "Kein Hash"
        self.table.setItem(i, 4, QTableWidgetItem(hash_abbr))
        
        if entry.description and entry.description != "Keine Angabe" and os.path.exists(entry.description):
            self.table.setItem(i, 5, QTableWidgetItem("Vorhanden"))
        else:
            self.table.setItem(i, 5, QTableWidgetItem("-"))
            
        
    def show_datev_export_dialog(self):
        from src.models.database import CashbookEntry
        from src.utils.datev_generator import DatevGenerator
        import os
        
        available_months = set()
        with self.db_controller.get_session() as session:
            entries = session.query(CashbookEntry).all()
            for entry in entries:
                available_months.add(f"{entry.entry_date.year}-{entry.entry_date.month:02d}")
                
        if not available_months:
            InfoBar.warning("Keine Daten", "Es gibt keine Kassenbucheinträge zum Exportieren.", parent=self)
            return
            
        months_list = sorted(list(available_months), reverse=True)
        
        from qfluentwidgets import MessageBoxBase, SubtitleLabel, ComboBox
        class DatevDialog(MessageBoxBase):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.titleLabel = SubtitleLabel('DATEV Monats-Export (Kassenbuch)', self)
                self.viewLayout.addWidget(self.titleLabel)
                self.monthCombo = ComboBox(self)
                self.monthCombo.addItems(months_list)
                self.viewLayout.addWidget(self.monthCombo)
                self.widget.setMinimumWidth(350)
                
        dialog = DatevDialog(self)
        if dialog.exec():
            selected = dialog.monthCombo.currentText()
            year, month = map(int, selected.split('-'))
            
            with self.db_controller.get_session() as session:
                all_entries = session.query(CashbookEntry).all()
                export_entries = [e for e in all_entries if e.entry_date.year == year and e.entry_date.month == month]
                
                if not export_entries:
                    return
                    
                filename = f"DATEV_Export_Kassenbuch_{year}_{month:02d}.zip"
                filepath = os.path.join(os.path.expanduser("~"), "Desktop", filename)
                
                generator = DatevGenerator(self.db_controller)
                if generator.generate_cashbook_export(export_entries, filepath, month, year):
                    # Record history
                    from src.models.database import DocumentHistory
                    for entry in export_entries:
                        h = DocumentHistory(document_type="Cashbook", document_id=entry.id, user="System", action="DATEV Export")
                        session.add(h)
                    session.commit()
                    self.db_controller.db.save()
                    
                    InfoBar.success(
                        title="DATEV Export erfolgreich",
                        content=f"Das DATEV ZIP-Archiv für {month:02d}/{year} ({len(export_entries)} Einträge) wurde auf dem Desktop gespeichert:\n{filename}",
                        parent=self,
                        duration=5000
                    )
                else:
                    InfoBar.error(
                        title="Fehler beim DATEV Export",
                        content="Die Export-Datei konnte nicht generiert werden.",
                        parent=self,
                        duration=4000
                    )


    def insert_row(self, entry_id):
        entry = self.db_controller.get_cashbook_entry(entry_id)
        if not entry: return
        self._update_or_insert_row(0, entry, is_new=True)
        self.update_balance(self.db_controller.get_cashbook_entries())
        self.filter_table()

    def update_row(self, entry_id):
        entry = self.db_controller.get_cashbook_entry(entry_id)
        if not entry: return
        from PySide6.QtCore import Qt
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == entry_id:
                self.table.removeCellWidget(row, 5)
                self._update_or_insert_row(row, entry, is_new=False)
                self.update_balance(self.db_controller.get_cashbook_entries())
                self.filter_table()
                break

    def remove_row(self, entry_id):
        from PySide6.QtCore import Qt
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == entry_id:
                self.table.removeRow(row)
                self.update_balance(self.db_controller.get_cashbook_entries())
                self.filter_table()
                break
