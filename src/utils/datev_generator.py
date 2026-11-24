"""
Belege export for DATEV Unternehmen online / the tax advisor: a ZIP archive per month with the
documents exactly as issued or received (archived e-invoice PDFs incl. their embedded XML).
"""
import logging
import os
import zipfile
from src.controllers.db_controller import DBController
from src.utils import paths
from src.utils.invoice_documents import build_invoice_pdf

logger = logging.getLogger(__name__)


class DatevGenerator:
    def __init__(self, db_controller: DBController):
        self.db_controller = db_controller

    @staticmethod
    def _write_zip(filepath: str, files: dict) -> bool:
        """files: {name in archive: source path}"""
        if not files:
            return False
        with zipfile.ZipFile(filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for arcname, source in files.items():
                zipf.write(source, arcname)
        return True

    @staticmethod
    def exportable_invoices(db_controller: DBController) -> list:
        """
        Paid, issued invoices. Cancelled invoices are left out together with their Stornorechnung: both cancel
        each other out and are not handed to the tax advisor.
        """
        return [i for i in db_controller.get_invoices() if db_controller.is_finalized(i) and i.status == "Bezahlt"
                and not i.cancels_invoice_id]

    def generate_export(self, invoices: list, filepath: str) -> bool:
        invoices = [i for i in invoices if i.status != "Storniert" and not i.cancels_invoice_id]
        try:
            files = {f"Rechnung_{i.invoice_number}.pdf": build_invoice_pdf(self.db_controller, i) for i in invoices}
            return self._write_zip(filepath, files)
        except Exception:
            logger.exception("DATEV-Export der Rechnungen fehlgeschlagen")
            return False

    @staticmethod
    def exportable_cashbook_entries(db_controller: DBController, entries: list) -> list:
        """
        Finalized entries without cancelled ones: an entry and its Storno-Gegenbuchung cancel each other out,
        like a cancelled invoice and its Stornorechnung, and their receipts are not handed to the tax advisor.
        """
        all_entries = db_controller.get_cashbook_entries()
        cancelled = {e.storno_of_id for e in all_entries if e.is_storno and e.storno_of_id}
        return [e for e in entries if e.finalized_at and not e.is_storno and e.id not in cancelled]

    @staticmethod
    def exported_before(db_controller: DBController, entries: list) -> list:
        """Entries of the list that already went to the tax advisor with an earlier DATEV export."""
        return [e for e in entries
                if any(h.action == "DATEV Export" for h in db_controller.get_document_history("Cashbook", e.id))]

    def generate_cashbook_export(self, entries: list, filepath: str) -> bool:
        entries = self.exportable_cashbook_entries(self.db_controller, entries)
        try:
            attachments = [(e, paths.resolve(e.attachment_path)) for e in entries if e.attachment_path]
            files = {f"{e.receipt_number}_{os.path.basename(path)}": path for e, path in attachments if os.path.isfile(path)}
            return self._write_zip(filepath, files)
        except Exception:
            logger.exception("DATEV-Export des Kassenbuchs fehlgeschlagen")
            return False

    def generate_incoming_export(self, invoices: list, filepath: str) -> bool:
        try:
            documents = [(i, paths.resolve(i.file_path)) for i in invoices if not i.cancelled_at]
            files = {f"{i.date.strftime('%Y%m%d')}_{os.path.basename(path)}": path for i, path in documents if os.path.isfile(path)}
            return self._write_zip(filepath, files)
        except Exception:
            logger.exception("DATEV-Export der Eingangsrechnungen fehlgeschlagen")
            return False
