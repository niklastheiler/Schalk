from qfluentwidgets import ComboBox, InfoBar, InfoBarPosition, PrimaryPushButton, PushButton, SearchLineEdit, SubtitleLabel, TableWidget
from PySide6.QtWidgets import QHBoxLayout, QHeaderView, QStackedWidget, QTableWidgetItem, QVBoxLayout, QWidget
from PySide6.QtCore import Qt
from src.controllers.db_controller import DBController, GoBDError
from src.utils import paths
import os
from src.views.quote_editor import QuoteEditor
from src.utils.signal_bus import SignalBus


class QuoteInterface(QWidget):
    def __init__(self, db_controller: DBController, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("QuoteInterface")
        self.db_controller = db_controller
        
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        
        self.stackedWidget = QStackedWidget(self)
        self.vBoxLayout.addWidget(self.stackedWidget)
        
        # View 1: List
        self.list_view = QWidget()
        self.init_list_view()
        self.stackedWidget.addWidget(self.list_view)
        
        # View 2: Editor
        self.editor_view = QuoteEditor(self.db_controller)
        self.editor_view.saved.connect(self.on_quote_saved)
        self.editor_view.canceled.connect(lambda: self.show_list_view(reload=False))
        self.stackedWidget.addWidget(self.editor_view)
        
        self.show_list_view()
        SignalBus.get().quoteAdded.connect(self.insert_row)
        SignalBus.get().quoteUpdated.connect(self.update_row)
        SignalBus.get().quoteDeleted.connect(self.remove_row)

    def init_list_view(self):
        layout = QVBoxLayout(self.list_view)
        layout.setContentsMargins(24, 24, 24, 24)
        
        # Header
        headerLayout = QHBoxLayout()
        self.titleLabel = SubtitleLabel("Angebote", self.list_view)
        
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
        
        self.newQuoteBtn = PrimaryPushButton("Neues Angebot", self.list_view)
        self.newQuoteBtn.clicked.connect(self.show_editor_view)
        
        headerLayout.addWidget(self.titleLabel)
        headerLayout.addStretch(1)
        headerLayout.addWidget(self.yearFilterCombo)
        headerLayout.addWidget(self.monthFilterCombo)
        headerLayout.addWidget(self.searchLineEdit)
        headerLayout.addWidget(self.newQuoteBtn)
        
        layout.addLayout(headerLayout)
        
        # Table
        self.table = TableWidget(self.list_view)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(['Datum', 'Angebotsnummer', 'Kunde', 'Betrag', 'Status'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.table.setColumnWidth(0, 100)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.table.setColumnWidth(1, 150)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Interactive)
        self.table.setColumnWidth(3, 120)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Interactive)
        self.table.setColumnWidth(4, 150)

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


    def showEvent(self, event):
        super().showEvent(event)

    def show_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item: return
        row = item.row()
        q_id_item = self.table.item(row, 0)
        if not q_id_item: return
        q_id = q_id_item.data(Qt.UserRole)
        
        q = self.db_controller.get_quote(q_id)
        if not q: return

        from qfluentwidgets import RoundMenu, Action
        from qfluentwidgets import FluentIcon as FIF
        menu = RoundMenu(parent=self.table)
        
        edit_action = Action(FIF.EDIT, "Anzeigen" if q.archived_at else "Bearbeiten", self)
        edit_action.triggered.connect(lambda: self.show_editor_view(q_id))
        menu.addAction(edit_action)
        
        if q.archived_at is not None:
            pdf_action = Action(FIF.DOCUMENT, "PDF erstellen", self)
            pdf_action.triggered.connect(lambda: self.generate_pdf_for_quote(q_id))
            menu.addAction(pdf_action)
            
            print_action = Action(FIF.PRINT, "Drucken", self)
            print_action.triggered.connect(lambda: self.generate_pdf_for_quote(q_id, print_only=True))
            menu.addAction(print_action)
        else:
            archive_action = Action(FIF.FOLDER, "Archivieren", self)
            archive_action.triggered.connect(lambda: self.archive_quote(q_id))
            menu.addAction(archive_action)
            
            delete_action = Action(FIF.DELETE, "Löschen", self)
            delete_action.triggered.connect(lambda: self.delete_quote(q_id))
            menu.addAction(delete_action)
            
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def on_item_double_clicked(self, item):
        row = item.row()
        q_id_item = self.table.item(row, 0)
        if not q_id_item: return
        q_id = q_id_item.data(Qt.UserRole)
        self.show_editor_view(q_id)

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

        self.table.setRowCount(0)
        quotes = self.db_controller.get_quotes()
        
        available_years = set()
        available_months = set()
        for q in quotes:
            if q.quote_date:
                available_years.add(q.quote_date.strftime("%Y"))
                available_months.add(q.quote_date.strftime("%m"))
                
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
        
        for i, q in enumerate(quotes):
            self._update_or_insert_row(i, q, is_new=True)
            
        self.filter_table()


    def _update_or_insert_row(self, i, q, is_new=False):
        if is_new:
            self.table.insertRow(i)
        
        def create_item(text):
            item = QTableWidgetItem(text)
            item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            return item
            
        first_item = create_item(q.quote_date.strftime("%d.%m.%Y"))
        first_item.setData(Qt.UserRole, q.id)
        self.table.setItem(i, 0, first_item)
        self.table.setItem(i, 1, create_item(q.quote_number))
        customer_name = q.customer.company_name if q.customer.company_name else f"{q.customer.first_name} {q.customer.last_name}"
        self.table.setItem(i, 2, create_item(customer_name))
        self.table.setItem(i, 3, create_item(f"{q.gross_amount:.2f} €"))
        
        from PySide6.QtGui import QColor, QBrush
        if q.status == "Angenommen":
            for col in range(4):
                item = self.table.item(i, col)
                if item: item.setBackground(QBrush(QColor("#D3EBCD")))
        elif q.status == "Abgelehnt":
            for col in range(4):
                item = self.table.item(i, col)
                if item: item.setBackground(QBrush(QColor("#FFD6D6")))
        elif q.status == "Überfällig":
            for col in range(4):
                item = self.table.item(i, col)
                if item: item.setBackground(QBrush(QColor("#FFCFCF")))

        status_combo = ComboBox()
        status_combo.addItems(["Entwurf", "Versendet", "Angenommen", "Abgelehnt", "Abgelaufen"])
        status_combo.setCurrentText(q.status)
        
        # Disconnect old signals if needed or just connect
        status_combo.currentTextChanged.connect(lambda text, q_id=q.id: self.change_quote_status(q_id, text))
        
        status_combo.setFocusPolicy(Qt.ClickFocus)
        status_combo.setFixedSize(130, 32)
        from PySide6.QtWidgets import QWidget, QHBoxLayout
        container = QWidget()
        container.setStyleSheet("background-color: transparent;")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 20, 0)
        layout.setAlignment(Qt.AlignCenter)
        layout.addWidget(status_combo)
        self.table.setCellWidget(i, 4, container)

    def generate_pdf_for_quote(self, quote_id, print_only=False):
        from src.utils.pdf_generator import PDFGenerator
        import os
        from src.models.database import Quote
        
        with self.db_controller.get_session() as session:
            quote = session.query(Quote).filter(Quote.id == quote_id).first()
            if quote:
                try:
                    import tempfile
                    
                    if print_only:
                        filepath = os.path.join(tempfile.gettempdir(), f"print_quote_{quote.quote_number}.pdf")
                    else:
                        filepath = paths.desktop_path(f"Angebot_{quote.quote_number}.pdf")
                    
                    pdf_gen = PDFGenerator(self.db_controller)
                    pdf_gen.generate_quote_pdf(quote, filepath)
                    
                    if print_only:
                        os.startfile(filepath, "print")
                    else:
                        InfoBar.success(
                            title="PDF Erstellt",
                            content=f"Das Angebot wurde als PDF auf dem Desktop gespeichert:\n{filepath}",
                            orient=Qt.Horizontal,
                            isClosable=True,
                            position=InfoBarPosition.TOP,
                            duration=5000,
                            parent=self.window()
                        )
                except Exception as e:
                    InfoBar.error(
                        title="Fehler",
                        content=f"Die PDF konnte nicht erstellt werden: {str(e)}",
                        orient=Qt.Horizontal,
                        isClosable=True,
                        position=InfoBarPosition.TOP,
                        duration=8000,
                        parent=self.window()
                    )

    def show_list_view(self, reload=True):
        self.stackedWidget.setCurrentIndex(0)
        if reload:
            self.load_data()

    def show_editor_view(self, quote_id=None):
        if quote_id:
            self.editor_view.load_quote(quote_id)
        else:
            self.editor_view.clear_form()
        self.stackedWidget.setCurrentIndex(1)
        
    def archive_quote(self, quote_id):
        if self.db_controller.archive_quote(quote_id):
            InfoBar.success("Archiviert", "Angebot wurde archiviert.", position=InfoBarPosition.TOP, parent=self.window())
            self.load_data()
            
    def change_quote_status(self, quote_id, new_status):
        self.db_controller.update_quote_status(quote_id, new_status)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self.load_data)
            
    def delete_quote(self, quote_id):
        from PySide6.QtWidgets import QMessageBox
        msgBox = QMessageBox(self)
        msgBox.setIcon(QMessageBox.Warning)
        msgBox.setWindowTitle("Angebot löschen")
        msgBox.setText("Möchten Sie dieses Angebot wirklich löschen? Diese Aktion kann nicht rückgängig gemacht werden.")
        msgBox.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msgBox.button(QMessageBox.Yes).setText("Ja")
        msgBox.button(QMessageBox.No).setText("Nein")
        msgBox.setDefaultButton(QMessageBox.No)
        
        if msgBox.exec() == QMessageBox.Yes:
            try:
                success = self.db_controller.delete_quote(quote_id)
            except GoBDError as e:
                InfoBar.error("Nicht erlaubt", str(e), position=InfoBarPosition.TOP, parent=self.window())
                return
            if success:
                # Find and remove row instantly for performance
                for row in range(self.table.rowCount()):
                    item = self.table.item(row, 0)
                    if item and item.data(Qt.UserRole) == quote_id:
                        self.table.removeRow(row)
                        break
                InfoBar.success("Gelöscht", "Das Angebot wurde gelöscht.", position=InfoBarPosition.TOP, parent=self.window())
            else:
                InfoBar.error("Fehler", "Das Angebot konnte nicht gelöscht werden.", position=InfoBarPosition.TOP, parent=self.window())
        
    def on_quote_saved(self, quote_id):
        InfoBar.success(
            title="Erfolgreich",
            content="Angebot wurde gespeichert.",
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
            if item and item.data(Qt.UserRole) == quote_id:
                self.update_row(quote_id)
                found = True
                break
                
        if not found:
            self.insert_row(quote_id)


    def insert_row(self, quote_id):
        quote = self.db_controller.get_quote(quote_id)
        if not quote: return
        self._update_or_insert_row(0, quote, is_new=True)

    def update_row(self, quote_id):
        quote = self.db_controller.get_quote(quote_id)
        if not quote: return
        from PySide6.QtCore import Qt
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == quote_id:
                self._update_or_insert_row(row, quote, is_new=False)
                break

    def remove_row(self, quote_id):
        from PySide6.QtCore import Qt
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == quote_id:
                self.table.removeRow(row)
                break
