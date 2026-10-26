import os
import tempfile
from src.controllers.db_controller import DBController
from src.utils.pdf_generator import PDFGenerator
from src.utils.zugferd_generator import generate_zugferd_xml


def build_invoice_pdf(db_controller: DBController, invoice) -> tuple:
    """
    Returns (pdf_path, is_e_invoice).
    Finalized invoices are rendered once (incl. ZUGFeRD XML), archived read-only and from then on
    always reproduced from the archive, so later changes to settings or customers don't alter them.
    Drafts are rendered as a preview into the temp directory.
    """
    is_e_invoice = bool(invoice.items)

    if not db_controller.is_finalized(invoice):
        preview = os.path.join(tempfile.gettempdir(), f"Entwurf_{invoice.id}.pdf")
        PDFGenerator(db_controller).generate_invoice_pdf(invoice, preview)
        return preview, False

    archived = db_controller.get_archived_invoice_pdf(invoice) # raises GoBDError if tampered
    if archived:
        return archived, is_e_invoice

    with tempfile.TemporaryDirectory() as temp_dir:
        base_pdf = os.path.join(temp_dir, f"base_{invoice.invoice_number}.pdf")
        PDFGenerator(db_controller).generate_invoice_pdf(invoice, base_pdf)

        final_pdf = base_pdf
        if is_e_invoice:
            from facturx import generate_from_file
            xml_path = os.path.join(temp_dir, "factur-x.xml")
            generate_zugferd_xml(invoice, db_controller, xml_path)
            final_pdf = os.path.join(temp_dir, f"Rechnung_{invoice.invoice_number}.pdf")
            generate_from_file(pdf_file=base_pdf, xml=xml_path, output_pdf_file=final_pdf)

        return db_controller.store_invoice_pdf(invoice.id, final_pdf), is_e_invoice
