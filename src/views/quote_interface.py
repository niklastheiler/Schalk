import logging
import shutil
from PySide6.QtWidgets import QFileDialog, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon as FIF, RoundMenu
from src.controllers.db_controller import DBController, GoBDError, QUOTE_STATUSES
from src.utils import paths
from src.utils.pdf_generator import PDFGenerator
from src.utils.signal_bus import SignalBus
from src.views.common import (COLOR_GREEN, COLOR_GREY, PDF_SVG, ROCKET_SVG, Column, ListPage, confirm, fmt_date, fmt_money,
                              notify_error, notify_success, open_document, ask_discard_changes)
from src.views.invoice_interface import _naive, add_action
from src.views.quote_editor import QuoteEditor

logger = logging.getLogger(__name__)


class QuoteListPage(ListPage):
    def __init__(self, interface: "QuoteInterface"):
        self.interface = interface
        self.c = c = interface.db_controller
        columns = [
            Column("Datum", lambda q: fmt_date(q.quote_date), sort=lambda q: (_naive(q.quote_date), q.id), width=115, descending=True),
            Column("Angebotsnummer", lambda q: q.quote_number, width=160, descending=True),
            Column("Kunde", c.customer_display_name),
            Column("Betrag", lambda q: fmt_money(q.gross_amount), sort=lambda q: q.gross_amount, width=130, descending=True),
            Column("Status", lambda q: q.status + (" (archiviert)" if q.archived_at else ""), width=170),
            Column("", lambda q: "", width=56, icon_svg=PDF_SVG, tooltip="Angebot drucken",
                   on_click=lambda q: interface.open_pdf(q.id, print_only=True)),
            Column("", lambda q: "", width=56, icon_svg=ROCKET_SVG, tooltip="In Rechnung umwandeln",
                   on_click=lambda q: interface.convert_to_invoice(q.id, ask=True)),
        ]
        super().__init__("Angebote", columns, (SignalBus.get().quotesChanged, SignalBus.get().customersChanged),
                         date_of=lambda q: q.quote_date, row_color=self._row_color, parent=interface)
        self.add_header_button("Neues Angebot", lambda: interface.show_editor(), primary=True)

    @staticmethod
    def _row_color(quote):
        if quote.status == "Angenommen":
            return COLOR_GREEN
        if quote.status in ("Abgelehnt", "Abgelaufen"):
            return COLOR_GREY
        return None

    def records(self) -> list:
        return self.c.get_quotes()

    def on_activated(self, quote):
        self.interface.show_editor(quote.id)

    def fill_context_menu(self, menu: RoundMenu, quote):
        interface = self.interface
        add_action(menu, FIF.EDIT, "Anzeigen" if quote.archived_at else "Bearbeiten", lambda: interface.show_editor(quote.id))
        add_action(menu, FIF.VIEW, "PDF öffnen", lambda: interface.open_pdf(quote.id))
        add_action(menu, FIF.SAVE, "PDF speichern unter...", lambda: interface.save_pdf(quote.id))
        add_action(menu, FIF.PRINT, "Drucken", lambda: interface.open_pdf(quote.id, print_only=True))
        add_action(menu, FIF.DOCUMENT, "In Rechnung übernehmen", lambda: interface.convert_to_invoice(quote.id))
        if not quote.archived_at: # quotes archived in older versions stay locked
            add_action(menu, FIF.DELETE, "Löschen", lambda: interface.delete(quote.id))
        menu.addSeparator()
        status_menu = RoundMenu("Status ändern", menu)
        status_menu.setIcon(FIF.TAG)
        for status in QUOTE_STATUSES:
            if status != quote.status:
                add_action(status_menu, FIF.TAG, status, lambda checked=False, s=status: self.c.update_quote_status(quote.id, s))
        menu.addMenu(status_menu)


