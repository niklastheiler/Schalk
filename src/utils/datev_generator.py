import os
from datetime import datetime
import zipfile
import tempfile
import shutil
from src.models.database import Invoice
from src.controllers.db_controller import DBController
from src.utils.pdf_generator import PDFGenerator

class DatevGenerator:
    def __init__(self, db_controller: DBController):
        self.db_controller = db_controller

    def generate_export(self, invoices: list, filepath: str, month: int, year: int) -> bool:
        """
        Generates a ZIP archive containing all related PDF invoices for the selected month.
        """
        if not invoices:
            return False
            
        try:
            # Use a temporary directory to build the ZIP contents
            with tempfile.TemporaryDirectory() as temp_dir:
                pdf_gen = PDFGenerator(self.db_controller)
                # Add PDFs for all invoices by generating them on the fly
                for invoice in invoices:
                    pdf_filename = f"Rechnung_{invoice.invoice_number}.pdf"
                    pdf_path = os.path.join(temp_dir, pdf_filename)
                    pdf_gen.generate_invoice_pdf(invoice, pdf_path)
                
                # Create the ZIP archive
                with zipfile.ZipFile(filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for root, _, files in os.walk(temp_dir):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, temp_dir)
                            zipf.write(file_path, arcname)
                            
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
            with tempfile.TemporaryDirectory() as temp_dir:
                # Add receipt files for all entries
                for entry in entries:
                    if entry.description and entry.description != "Keine Angabe" and os.path.exists(entry.description):
                        if os.path.isfile(entry.description):
                            filename = os.path.basename(entry.description)
                            # Prepend receipt number to ensure uniqueness
                            safe_filename = f"{entry.receipt_number}_{filename}"
                            shutil.copy2(entry.description, os.path.join(temp_dir, safe_filename))
                
                # Create the ZIP archive
                with zipfile.ZipFile(filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for root, _, files in os.walk(temp_dir):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, temp_dir)
                            zipf.write(file_path, arcname)
                            
            return True
        except Exception as e:
            print(f"Error generating Cashbook PDF export: {e}")
            return False

    def generate_incoming_export(self, invoices: list, filepath: str) -> bool:
        """
        Generates a ZIP archive containing all uploaded PDFs for incoming invoices.
        """
        if not invoices:
            return False
            
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                for inv in invoices:
                    if os.path.exists(inv.file_path):
                        # Use a safe filename
                        safe_filename = f"{inv.date.strftime('%Y%m%d')}_{os.path.basename(inv.file_path)}"
                        shutil.copy2(inv.file_path, os.path.join(temp_dir, safe_filename))
                        
                with zipfile.ZipFile(filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for root, _, files in os.walk(temp_dir):
                        for file in files:
                            file_path = os.path.join(root, file)
                            arcname = os.path.relpath(file_path, temp_dir)
                            zipf.write(file_path, arcname)
                            
            return True
        except Exception as e:
            print(f"Error generating incoming invoice export: {e}")
            return False
