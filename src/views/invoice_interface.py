import logging
import os
import shutil
from datetime import datetime
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import Action, ComboBox, FluentIcon as FIF, MessageBoxBase, RoundMenu, SubtitleLabel
from src.controllers.db_controller import DBController, GoBDError
from src.utils import paths
from src.utils.invoice_documents import build_invoice_pdf, export_xrechnung
from src.utils.signal_bus import SignalBus
from src.views.common import (COLOR_GREEN, COLOR_GREY, COLOR_RED, COLOR_YELLOW, Column, ListPage, confirm, fmt_date,
                              fmt_money, notify_error, notify_success, show_message)
from src.views.invoice_editor import InvoiceEditor

logger = logging.getLogger(__name__)

RIGHT = Qt.AlignRight | Qt.AlignVCenter


def _naive(value):
    return value.replace(tzinfo=None) if value else datetime.min


def add_action(menu: RoundMenu, icon, text: str, slot):
    action = Action(icon, text, menu)
    action.triggered.connect(slot)
    menu.addAction(action)


class MonthDialog(MessageBoxBase):
    def __init__(self, title: str, months: list, parent=None):
        super().__init__(parent)
        self.viewLayout.addWidget(SubtitleLabel(title, self))
        self.monthCombo = ComboBox(self)
        self.monthCombo.addItems(months)
        self.viewLayout.addWidget(self.monthCombo)
        self.widget.setMinimumWidth(350)


class InvoiceListPage(ListPage):
    def __init__(self, interface: "InvoiceInterface"):
        self.interface = interface
        c = interface.db_controller
        self.c = c
        columns = [
            Column("Datum", lambda i: fmt_date(i.invoice_date), sort=lambda i: (_naive(i.invoice_date), i.id), width=100, descending=True),
            Column("Rechnungsnummer", self._number_text, width=180, descending=True),
            Column("Kunde", c.customer_display_name),
            Column("Betrag", lambda i: fmt_money(i.gross_amount), sort=lambda i: i.gross_amount, width=130, align=RIGHT, descending=True),
            Column("Fällig am", self._due_text, sort=lambda i: c.get_due_date(i) if self._due_text(i) else None, width=110),
            Column("Status", lambda i: i.status, width=140, choices=c.next_invoice_statuses,
                   on_choice=lambda invoice, status: interface.change_status(invoice.id, status)),
        ]
        super().__init__("Rechnungen", columns, (SignalBus.get().invoicesChanged, SignalBus.get().customersChanged),
                         date_of=lambda i: i.invoice_date, row_color=self._row_color, parent=interface)
        self.add_header_button("DATEV Export", interface.show_datev_export_dialog)
        self.add_header_button("Neue Rechnung", lambda: interface.show_editor(), primary=True)

    def _number_text(self, invoice) -> str:
        if self.c.is_draft_number(invoice.invoice_number):
            return "Entwurf"
        return invoice.invoice_number + (" (Storno)" if invoice.cancels_invoice_id else "")

    def _due_text(self, invoice) -> str:
        if not self.c.is_finalized(invoice) or invoice.cancels_invoice_id:
            return ""
        return fmt_date(self.c.get_due_date(invoice))

    def _row_color(self, invoice):
        if invoice.status == "Bezahlt":
            return COLOR_GREEN
        if invoice.status == "Storniert":
            return COLOR_GREY
        if invoice.status == "Überfällig":
            return COLOR_RED
        if invoice.status in ("Offen", "Teilbezahlt") and (self.c.get_due_date(invoice) - datetime.now()).days < 7:
            return COLOR_YELLOW
        return None

    def records(self) -> list:
        return self.c.get_invoices()

    def on_activated(self, invoice):
        self.interface.show_editor(invoice.id)

    def fill_context_menu(self, menu: RoundMenu, invoice):
        interface, c = self.interface, self.c
        finalized = c.is_finalized(invoice)

        add_action(menu, FIF.EDIT, "Anzeigen" if finalized else "Bearbeiten", lambda: interface.show_editor(invoice.id))
        add_action(menu, FIF.VIEW, "PDF öffnen" if finalized else "Entwurf als PDF öffnen", lambda: interface.open_pdf(invoice.id))
        add_action(menu, FIF.SAVE, "PDF speichern unter...", lambda: interface.save_pdf(invoice.id))
        add_action(menu, FIF.PRINT, "Drucken", lambda: interface.print_pdf(invoice.id))
        if finalized:
            add_action(menu, FIF.CODE, "XRechnung (XML) exportieren...", lambda: interface.export_xrechnung(invoice.id))
        if invoice.archived_at is None:
            add_action(menu, FIF.FOLDER, "Archivieren", lambda: interface.archive(invoice.id))
        if not finalized:
            add_action(menu, FIF.DELETE, "Entwurf löschen", lambda: interface.delete(invoice.id))
        elif invoice.status != "Storniert" and not invoice.cancels_invoice_id:
            add_action(menu, FIF.CANCEL, "Stornieren", lambda: interface.change_status(invoice.id, "Storniert"))
        add_action(menu, FIF.HISTORY, "Verlauf anzeigen", lambda: interface.show_history(invoice.id))

        statuses = c.next_invoice_statuses(invoice)
        if statuses:
            menu.addSeparator()
            status_menu = RoundMenu("Status ändern", menu)
            status_menu.setIcon(FIF.TAG)
            for status in statuses:
                add_action(status_menu, FIF.TAG, status, lambda checked=False, s=status: interface.change_status(invoice.id, s))
            menu.addMenu(status_menu)


