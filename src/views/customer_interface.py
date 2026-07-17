from qfluentwidgets import InfoBar, InfoBarPosition, PrimaryPushButton, PushButton, SearchLineEdit, SubtitleLabel, TableWidget
from PySide6.QtWidgets import QHBoxLayout, QHeaderView, QMessageBox, QStackedWidget, QTableWidgetItem, QVBoxLayout, QWidget
from PySide6.QtCore import Qt
from src.controllers.db_controller import DBController
from src.views.customer_editor import CustomerEditor
from src.utils.signal_bus import SignalBus


class CustomerInterface(QWidget):
    def __init__(self, db_controller: DBController, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("CustomerInterface")
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
        self.editor_view = CustomerEditor(self.db_controller)
        self.editor_view.saved.connect(self.on_customer_saved)
        self.editor_view.canceled.connect(lambda: self.show_list_view(reload=False))
        self.stackedWidget.addWidget(self.editor_view)
        
        self.show_list_view()
        SignalBus.get().customerAdded.connect(self.insert_row)
        SignalBus.get().customerUpdated.connect(self.update_row)
        SignalBus.get().customerDeleted.connect(self.remove_row)

    def init_list_view(self):
        layout = QVBoxLayout(self.list_view)
        layout.setContentsMargins(24, 24, 24, 24)
        
        # Header
        headerLayout = QHBoxLayout()
        self.titleLabel = SubtitleLabel("Kunden", self.list_view)
        
        self.searchLineEdit = SearchLineEdit(self.list_view)
        self.searchLineEdit.setPlaceholderText("Suchen...")
        self.searchLineEdit.setFixedWidth(300)
        
        self.newCustomerBtn = PrimaryPushButton("Neuer Kunde", self.list_view)
        self.newCustomerBtn.clicked.connect(self.show_editor_view)
        
        headerLayout.addWidget(self.titleLabel)
        headerLayout.addStretch(1)
        headerLayout.addWidget(self.searchLineEdit)
        headerLayout.addWidget(self.newCustomerBtn)
        
        layout.addLayout(headerLayout)
        
        # Table
        self.table = TableWidget(self.list_view)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(['Firma', 'Name', 'Adresse', 'PLZ', 'Ort'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.table.setColumnWidth(0, 180)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.table.setColumnWidth(1, 180)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Interactive)
        self.table.setColumnWidth(3, 80)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Interactive)
        self.table.setColumnWidth(4, 120)

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
        cust_id_item = self.table.item(row, 0)
        if not cust_id_item: return
        cust_id = cust_id_item.data(Qt.UserRole)
        
        cust = self.db_controller.get_customer(cust_id)
        if not cust: return

        from qfluentwidgets import RoundMenu, Action
        from qfluentwidgets import FluentIcon as FIF
        menu = RoundMenu(parent=self.table)
        
        edit_action = Action(FIF.EDIT, "Bearbeiten", self)
        edit_action.triggered.connect(lambda: self.show_editor_view(cust_id))
        menu.addAction(edit_action)
        
        delete_action = Action(FIF.DELETE, "Löschen", self)
        delete_action.triggered.connect(lambda: self.delete_customer(cust_id))
        menu.addAction(delete_action)
            
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def on_item_double_clicked(self, item):
        row = item.row()
        cust_id_item = self.table.item(row, 0)
        if not cust_id_item: return
        cust_id = cust_id_item.data(Qt.UserRole)
        self.show_editor_view(cust_id)

    def filter_table(self):
        search_text = self.searchLineEdit.text().lower()
        
        for i in range(self.table.rowCount()):
            match_search = False
            if not search_text: match_search = True
            else:
                for col in range(5):
                    item = self.table.item(i, col)
                    if item and search_text in item.text().lower():
                        match_search = True
                        break
            self.table.setRowHidden(i, not match_search)

    def load_data(self):

        self.table.setRowCount(0)
        customers = self.db_controller.get_customers()
        for i, cust in enumerate(customers):
            self._update_or_insert_row(i, cust, is_new=True)
            
        self.filter_table()


    def _update_or_insert_row(self, i, cust, is_new=False):
        from PySide6.QtWidgets import QTableWidgetItem, QWidget, QHBoxLayout
        from PySide6.QtCore import Qt
        from qfluentwidgets import PushButton
        if is_new:
            self.table.insertRow(i)
        first_item = QTableWidgetItem(cust.company_name if cust.company_name else "")
        first_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
        first_item.setData(Qt.UserRole, cust.id)
        self.table.setItem(i, 0, first_item)
        self.table.setItem(i, 1, QTableWidgetItem(f"{cust.first_name or ''} {cust.last_name or ''}".strip()))
        self.table.setItem(i, 2, QTableWidgetItem(cust.address or ""))
        self.table.setItem(i, 3, QTableWidgetItem(cust.postal_code or ""))
        self.table.setItem(i, 4, QTableWidgetItem(cust.city or ""))

    def show_list_view(self, reload=True):
        self.stackedWidget.setCurrentIndex(0)
        if reload:
            self.load_data()

    def show_editor_view(self, customer_id=None):
        # We need to make sure invoice/quote views reload customers if modified
        if customer_id and customer_id is not False: # Button clicked sends False as first arg
            self.editor_view.load_customer(customer_id)
        else:
            self.editor_view.clear_form()
        self.stackedWidget.setCurrentIndex(1)
        
    def delete_customer(self, customer_id):
        # Ask for confirmation
        msgBox = QMessageBox(self)
        msgBox.setIcon(QMessageBox.Warning)
        msgBox.setWindowTitle("Kunde löschen")
        msgBox.setText("Möchten Sie diesen Kunden wirklich löschen?")
        msgBox.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msgBox.button(QMessageBox.Yes).setText("Ja")
        msgBox.button(QMessageBox.No).setText("Nein")
        msgBox.setDefaultButton(QMessageBox.No)
        
        if msgBox.exec() == QMessageBox.Yes:
            success, reason = self.db_controller.delete_customer(customer_id)
            if success:
                # Find and remove row instantly for performance
                for row in range(self.table.rowCount()):
                    item = self.table.item(row, 0)
                    if item and item.data(Qt.UserRole) == customer_id:
                        self.table.removeRow(row)
                        break
                InfoBar.success("Gelöscht", "Der Kunde wurde erfolgreich gelöscht.", position=InfoBarPosition.TOP, parent=self.window())
            else:
                InfoBar.error(
                    title="Fehler beim Löschen",
                    content=f"Dieser Kunde kann nicht gelöscht werden, da noch {reason} mit ihm verknüpft sind.",
                    orient=Qt.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=5000,
                    parent=self.window()
                )
        
    def on_customer_saved(self, customer_id):
        InfoBar.success(
            title="Erfolgreich",
            content="Kunde wurde gespeichert.",
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
            if item and item.data(Qt.UserRole) == customer_id:
                self.update_row(customer_id)
                found = True
                break
                
        if not found:
            self.insert_row(customer_id)


    def insert_row(self, customer_id):
        customer = self.db_controller.get_customer(customer_id)
        if not customer: return
        self._update_or_insert_row(0, customer, is_new=True)

    def update_row(self, customer_id):
        customer = self.db_controller.get_customer(customer_id)
        if not customer: return
        from PySide6.QtCore import Qt
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == customer_id:
                self._update_or_insert_row(row, customer, is_new=False)
                break

    def remove_row(self, customer_id):
        from PySide6.QtCore import Qt
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == customer_id:
                self.table.removeRow(row)
                break
