import logging
import os
import tempfile
from datetime import datetime
from PySide6.QtWidgets import QFileDialog
from qfluentwidgets import FluentIcon as FIF, RoundMenu
from src.controllers.db_controller import DBController, GoBDError
from src.utils import paths
from src.utils.pdf_generator import PDFGenerator
from src.utils.signal_bus import SignalBus
from src.views.common import COLOR_RED, COLOR_YELLOW, Column, ListPage, fmt_date, fmt_money, notify_error, notify_success
from src.views.invoice_interface import RIGHT, _naive, add_action

logger = logging.getLogger(__name__)

MAX_REMINDER_LEVEL = 3
REMINDER_INTERVAL_DAYS = 14


class ReminderInterface(ListPage):
    def __init__(self, db_controller: DBController, parent=None):
        self.db_controller = c = db_controller
        columns = [
            Column("Datum", lambda i: fmt_date(i.invoice_date), sort=lambda i: (_naive(i.invoice_date), i.id), width=100, descending=True),
            Column("Rechnungsnummer", lambda i: i.invoice_number, width=160, descending=True),
            Column("Kunde", c.customer_display_name),
            Column("Betrag", lambda i: fmt_money(i.gross_amount), sort=lambda i: i.gross_amount, width=130, align=RIGHT, descending=True),
            Column("Fällig seit", lambda i: fmt_date(c.get_due_date(i)), sort=lambda i: c.get_due_date(i), width=110),
            Column("Mahnstufe", lambda i: str(i.reminder_level or 0), sort=lambda i: i.reminder_level or 0, width=90, descending=True),
            Column("Nächste Mahnung", self._next_text, width=200),
        ]
        super().__init__("Mahnungen", columns, (SignalBus.get().invoicesChanged, SignalBus.get().customersChanged),
                         row_color=lambda i: COLOR_RED if self._next_level(i) else COLOR_YELLOW, parent=parent)
        self.setObjectName("ReminderInterface")
        self.add_header_button("Als bezahlt markieren", lambda: [self.mark_as_paid(i.id) for i in self.selected_records()])
        self.add_header_button("Mahnung erstellen", self.remind_selected, primary=True)

    # --- Rules ---
    @staticmethod
    def _days_since_last(invoice) -> int:
        return (datetime.now() - _naive(invoice.last_reminder_date)).days if invoice.last_reminder_date else 10 ** 6

    def _next_level(self, invoice):
        """Next possible reminder level, or None if not (yet) possible."""
        level = invoice.reminder_level or 0
        if level >= MAX_REMINDER_LEVEL:
            return None
        if level and self._days_since_last(invoice) < REMINDER_INTERVAL_DAYS:
            return None
        return level + 1

    def _next_text(self, invoice) -> str:
        next_level = self._next_level(invoice)
        if next_level:
            return f"{next_level}. Mahnung möglich"
        level = invoice.reminder_level or 0
        if level >= MAX_REMINDER_LEVEL:
            return "Letzte Mahnung versandt"
        return f"{level + 1}. Mahnung in {REMINDER_INTERVAL_DAYS - self._days_since_last(invoice)} Tagen"

    def records(self) -> list:
        self.db_controller.refresh_overdue()
        return [i for i in self.db_controller.get_invoices()
                if self.db_controller.is_finalized(i) and not i.cancels_invoice_id
                and (i.status == "Überfällig" or ((i.reminder_level or 0) > 0 and i.status not in ("Bezahlt", "Storniert")))]

    def on_activated(self, invoice):
        main_window = self.window()
        if hasattr(main_window, "open_invoice"):
            main_window.open_invoice(invoice.id)

    def fill_context_menu(self, menu: RoundMenu, invoice):
        next_level = self._next_level(invoice)
        if next_level:
            add_action(menu, FIF.MAIL, f"{next_level}. Mahnung erstellen", lambda: self.generate_reminder(invoice.id, next_level))
        if invoice.reminder_level:
            add_action(menu, FIF.PRINT, f"{invoice.reminder_level}. Mahnung erneut drucken", lambda: self.generate_reminder(invoice.id, invoice.reminder_level, print_only=True))
        add_action(menu, FIF.ACCEPT, "Als bezahlt markieren", lambda: self.mark_as_paid(invoice.id))
        add_action(menu, FIF.DOCUMENT, "Rechnung anzeigen", lambda: self.on_activated(invoice))

    # --- Actions ---
    def remind_selected(self):
        invoices = self.selected_records()
        if not invoices:
            notify_error(self, "Keine Auswahl", "Bitte zuerst eine oder mehrere Rechnungen auswählen.")
            return
        for invoice in invoices:
            next_level = self._next_level(invoice)
            if next_level:
                self.generate_reminder(invoice.id, next_level)
            else:
                notify_error(self, "Noch nicht möglich", f"{invoice.invoice_number}: {self._next_text(invoice)}")

    def mark_as_paid(self, invoice_id):
        success, message = self.db_controller.update_invoice_status(invoice_id, "Bezahlt")
        if success:
            notify_success(self, "Status aktualisiert", "Die Rechnung wurde als bezahlt markiert.")
        else:
            notify_error(self, "Nicht möglich", message)

    def generate_reminder(self, invoice_id, level, print_only=False):
        invoice = self.db_controller.get_invoice(invoice_id)
        filename = f"Mahnung_{level}_{invoice.invoice_number}.pdf"
        if print_only:
            target = os.path.join(tempfile.gettempdir(), filename)
        else:
            target, _ = QFileDialog.getSaveFileName(self, "Mahnung speichern unter", paths.desktop_path(filename), "PDF (*.pdf)")
            if not target:
                return
        try:
            PDFGenerator(self.db_controller).generate_reminder_pdf(invoice, target, level)
            if print_only:
                os.startfile(target, "print")
                return
            self.db_controller.record_reminder(invoice_id, level)
        except GoBDError as e:
            notify_error(self, "Nicht möglich", str(e))
            return
        except Exception as e:
            logger.exception("Mahnung konnte nicht erstellt werden")
            notify_error(self, "Fehler", f"Die PDF konnte nicht erstellt werden: {e}")
            return
        notify_success(self, "Mahnung erstellt", target, duration=5000)