class InvoiceInterface(QWidget):
    def __init__(self, db_controller: DBController, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("InvoiceInterface")
        self.db_controller = db_controller

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.stackedWidget = QStackedWidget(self)
        layout.addWidget(self.stackedWidget)

        self.list_page = InvoiceListPage(self)
        self.editor = InvoiceEditor(db_controller)
        self.editor.saved.connect(self._on_saved)
        self.editor.canceled.connect(self.show_list)
        self.stackedWidget.addWidget(self.list_page)
        self.stackedWidget.addWidget(self.editor)

    # --- Navigation ---
    def show_list(self):
        self.stackedWidget.setCurrentWidget(self.list_page)

    def show_editor(self, invoice_id=None):
        if invoice_id:
            self.editor.load_invoice(invoice_id)
        else:
            self.editor.clear_form()
        self.stackedWidget.setCurrentWidget(self.editor)

    def _on_saved(self, invoice_id):
        notify_success(self, "Gespeichert", "Rechnung wurde gespeichert.")
        self.show_list()

    # --- Documents ---
    def _pdf_path(self, invoice_id):
        invoice = self.db_controller.get_invoice(invoice_id)
        try:
            return invoice, build_invoice_pdf(self.db_controller, invoice)
        except GoBDError as e:
            notify_error(self, "GoBD-Prüfung fehlgeschlagen", str(e), duration=10000)
        except Exception as e:
            logger.exception("PDF der Rechnung %s konnte nicht erstellt werden", invoice_id)
            notify_error(self, "PDF konnte nicht erstellt werden", f"{e}\nDetails: {paths.LOG_PATH}")
        return invoice, None

    def open_pdf(self, invoice_id):
        _, path = self._pdf_path(invoice_id)
        if path:
            os.startfile(path)

    def print_pdf(self, invoice_id):
        _, path = self._pdf_path(invoice_id)
        if path:
            os.startfile(path, "print")

    def save_pdf(self, invoice_id):
        invoice, path = self._pdf_path(invoice_id)
        if not path:
            return
        name = "Entwurf" if self.db_controller.is_draft_number(invoice.invoice_number) else invoice.invoice_number
        target, _ = QFileDialog.getSaveFileName(self, "PDF speichern unter", paths.desktop_path(f"Rechnung_{name}.pdf"), "PDF (*.pdf)")
        if target:
            shutil.copyfile(path, target)
            notify_success(self, "PDF gespeichert", target)

    def export_xrechnung(self, invoice_id):
        invoice = self.db_controller.get_invoice(invoice_id)
        target, _ = QFileDialog.getSaveFileName(self, "XRechnung speichern unter", paths.desktop_path(f"XRechnung_{invoice.invoice_number}.xml"), "XML (*.xml)")
        if not target:
            return
        try:
            export_xrechnung(self.db_controller, invoice, target)
        except GoBDError as e:
            show_message(self, "XRechnung nicht möglich", str(e))
            return
        self.db_controller.log_actions("Invoice", [invoice_id], "XRechnung exportiert")
        notify_success(self, "XRechnung exportiert", target)

    # --- Actions ---
    def archive(self, invoice_id):
        invoice = self.db_controller.get_invoice(invoice_id)
        if not self.db_controller.is_finalized(invoice) and not confirm(
                self, "Rechnung festschreiben",
                "Beim Archivieren wird die Rechnung festgeschrieben und erhält ihre endgültige Rechnungsnummer. "
                "Danach ist sie nicht mehr änderbar.\n\nFortfahren?"):
            return
        success, message = self.db_controller.archive_invoice(invoice_id)
        if success:
            notify_success(self, "Archiviert", "Rechnung wurde archiviert.")
        else:
            show_message(self, "Nicht archiviert", message)

    def change_status(self, invoice_id, new_status):
        invoice = self.db_controller.get_invoice(invoice_id)
        if not invoice or invoice.status == new_status:
            return
        if new_status == "Storniert":
            question = (f"Für Rechnung {invoice.invoice_number} wird eine Stornorechnung mit negativen Beträgen erstellt. "
                        "Dies kann nicht rückgängig gemacht werden.\n\nFortfahren?")
            if not confirm(self, "Rechnung stornieren", question):
                return
        elif not self.db_controller.is_finalized(invoice):
            question = ("Die Rechnung wird festgeschrieben und erhält ihre endgültige Rechnungsnummer. "
                        "Danach ist sie nicht mehr änderbar (nur noch Storno möglich).\n\nFortfahren?")
            if not confirm(self, "Rechnung festschreiben", question):
                return
        success, message = self.db_controller.update_invoice_status(invoice_id, new_status)
        if not success:
            show_message(self, "Nicht möglich", message)
        elif message:
            notify_success(self, "Status geändert", message, duration=5000)

    def delete(self, invoice_id):
        if not confirm(self, "Entwurf löschen", "Möchten Sie diesen Rechnungsentwurf wirklich löschen?"):
            return
        try:
            self.db_controller.delete_invoice(invoice_id)
        except GoBDError as e:
            notify_error(self, "Nicht erlaubt", str(e))
            return
        notify_success(self, "Gelöscht", "Der Entwurf wurde gelöscht.")

    def show_history(self, invoice_id):
        entries = self.db_controller.get_document_history("Invoice", invoice_id)
        lines = [f"{h.timestamp.strftime('%d.%m.%Y %H:%M')} UTC – {h.user}: {h.action}" for h in entries]
        show_message(self, "Verlauf", "\n".join(lines) or "Kein Verlauf vorhanden.")

    def show_datev_export_dialog(self):
        from src.utils.datev_generator import DatevGenerator
        exportable = [i for i in self.db_controller.get_invoices() if i.archived_at and i.status in ("Bezahlt", "Storniert")]
        months = sorted({i.invoice_date.strftime("%Y-%m") for i in exportable}, reverse=True)
        if not months:
            notify_error(self, "Keine Daten", "Es gibt keine archivierten bezahlten oder stornierten Rechnungen zum Exportieren.")
            return
        dialog = MonthDialog("DATEV Monats-Export (Belege)", months, self.window())
        if not dialog.exec():
            return
        selected = dialog.monthCombo.currentText()
        invoices = [i for i in exportable if i.invoice_date.strftime("%Y-%m") == selected]
        year, month = map(int, selected.split('-'))
        filename = f"DATEV_Export_Rechnungen_{year}_{month:02d}.zip"
        target, _ = QFileDialog.getSaveFileName(self, "DATEV-Export speichern", paths.desktop_path(filename), "ZIP (*.zip)")
        if not target:
            return
        if DatevGenerator(self.db_controller).generate_export(invoices, target):
            self.db_controller.log_actions("Invoice", [i.id for i in invoices], "DATEV Export")
            notify_success(self, "DATEV Export erfolgreich", f"{len(invoices)} Rechnungen exportiert:\n{target}", duration=5000)
        else:
            notify_error(self, "Fehler beim DATEV Export", f"Die Export-Datei konnte nicht erstellt werden. Details: {paths.LOG_PATH}")
