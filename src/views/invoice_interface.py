from qfluentwidgets import ComboBox, InfoBar, InfoBarPosition, PrimaryPushButton, PushButton, SearchLineEdit, SubtitleLabel, TableWidget
from PySide6.QtWidgets import QHBoxLayout, QHeaderView, QStackedWidget, QTableWidgetItem, QVBoxLayout, QWidget
from PySide6.QtCore import Qt
from src.controllers.db_controller import DBController
import os
from src.views.invoice_editor import InvoiceEditor
from src.utils.signal_bus import SignalBus


class InvoiceInterface(QWidget):
    def __init__(self, db_controller: DBController, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("InvoiceInterface")
        self.db_controller = db_controller
        
        SignalBus.get().dataChanged.connect(self.mark_dirty)
        
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        
        self.stackedWidget = QStackedWidget(self)
        self.vBoxLayout.addWidget(self.stackedWidget)
        
        # View 1: List
        self.list_view = QWidget()
        self.init_list_view()
        self.stackedWidget.addWidget(self.list_view)
        
        # View 2: Editor
        self.editor_view = InvoiceEditor(self.db_controller)
        self.editor_view.saved.connect(self.on_invoice_saved)
        self.editor_view.canceled.connect(lambda: self.show_list_view(reload=False))
        self.stackedWidget.addWidget(self.editor_view)
        
        self.show_list_view()
        SignalBus.get().invoiceAdded.connect(self.insert_row)
        SignalBus.get().invoiceUpdated.connect(self.update_row)
        SignalBus.get().invoiceDeleted.connect(self.remove_row)

    def init_list_view(self):
        layout = QVBoxLayout(self.list_view)
        layout.setContentsMargins(24, 24, 24, 24)
        
        # Header
        headerLayout = QHBoxLayout()
        self.titleLabel = SubtitleLabel("Rechnungen", self.list_view)
        
        self.searchLineEdit = SearchLineEdit(self.list_view)
        self.searchLineEdit.setPlaceholderText("Suchen...")
        self.searchLineEdit.setFixedWidth(200)
        self.searchLineEdit.textChanged.connect(self.filter_table)
        
        self.yearFilterCombo = ComboBox(self.list_view)
        self.yearFilterCombo.addItem("Alle Jahre")
        self.yearFilterCombo.setFixedWidth(130)
        self.yearFilterCombo.currentTextChanged.connect(self.filter_table)
        
        self.monthFilterCombo = ComboBox(self.list_view)
        self.monthFilterCombo.addItem("Alle Monate")
        self.monthFilterCombo.setFixedWidth(130)
        self.monthFilterCombo.currentTextChanged.connect(self.filter_table)
        
        self.datevExportBtn = PushButton("DATEV Export", self.list_view)
        self.datevExportBtn.clicked.connect(self.show_datev_export_dialog)
        
        self.newInvoiceBtn = PrimaryPushButton("Neue Rechnung", self.list_view)
        self.newInvoiceBtn.clicked.connect(self.show_editor_view)
        
        headerLayout.addWidget(self.titleLabel)
        headerLayout.addStretch(1)
        headerLayout.addWidget(self.yearFilterCombo)
        headerLayout.addWidget(self.monthFilterCombo)
        headerLayout.addWidget(self.searchLineEdit)
        headerLayout.addWidget(self.datevExportBtn)
        headerLayout.addWidget(self.newInvoiceBtn)
        
        layout.addLayout(headerLayout)
        
        # Table
        self.table = TableWidget(self.list_view)
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(['Datum', 'Rechnungsnummer', 'Kunde', 'Betrag', 'Zahlungsziel', 'Status'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.table.setColumnWidth(0, 100)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.table.setColumnWidth(1, 150)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Interactive)
        self.table.setColumnWidth(3, 120)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Interactive)
        self.table.setColumnWidth(4, 150)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Interactive)
        self.table.setColumnWidth(5, 160)

        
        # Performance optimization for scrolling with setCellWidget
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(45)
        from PySide6.QtWidgets import QAbstractItemView
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.itemDoubleClicked.connect(self.on_item_double_clicked)
        
        layout.addWidget(self.table)
        
        self.load_data()

    def mark_dirty(self):
        self._needs_reload = True

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, '_needs_reload', True):
            self.load_data()
            self._needs_reload = False

    def show_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item: return
        row = item.row()
        inv_id_item = self.table.item(row, 0)
        if not inv_id_item: return
        inv_id = inv_id_item.data(Qt.UserRole)
        
        inv = self.db_controller.get_invoice(inv_id)
        if not inv: return

        from qfluentwidgets import RoundMenu, Action
        from qfluentwidgets import FluentIcon as FIF
        menu = RoundMenu(parent=self.table)
        
        edit_action = Action(FIF.EDIT, "Anzeigen" if inv.archived_at else "Bearbeiten", self)
        edit_action.triggered.connect(lambda: self.show_editor_view(inv_id))
        menu.addAction(edit_action)
        
        if inv.archived_at is not None:
            pdf_action = Action(FIF.DOCUMENT, "PDF erstellen", self)
            pdf_action.triggered.connect(lambda: self.generate_pdf_for_invoice(inv_id))
            menu.addAction(pdf_action)
            
            print_action = Action(FIF.PRINT, "Drucken", self)
            print_action.triggered.connect(lambda: self.generate_pdf_for_invoice(inv_id, print_only=True))
            menu.addAction(print_action)
        else:
            archive_action = Action(FIF.FOLDER, "Archivieren", self)
            archive_action.triggered.connect(lambda: self.archive_invoice(inv_id))
            menu.addAction(archive_action)
            
            delete_action = Action(FIF.DELETE, "Löschen", self)
            delete_action.triggered.connect(lambda: self.delete_invoice(inv_id))
            menu.addAction(delete_action)
            
        menu.addSeparator()
        
        # Status Menu
        from qfluentwidgets import RoundMenu, Action
        status_menu = RoundMenu("Status ändern", self)
        status_menu.setIcon(FIF.TAG)
        
        for status_text in ["Entwurf", "Offen", "Bezahlt", "Überfällig", "Storniert"]:
            if status_text != inv.status:
                action = Action(status_text, self)
                action.triggered.connect(lambda checked=False, st=status_text: self.change_invoice_status(inv_id, st))
                status_menu.addAction(action)
                
        menu.addMenu(status_menu)
            
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def on_item_double_clicked(self, item):
        row = item.row()
        inv_id_item = self.table.item(row, 0)
        if not inv_id_item: return
        inv_id = inv_id_item.data(Qt.UserRole)
        self.show_editor_view(inv_id)

    def filter_table(self):
        search_text = self.searchLineEdit.text().lower()
        year_filter = self.yearFilterCombo.currentText()
        month_filter = self.monthFilterCombo.currentText()
        
        for i in range(self.table.rowCount()):
            date_item = self.table.item(i, 0)
            if not date_item:
                continue
                
            date_text = date_item.text()
            row_month = date_text[3:5] if len(date_text) >= 10 else ""
            row_year = date_text[6:10] if len(date_text) >= 10 else ""
            
            match_year = (year_filter == "Alle Jahre" or row_year == year_filter)
            match_month = (month_filter == "Alle Monate" or row_month == month_filter)
            match_search = False
            
            if not search_text:
                match_search = True
            else:
                # search in columns 1, 2, 3
                for col in range(1, 4):
                    item = self.table.item(i, col)
                    if item and search_text in item.text().lower():
                        match_search = True
                        break
                        
            self.table.setRowHidden(i, not (match_year and match_month and match_search))

    def load_data(self):

        self.table.setRowCount(0)
        invoices = self.db_controller.get_invoices()
        
        available_years = set()
        available_months = set()
        for inv in invoices:
            if inv.invoice_date:
                available_years.add(inv.invoice_date.strftime("%Y"))
                available_months.add(inv.invoice_date.strftime("%m"))
                
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
        
        from datetime import datetime, timedelta
        now = datetime.now()
        
        try:
            payment_terms = int(self.db_controller.get_setting("payment_terms_days") or 14)
        except ValueError:
            payment_terms = 14
            
        for i, inv in enumerate(invoices):
            self._update_or_insert_row(i, inv, now, payment_terms, is_new=True)
            
        self.filter_table()


    def _update_or_insert_row(self, i, inv, now, payment_terms, is_new=False):
        from datetime import timedelta
        if is_new:
            self.table.insertRow(i)
        # Date calculation for row colors
        inv_date = inv.invoice_date.replace(tzinfo=None) if inv.invoice_date else now
        delta = now - inv_date
        
        row_color = None
        if inv.status in ["Entwurf", "Offen", "Überfällig"]:
            if delta.days > 14:
                row_color = "#FFD6D6" # Red
            elif delta.days > 7:
                row_color = "#FFF5C2" # Yellow
        
        def create_item(text):
            item = QTableWidgetItem(text)
            item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            if row_color:
                from PySide6.QtGui import QBrush, QColor
                item.setBackground(QBrush(QColor(row_color)))
            return item

        first_item = create_item(inv.invoice_date.strftime("%d.%m.%Y"))
        first_item.setData(Qt.UserRole, inv.id)
        self.table.setItem(i, 0, first_item)
        self.table.setItem(i, 1, create_item(inv.invoice_number))
        customer_name = inv.customer.company_name if inv.customer.company_name else f"{inv.customer.first_name} {inv.customer.last_name}"
        self.table.setItem(i, 2, create_item(customer_name))
        self.table.setItem(i, 3, create_item(f"{inv.gross_amount:.2f} €"))
        
        due_date = inv.invoice_date + timedelta(days=payment_terms)
        self.table.setItem(i, 4, create_item(due_date.strftime("%d.%m.%Y")))
        
        status_combo = ComboBox()
        status_combo.addItems(["Entwurf", "Offen", "Bezahlt", "Überfällig"])
        status_combo.setCurrentText(inv.status)
        
        # Disconnect old signals if needed or just connect
        status_combo.currentTextChanged.connect(lambda text, inv_id=inv.id: self.change_invoice_status(inv_id, text))
        
        # Avoid focus issues and scrolling bugs by setting focus policy
        status_combo.setFocusPolicy(Qt.ClickFocus)
        status_combo.setFixedSize(130, 32)
        from PySide6.QtWidgets import QWidget, QHBoxLayout
        container = QWidget()
        container.setStyleSheet("background-color: transparent;")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 20, 0)
        layout.setAlignment(Qt.AlignCenter)
        layout.addWidget(status_combo)
        self.table.setCellWidget(i, 5, container)
        
        # Color row if paid or overdue
        if inv.status == "Bezahlt":
            from PySide6.QtGui import QColor, QBrush
            for col in range(5):
                item = self.table.item(i, col)
                if item:
                    item.setBackground(QBrush(QColor("#D3EBCD")))
                    
        elif inv.status == "Überfällig":
            from PySide6.QtGui import QColor, QBrush
            for col in range(5):
                item = self.table.item(i, col)
                if item:
                    item.setBackground(QBrush(QColor("#FFD6D6")))

    def show_datev_export_dialog(self):
        from src.models.database import Invoice
        from src.utils.datev_generator import DatevGenerator
        import os
        from datetime import datetime
        
        # Determine available months from invoices
        available_months = set()
        with self.db_controller.get_session() as session:
            invoices = session.query(Invoice).filter(
                Invoice.archived_at != None,
                Invoice.status == "Bezahlt"
            ).all()
            for inv in invoices:
                # Format: YYYY-MM
                available_months.add(f"{inv.invoice_date.year}-{inv.invoice_date.month:02d}")
                
        if not available_months:
            from qfluentwidgets import InfoBar
            InfoBar.warning("Keine Daten", "Es gibt keine archivierten und bezahlten Rechnungen zum Exportieren.", parent=self)
            return
            
        months_list = sorted(list(available_months), reverse=True)
        
        from qfluentwidgets import MessageBoxBase, SubtitleLabel, ComboBox
        class DatevDialog(MessageBoxBase):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.titleLabel = SubtitleLabel('DATEV Monats-Export', self)
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
                from sqlalchemy import extract
                # We do simple Python filter since SQLite extract might be tricky
                all_invs = session.query(Invoice).filter(
                    Invoice.archived_at != None,
                    Invoice.status == "Bezahlt"
                ).all()
                
                export_invs = [inv for inv in all_invs if inv.invoice_date.year == year and inv.invoice_date.month == month]
                
                if not export_invs:
                    return
                    
                filename = f"DATEV_Export_Rechnungen_{year}_{month:02d}.zip"
                filepath = os.path.join(os.path.expanduser("~"), "Desktop", filename)
                
                generator = DatevGenerator(self.db_controller)
                if generator.generate_export(export_invs, filepath, month, year):
                    # Record history for each
                    from src.models.database import DocumentHistory, timezone
                    for inv in export_invs:
                        h = DocumentHistory(document_type="Invoice", document_id=inv.id, user="System", action="DATEV Export")
                        session.add(h)
                    session.commit()
                    self.db_controller.db.save()
                    
                    from qfluentwidgets import InfoBar
                    InfoBar.success(
                        title="DATEV Export erfolgreich",
                        content=f"Das DATEV ZIP-Archiv für {month:02d}/{year} ({len(export_invs)} Rechnungen) wurde auf dem Desktop gespeichert:\n{filename}",
                        parent=self,
                        duration=5000
                    )
                else:
                    from qfluentwidgets import InfoBar
                    InfoBar.error(
                        title="Fehler beim DATEV Export",
                        content="Die Export-Datei konnte nicht generiert werden.",
                        parent=self,
                        duration=4000
                    )

    def generate_pdf_for_invoice(self, invoice_id, print_only=False):
        from src.utils.pdf_generator import PDFGenerator
        from src.utils.zugferd_generator import generate_zugferd_xml
        from facturx import generate_from_file
        import os
        import tempfile
        
        # Proper query
        from src.models.database import Invoice
        with self.db_controller.get_session() as session:
            invoice = session.query(Invoice).filter(Invoice.id == invoice_id).first()
            if invoice:
                try:
                    # 1. Generate base PDF
                    pdf_gen = PDFGenerator(self.db_controller)
                    temp_pdf = os.path.join(tempfile.gettempdir(), f"base_inv_{invoice.invoice_number}.pdf")
                    pdf_gen.generate_invoice_pdf(invoice, temp_pdf)
                    
                    # 2. Generate ZUGFeRD XML
                    temp_xml = os.path.join(tempfile.gettempdir(), "factur-x.xml")
                    zugferd_success = generate_zugferd_xml(invoice, self.db_controller, temp_xml)
                    
                    if print_only:
                        final_pdf_path = temp_pdf
                    else:
                        final_pdf_path = os.path.join(os.path.expanduser("~"), "Desktop", f"Rechnung_{invoice.invoice_number}.pdf")
                    
                    if zugferd_success is False and not print_only:
                        # Fallback: Just use regular PDF
                        import shutil
                        shutil.copy(temp_pdf, final_pdf_path)
                        InfoBar.success(
                            title="Rechnung Erstellt",
                            content=f"Die Rechnung wurde als Standard-PDF gespeichert (Keine Positionen für ZUGFeRD):\n{final_pdf_path}",
                            orient=Qt.Horizontal,
                            isClosable=True,
                            position=InfoBarPosition.TOP,
                            duration=5000,
                            parent=self.window()
                        )
                    elif zugferd_success is not False and not print_only:
                        # 3. Combine to PDF/A-3
                        generate_from_file(pdf_file=temp_pdf, xml=temp_xml, output_pdf_file=final_pdf_path)
                        InfoBar.success(
                            title="E-Rechnung Erstellt",
                            content=f"Die Rechnung wurde inkl. ZUGFeRD/XRechnung-Daten als PDF gespeichert:\n{final_pdf_path}",
                            orient=Qt.Horizontal,
                            isClosable=True,
                            position=InfoBarPosition.TOP,
                            duration=5000,
                            parent=self.window()
                        )
                    elif print_only:
                        os.startfile(final_pdf_path, "print")
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    
                    # Log to error.log
                    with open("error.log", "a", encoding="utf-8") as f:
                        f.write(traceback.format_exc() + "\n")
                        
                    InfoBar.error(
                        title="Fehler bei E-Rechnung",
                        content=f"Ein interner Fehler trat auf (siehe error.log oder Konsole).",
                        orient=Qt.Horizontal,
                        isClosable=True,
                        position=InfoBarPosition.TOP,
                        duration=10000,
                        parent=self.window()
                    )

    def show_list_view(self, reload=True):
        self.stackedWidget.setCurrentIndex(0)
        if reload:
            self.load_data()

    def show_editor_view(self, invoice_id=None):
        if invoice_id:
            self.editor_view.load_invoice(invoice_id)
        else:
            self.editor_view.clear_form()
        self.stackedWidget.setCurrentIndex(1)
        
    def archive_invoice(self, invoice_id):
        if self.db_controller.archive_invoice(invoice_id):
            InfoBar.success("Archiviert", "Rechnung wurde archiviert.", position=InfoBarPosition.TOP, parent=self.window())
            self.load_data()
            
    def change_invoice_status(self, invoice_id, new_status):
        if not new_status:
            return
        self.db_controller.update_invoice_status(invoice_id, new_status)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self.load_data)
            
    def delete_invoice(self, invoice_id):
        from PySide6.QtWidgets import QMessageBox
        msgBox = QMessageBox(self)
        msgBox.setIcon(QMessageBox.Warning)
        msgBox.setWindowTitle("Rechnung löschen")
        msgBox.setText("Möchten Sie diese Rechnung wirklich löschen? Diese Aktion kann nicht rückgängig gemacht werden.")
        msgBox.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msgBox.button(QMessageBox.Yes).setText("Ja")
        msgBox.button(QMessageBox.No).setText("Nein")
        msgBox.setDefaultButton(QMessageBox.No)
        
        if msgBox.exec() == QMessageBox.Yes:
            success = self.db_controller.delete_invoice(invoice_id)
            if success:
                # Find and remove row instantly for performance
                for row in range(self.table.rowCount()):
                    item = self.table.item(row, 0)
                    if item and item.data(Qt.UserRole) == invoice_id:
                        self.table.removeRow(row)
                        break
                InfoBar.success("Gelöscht", "Die Rechnung wurde gelöscht.", position=InfoBarPosition.TOP, parent=self.window())
            else:
                InfoBar.error("Fehler", "Die Rechnung konnte nicht gelöscht werden.", position=InfoBarPosition.TOP, parent=self.window())
        
    def on_invoice_saved(self, invoice_id):
        InfoBar.success(
            title="Erfolgreich",
            content="Rechnung wurde gespeichert.",
            orient=Qt.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self.window()
        )
        self.show_list_view(reload=False)
        
        found = False
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == invoice_id:
                self.update_row(invoice_id)
                found = True
                break
                
        if not found:
            self.insert_row(invoice_id)


    def insert_row(self, invoice_id):
        from datetime import datetime
        invoice = self.db_controller.get_invoice(invoice_id)
        if not invoice: return
        now = datetime.now()
        try: payment_terms = int(self.db_controller.get_setting("payment_terms_days") or 14)
        except ValueError: payment_terms = 14
        
        # Insert at the top
        self._update_or_insert_row(0, invoice, now, payment_terms, is_new=True)

    def update_row(self, invoice_id):
        from datetime import datetime
        invoice = self.db_controller.get_invoice(invoice_id)
        if not invoice: return
        now = datetime.now()
        try: payment_terms = int(self.db_controller.get_setting("payment_terms_days") or 14)
        except ValueError: payment_terms = 14
        
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == invoice_id:
                # To prevent memory leaks with QFluentWidgets, we first clear the row cell widgets
                self.table.removeCellWidget(row, 5)
                self._update_or_insert_row(row, invoice, now, payment_terms, is_new=False)
                break

    def remove_row(self, invoice_id):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == invoice_id:
                self.table.removeRow(row)
                break