class QuoteInterface(QWidget):
    def __init__(self, db_controller: DBController, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("QuoteInterface")
        self.db_controller = db_controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.stackedWidget = QStackedWidget(self)
        layout.addWidget(self.stackedWidget)

        self.list_page = QuoteListPage(self)
        self.editor = QuoteEditor(db_controller)
        self.editor.saved.connect(self._on_saved)
        self.editor.canceled.connect(self.leave_editor)
        self.stackedWidget.addWidget(self.list_page)
        self.stackedWidget.addWidget(self.editor)

    def show_list(self):
        self.stackedWidget.setCurrentWidget(self.list_page)

    def show_editor(self, quote_id=None):
        if quote_id:
            self.editor.load_quote(quote_id)
        else:
            self.editor.clear_form()
        self.editor.mark_clean()
        self.stackedWidget.setCurrentWidget(self.editor)

    # --- Unsaved changes (asked by the main window before switching tabs) ---
    def has_unsaved_changes(self) -> bool:
        return (self.stackedWidget.currentWidget() is self.editor and not self.editor._read_only
                and self.editor.has_unsaved_changes())

    def discard_changes(self):
        self.editor.clear_form()
        self.editor.mark_clean()
        self.show_list()

    def leave_editor(self):
        """"Zurück": asks first if something was typed."""
        if self.has_unsaved_changes() and not ask_discard_changes(self):
            return
        self.discard_changes()

    def _on_saved(self, quote_id):
        notify_success(self, "Gespeichert", "Angebot wurde gespeichert.")
        self.show_list()

    def _render(self, quote_id) -> str:
        quote = self.db_controller.get_quote(quote_id)
        path = paths.temp_document(f"Angebot_{quote.quote_number}.pdf")
        PDFGenerator(self.db_controller).generate_quote_pdf(quote, path)
        return path

    def _render_or_report(self, quote_id):
        try:
            return self._render(quote_id)
        except Exception as e:
            logger.exception("Angebots-PDF fehlgeschlagen")
            notify_error(self, "PDF konnte nicht erstellt werden", f"{e}\nDetails: {paths.LOG_PATH}")
            return None

    def open_pdf(self, quote_id, print_only=False):
        path = self._render_or_report(quote_id)
        if path:
            open_document(self, path, print_document=print_only)

    def save_pdf(self, quote_id):
        quote = self.db_controller.get_quote(quote_id)
        target, _ = QFileDialog.getSaveFileName(self, "PDF speichern unter", paths.desktop_path(f"Angebot_{quote.quote_number}.pdf"), "PDF (*.pdf)")
        if not target:
            return
        path = self._render_or_report(quote_id)
        if not path:
            return
        try:
            shutil.copyfile(path, target)
        except OSError as e:
            notify_error(self, "PDF nicht gespeichert", str(e))
            return
        notify_success(self, "PDF gespeichert", target)

    def convert_to_invoice(self, quote_id, ask: bool = False):
        quote = self.db_controller.get_quote(quote_id)
        if ask and not confirm(self, "In Rechnung umwandeln",
                               f"Aus Angebot {quote.quote_number} einen Rechnungsentwurf mit allen Positionen erstellen?"):
            return
        try:
            invoice_id = self.db_controller.create_invoice_from_quote(quote_id)
        except ValueError as e:
            notify_error(self, "Nicht möglich", str(e))
            return
        main_window = self.window()
        if hasattr(main_window, "open_invoice"):
            main_window.open_invoice(invoice_id)
        notify_success(self, "Rechnungsentwurf erstellt", "Die Positionen des Angebots wurden übernommen.")

    def delete(self, quote_id):
        if not confirm(self, "Angebot löschen", "Möchten Sie dieses Angebot wirklich löschen?"):
            return
        try:
            self.db_controller.delete_quote(quote_id)
        except GoBDError as e:
            notify_error(self, "Nicht erlaubt", str(e))
            return
        notify_success(self, "Gelöscht", "Das Angebot wurde gelöscht.")
