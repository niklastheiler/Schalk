import os
import zipfile
from src.controllers.db_controller import DBController
from src.utils.invoice_documents import build_invoice_pdf

class DatevGenerator:
    def __init__(self, db_controller: DBController):
        self.db_controller = db_controller

    def _write_zip(self, filepath: str, files: dict):
        """files: {name in archive: source path}"""
        with zipfile.ZipFile(filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for arcname, source in files.items():
                zipf.write(source, arcname)

    def generate_export(self, invoices: list, filepath: str, month: int, year: int) -> bool:
        """
        Generates a ZIP archive containing all related PDF invoices for the selected month.
        Uses the archived PDFs, i.e. exactly the documents that were issued.
        """
        if not invoices:
            return False

        try:
            files = {}
            for invoice in invoices:
                # Reload so items/customer are available outside the caller's session
                full_invoice = self.db_controller.get_invoice(invoice.id)
                pdf_path, _ = build_invoice_pdf(self.db_controller, full_invoice)
                files[f"Rechnung_{full_invoice.invoice_number}.pdf"] = pdf_path
            self._write_zip(filepath, files)
            return True
        except Exception as e:
            print(f"Error generating PDF export: {e}")
            return False

    def generate_cashbook_export(self, entries: list, filepath: str, month: int, year: int) -> bool:
        """
        Generates a ZIP archive containing all related receipt files for Cashbook.
        """
        if not entries:
            return False

        try:
            files = {}
            for entry in entries:
                attachment = self.db_controller.get_cashbook_attachment(entry)
                if attachment and os.path.isfile(attachment):
                    # Prepend receipt number to ensure uniqueness
                    files[f"{entry.receipt_number}_{os.path.basename(attachment)}"] = attachment
            self._write_zip(filepath, files)
            return True
        except Exception as e:
            print(f"Error generating Cashbook PDF export: {e}")
            return False

    def generate_incoming_export(self, invoices: list, filepath: str) -> bool:
        """
        Generates a ZIP archive containing all uploaded PDFs for incoming invoices.
        """
        invoices = [inv for inv in invoices if not inv.cancelled_at]
        if not invoices:
            return False

        try:
            files = {}
            for inv in invoices:
                if os.path.exists(inv.file_path):
                    files[f"{inv.date.strftime('%Y%m%d')}_{os.path.basename(inv.file_path)}"] = inv.file_path
            self._write_zip(filepath, files)
            return True
        except Exception as e:
            print(f"Error generating incoming invoice export: {e}")
            return False
