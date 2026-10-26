from PySide6.QtCore import Qt, QSize, QTimer, QEventLoop
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from qfluentwidgets import (FluentWindow, setTheme, Theme)
from qfluentwidgets import FluentIcon as FIF
import os

from src.controllers.db_controller import DBController
from src.views.invoice_interface import InvoiceInterface
from src.views.cashbook_interface import CashbookInterface
from src.views.quote_interface import QuoteInterface
from src.views.reminder_interface import ReminderInterface
from src.views.settings_interface import SettingsInterface
from src.views.customer_interface import CustomerInterface
from src.views.incoming_invoice_interface import IncomingInvoiceInterface
from src.views.analysis_interface import AnalysisInterface

class MainWindow(FluentWindow):
    def __init__(self, db_controller: DBController):
        super().__init__()
        self.db_controller = db_controller
        
        self.initWindow()

        # Sub-interfaces
        self.invoice_interface = InvoiceInterface(self.db_controller, self)
        print("invoice_interface done")
        self.cashbook_interface = CashbookInterface(self.db_controller, self)
        print("cashbook_interface done")
        self.quote_interface = QuoteInterface(self.db_controller, self)
        print("quote_interface done")
        self.reminder_interface = ReminderInterface(self.db_controller, self)
        print("reminder_interface done")
        self.customer_interface = CustomerInterface(self.db_controller, self)
        print("customer_interface done")
        self.settings_interface = SettingsInterface(self.db_controller, self)
        print("settings_interface done")
        self.supplier_invoice_interface = IncomingInvoiceInterface(self.db_controller, "Lieferant", self)
        self.other_invoice_interface = IncomingInvoiceInterface(self.db_controller, "Sonstige", self)
        self.analysis_interface = AnalysisInterface(self.db_controller, self)
        
        self.initNavigation()

    def initNavigation(self):
        self.addSubInterface(self.invoice_interface, FIF.DOCUMENT, 'Kundenrechnungen')
        self.addSubInterface(self.supplier_invoice_interface, FIF.SHOPPING_CART, 'Lieferantenrechnungen')
        self.addSubInterface(self.other_invoice_interface, FIF.FOLDER, 'Sonstige Rechnungen')
        self.addSubInterface(self.cashbook_interface, FIF.CALENDAR, 'Kassenbuch')
        self.addSubInterface(self.quote_interface, FIF.SEND, 'Angebote')
        self.addSubInterface(self.reminder_interface, FIF.MESSAGE, 'Mahnungen')
        self.addSubInterface(self.customer_interface, FIF.PEOPLE, 'Kunden')
        self.addSubInterface(self.analysis_interface, FIF.PIE_SINGLE, 'Auswertung')
        self.addSubInterface(self.settings_interface, FIF.SETTING, 'Einstellungen')
        
        self.navigationInterface.setCurrentItem(self.invoice_interface.objectName())

    def check_integrity_on_startup(self):
        """GoBD: warn immediately if booked data or archived documents were altered outside the app."""
        from qfluentwidgets import InfoBar, InfoBarPosition
        problems = self.db_controller.verify_integrity()
        if problems:
            InfoBar.error(
                title="GoBD-Integritätsprüfung",
                content=f"{len(problems)} Abweichung(en) gefunden. Details unter Einstellungen > Sicherheit & GoBD.",
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=-1,
                parent=self
            )

    def initWindow(self):
        self.resize(1200, 800)
        self.setMinimumWidth(800)
        self.setWindowTitle('Schalk')
        
        # Set light theme by default
        setTheme(Theme.LIGHT)
        
        # Halve the expanded width of the sidebar
        if hasattr(self.navigationInterface, 'setExpandWidth'):
            self.navigationInterface.setExpandWidth(240)
        elif hasattr(self.navigationInterface.panel, 'setExpandWidth'):
            self.navigationInterface.panel.setExpandWidth(240)

        # Expand sidebar by default
        if hasattr(self.navigationInterface, 'expand'):
            self.navigationInterface.expand(useAni=False)
        elif hasattr(self.navigationInterface.panel, 'expand'):
            self.navigationInterface.panel.expand(useAni=False)
            
        # Center the window
        desktop = QApplication.primaryScreen().availableGeometry()
        w, h = desktop.width(), desktop.height()
        self.move(w//2 - self.width()//2, h//2 - self.height()//2)
