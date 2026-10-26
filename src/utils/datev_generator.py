"""
Belege export for DATEV Unternehmen online / the tax advisor: a ZIP archive per month with the
documents exactly as issued or received (archived e-invoice PDFs incl. their embedded XML).
"""
import logging
import os
import zipfile
from src.controllers.db_controller import DBController
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

    def generate_export(self, invoices: list, filepath: str) -> bool:
        try:
            files = {f"Rechnung_{i.invoice_number}.pdf": build_invoice_pdf(self.db_controller, i) for i in invoices}
            return self._write_zip(filepath, files)
        except Exception:
            logger.exception("DATEV-Export der Rechnungen fehlgeschlagen")
            return False

    def generate_cashbook_export(self, entries: list, filepath: str) -> bool:
        try:
            files = {f"{e.receipt_number}_{os.path.basename(e.attachment_path)}": e.attachment_path
                     for e in entries if e.attachment_path and os.path.isfile(e.attachment_path)}
            return self._write_zip(filepath, files)
        except Exception:
            logger.exception("DATEV-Export des Kassenbuchs fehlgeschlagen")
            return False

    def generate_incoming_export(self, invoices: list, filepath: str) -> bool:
        try:
            files = {f"{i.date.strftime('%Y%m%d')}_{os.path.basename(i.file_path)}": i.file_path
                     for i in invoices if not i.cancelled_at and os.path.isfile(i.file_path)}
            return self._write_zip(filepath, files)
        except Exception:
            logger.exception("DATEV-Export der Eingangsrechnungen fehlgeschlagen")
            return False
