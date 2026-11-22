from datetime import datetime
from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QApplication, QMessageBox
from qfluentwidgets import FluentIcon as FIF, FluentWindow, InfoBar, InfoBarPosition, MessageBox, Theme, setTheme, setThemeColor
from src.controllers.db_controller import DBController
from src.utils import paths
from src.utils.pdf_generator import DEFAULT_DOCUMENT_COLOR, document_color
from src.utils.signal_bus import SignalBus
from src.views.analysis_interface import AnalysisInterface
from src.views.cashbook_interface import CashbookInterface
from src.views.customer_interface import CustomerInterface
from src.views.incoming_invoice_interface import IncomingInvoiceInterface
from src.views.invoice_interface import InvoiceInterface
from src.views.quote_interface import QuoteInterface
from src.views.reminder_interface import ReminderInterface
from src.views.settings_interface import SettingsInterface
from src.views.update_notifier import UpdateNotifier


MONTH_NAMES = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
               "November", "Dezember"]


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

        self.updates = UpdateNotifier(self)
        self.settings_interface.updateCheckRequested.connect(self.updates.check_now)
        SignalBus.get().saveFailed.connect(self._on_save_failed)
        # Overdue invoices are re-evaluated hourly so a long running session stays correct
        self._overdue_timer = QTimer(self, interval=60 * 60 * 1000)
        self._overdue_timer.timeout.connect(db_controller.refresh_overdue)
        self._overdue_timer.start()

    def apply_color(self):
        name = self.db_controller.get_setting("document_color", DEFAULT_DOCUMENT_COLOR)
        if name != getattr(self, "_applied_color", None):
            self._applied_color = name
            setThemeColor(document_color(name))

    def init_window(self):
        self.resize(1280, 820)
        self.setMinimumWidth(900)
        self.setWindowTitle('Schalk')
        setTheme(Theme.LIGHT)
        # The colour chosen in the settings is the accent of the program as well as of the documents
        self.apply_color()
        SignalBus.get().settingsChanged.connect(self.apply_color)
        self.navigationInterface.setExpandWidth(240)
        # The menu stays expanded down to the minimum window width (the default collapses it below ~1000 px)
        self.navigationInterface.setMinimumExpandWidth(self.minimumWidth())
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - self.width() // 2, screen.center().y() - self.height() // 2)

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_navigation_expanded", False):
            # Expanded on start; afterwards the menu button collapses and expands it as usual
            self._navigation_expanded = True
            QTimer.singleShot(0, self, lambda: self.navigationInterface.expand(useAni=False))

    def open_invoice(self, invoice_id: int):
        self.invoice_interface.show_editor(invoice_id)
        self.switchTo(self.invoice_interface)

    def backup_due(self) -> bool:
        """True if no backup was made in the current month yet."""
        last = self.db_controller.get_setting("last_backup")
        try:
            last = datetime.fromisoformat(last) if last else None
        except ValueError:
            last = None
        now = datetime.now()
        return last is None or (last.year, last.month) != (now.year, now.month)

    def remind_of_backup(self):
        """At the start of every month (and on each start until it is done): ask for a backup."""
        if not self.backup_due():
            return
        month = f"{MONTH_NAMES[datetime.now().month - 1]} {datetime.now().year}"
        box = MessageBox("Monatliches Backup",
                         f"Für {month} wurde noch kein Backup erstellt. Ein Backup sichert alle Daten und Dokumente in einer "
                         "verschlüsselten Datei, z. B. auf einem USB-Stick, und schützt sie bei einem Defekt oder PC-Wechsel.",
                         self)
        box.yesButton.setText("Backup jetzt erstellen")
        box.cancelButton.setText("Später")
        if box.exec():
            self.switchTo(self.settings_interface)
            self.settings_interface.export_backup()

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
        # Only after everything is saved: a downloaded update replaces the program files once Schalk has exited
        self.updates.install_on_exit()
        super().closeEvent(event)
