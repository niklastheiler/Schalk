from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QApplication, QMessageBox
from qfluentwidgets import FluentIcon as FIF, FluentWindow, InfoBar, InfoBarPosition, Theme, setTheme
from src.controllers.db_controller import DBController
from src.utils import paths
from src.utils.signal_bus import SignalBus
from src.views.analysis_interface import AnalysisInterface
from src.views.cashbook_interface import CashbookInterface
from src.views.customer_interface import CustomerInterface
from src.views.incoming_invoice_interface import IncomingInvoiceInterface
from src.views.invoice_interface import InvoiceInterface
from src.views.quote_interface import QuoteInterface
from src.views.reminder_interface import ReminderInterface
from src.views.settings_interface import SettingsInterface


class MainWindow(FluentWindow):
    integrityChecked = Signal(list)

    def __init__(self, db_controller: DBController):
        super().__init__()
        self.db_controller = db_controller
        self.init_window()

        self.invoice_interface = InvoiceInterface(db_controller, self)
        self.supplier_invoice_interface = IncomingInvoiceInterface(db_controller, "Lieferant", self)
        self.other_invoice_interface = IncomingInvoiceInterface(db_controller, "Sonstige", self)
        self.cashbook_interface = CashbookInterface(db_controller, self)
        self.quote_interface = QuoteInterface(db_controller, self)
        self.reminder_interface = ReminderInterface(db_controller, self)
        self.customer_interface = CustomerInterface(db_controller, self)
        self.analysis_interface = AnalysisInterface(db_controller, self)
        self.settings_interface = SettingsInterface(db_controller, self)

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

        SignalBus.get().saveFailed.connect(self._on_save_failed)
        # Overdue invoices are re-evaluated hourly so a long running session stays correct
        self._overdue_timer = QTimer(self, interval=60 * 60 * 1000)
        self._overdue_timer.timeout.connect(db_controller.refresh_overdue)
        self._overdue_timer.start()

    def init_window(self):
        self.resize(1280, 820)
        self.setMinimumWidth(900)
        self.setWindowTitle('Schalk')
        setTheme(Theme.LIGHT)
        self.navigationInterface.setExpandWidth(240)
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - self.width() // 2, screen.center().y() - self.height() // 2)

    def open_invoice(self, invoice_id: int):
        self.invoice_interface.show_editor(invoice_id)
        self.switchTo(self.invoice_interface)

    def check_integrity_on_startup(self):
        """GoBD: warn if booked data was altered outside the app. Runs in the background."""
        self.integrityChecked.connect(self._on_integrity_checked)
        self.db_controller.verify_integrity_async(self.integrityChecked.emit, check_files=False)

    def _on_integrity_checked(self, problems: list):
        if problems:
            InfoBar.error(
                title="GoBD-Integritätsprüfung",
                content=f"{len(problems)} Abweichung(en) gefunden. Details unter Einstellungen > Sicherheit & GoBD.",
                isClosable=True, position=InfoBarPosition.TOP, duration=-1, parent=self)

    def _on_save_failed(self, message: str):
        InfoBar.error(title="Speichern fehlgeschlagen",
                      content=f"Die Daten konnten nicht auf die Festplatte geschrieben werden: {message}\nDetails: {paths.LOG_PATH}",
                      isClosable=True, position=InfoBarPosition.TOP, duration=-1, parent=self)

    def closeEvent(self, event):
        try:
            # Wait for the background writer so no change is lost
            self.db_controller.close()
        except Exception as e:
            QMessageBox.critical(self, "Schalk", f"Die letzten Änderungen konnten nicht gespeichert werden:\n{e}\n\n"
                                                 "Bitte freien Speicherplatz und Zugriffsrechte prüfen und erneut schließen.")
            event.ignore()
            return
        super().closeEvent(event)
