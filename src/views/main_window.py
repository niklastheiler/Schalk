from datetime import datetime
from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMessageBox
from qfluentwidgets import FluentIcon as FIF, FluentWindow, InfoBar, InfoBarPosition, MessageBox, Theme, setTheme, setThemeColor
from src.controllers.db_controller import DBController
from src.utils import paths
from src.utils.pdf_generator import DEFAULT_DOCUMENT_COLOR, document_color
from src.utils.signal_bus import SignalBus
from src.views.analysis_interface import AnalysisInterface
from src.views.common import ask_discard_changes
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


# Narrowest window (in logical pixels) in which the expanded menu stays beside the pages
NAVIGATION_INLINE_WIDTH = 1100


class _MouseNavigation(QObject):
    """Back and forward buttons of the mouse anywhere in the main window (not in dialogs)."""

    def __init__(self, window):
        super().__init__() # no parent: lives as long as the window keeps a reference
        self.window = window

    def eventFilter(self, watched, event):
        if event.type() == QEvent.MouseButtonPress and event.button() in (Qt.BackButton, Qt.ForwardButton) \
                and QApplication.activeModalWidget() is None and QApplication.activeWindow() is self.window:
            if event.button() == Qt.BackButton:
                self.window.go_back()
            else:
                self.window.go_forward()
            return True
        return False


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
        self._guard_tab_changes()
        # Tabs visited, for the back and forward buttons of the mouse
        self._history = [self.stackedWidget.currentWidget()]
        self._history_pos = 0
        self._navigating = False
        self.stackedWidget.currentChanged.connect(self._remember_tab)
        # A separate filter object: the application calls it for every event, also while a window is being
        # destroyed; it touches the window only for the two mouse buttons
        self._mouse_navigation = mouse_navigation = _MouseNavigation(self)
        app = QApplication.instance()
        app.installEventFilter(mouse_navigation)
        self.destroyed.connect(lambda *_: app.removeEventFilter(mouse_navigation))

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
        # The interface is enlarged (see main.UI_SCALE) and Windows may scale as well: the window never asks for
        # more than the screen has
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1280, screen.width()), min(820, screen.height()))
        self.setMinimumWidth(min(900, screen.width()))
        self.setWindowTitle('Schalk')
        setTheme(Theme.LIGHT)
        # The colour chosen in the settings is the accent of the program as well as of the documents
        self.apply_color()
        SignalBus.get().settingsChanged.connect(self.apply_color)
        self.navigationInterface.setExpandWidth(240)
        # Below this width the menu stays collapsed to icons and opens over the content, so the pages keep room
        self.navigationInterface.setMinimumExpandWidth(NAVIGATION_INLINE_WIDTH)
        self.move(screen.center().x() - self.width() // 2, screen.center().y() - self.height() // 2)

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_navigation_expanded", False):
            # Expanded on start; afterwards the menu button collapses and expands it as usual
            self._navigation_expanded = True
            if self.width() >= NAVIGATION_INLINE_WIDTH:
                QTimer.singleShot(0, self, lambda: self.navigationInterface.expand(useAni=False))

    def _guard_tab_changes(self):
        """
        Before leaving a tab with unsaved input the user decides: discard (the input is reset and the new tab
        opens) or stay (nothing changes, the menu keeps the current tab selected). Installed on the stacked
        widget itself, so the menu, the back arrow and programmatic switches are all covered.
        """
        stacked = self.stackedWidget
        switch = stacked.setCurrentWidget

        def guarded(widget, popOut=True):
            current = stacked.currentWidget()
            if widget is not current and current is not None and not self.leave_allowed(current):
                self.navigationInterface.setCurrentItem(current.objectName())
                return
            switch(widget, popOut)
        stacked.setCurrentWidget = guarded

    # --- Back and forward buttons of the mouse ---
    def _remember_tab(self, _index=None):
        current = self.stackedWidget.currentWidget()
        if self._navigating or current is self._history[self._history_pos]:
            return
        del self._history[self._history_pos + 1:]
        self._history.append(current)
        self._history_pos = len(self._history) - 1

    def go_back(self):
        """Back: closes an open editor (asking about unsaved input), otherwise the previously visited tab."""
        view = self.stackedWidget.currentWidget()
        editor = getattr(view, "editor", None)
        if editor is not None and view.stackedWidget.currentWidget() is editor:
            view.leave_editor()
            return
        self._go_to(self._history_pos - 1)

    def go_forward(self):
        self._go_to(self._history_pos + 1)

    def _go_to(self, position: int):
        if not 0 <= position < len(self._history):
            return
        self._navigating = True
        try:
            if self.switchTo(self._history[position]):
                self._history_pos = position
        finally:
            self._navigating = False

    def switchTo(self, interface) -> bool:
        """Switches the tab; False if the user stayed because of unsaved input."""
        super().switchTo(interface)
        return self.stackedWidget.currentWidget() is interface

    def leave_allowed(self, view) -> bool:
        if not getattr(view, "has_unsaved_changes", None) or not view.has_unsaved_changes():
            return True
        if not ask_discard_changes(self):
            return False
        view.discard_changes()
        return True

    def open_invoice(self, invoice_id: int):
        # First the tab (which may ask about unsaved input), then the invoice: an open draft in the invoice
        # editor is not replaced without asking either
        if not self.switchTo(self.invoice_interface) or not self.leave_allowed(self.invoice_interface):
            return
        self.invoice_interface.show_editor(invoice_id)

    def backup_due(self) -> bool:
        """True if no backup was made in the current month yet."""
        last = self.db_controller.get_setting("last_backup")
        try:
            last = datetime.fromisoformat(last) if last else None
        except ValueError:
            last = None
        now = datetime.now()
        return last is None or (last.year, last.month) != (now.year, now.month)

    def remind_of_backup_when_ready(self, attempts: int = 20):
        """
        The reminder appears only once the window is really on screen: right after an update the first start is
        slow (Windows checks the new program files), and a dialog opened before the window was maximized and
        painted stayed invisible behind its grey mask.
        """
        handle = self.windowHandle()
        ready = self.isVisible() and handle is not None and handle.isExposed() and not self.isMinimized()
        if not ready and attempts > 0:
            QTimer.singleShot(500, self, lambda: self.remind_of_backup_when_ready(attempts - 1))
            return
        if ready:
            # One more round of the event loop, so the maximized window is laid out and painted first
            QTimer.singleShot(300, self, self.remind_of_backup)

    def remind_of_backup(self):
        """At the start of every month (and on each start until it is done): ask for a backup."""
        if not self.backup_due():
            return
        month = f"{MONTH_NAMES[datetime.now().month - 1]} {datetime.now().year}"
        box = MessageBox("Monatliches Backup",
                         f"Für {month} wurde noch kein Backup erstellt. Ein Backup sichert alle Daten und Dokumente in einer "
                         "Datei, z. B. auf einem USB-Stick, und schützt sie bei einem Defekt oder PC-Wechsel.",
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
        # Unsaved input in any tab: discard or stay (the window stays open)
        for view in [self.stackedWidget.currentWidget()] + [self.stackedWidget.widget(i) for i in range(self.stackedWidget.count())]:
            if not self.leave_allowed(view):
                self.switchTo(view)
                event.ignore()
                return
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
