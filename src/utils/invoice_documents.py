import logging
import os
import tempfile
from facturx import generate_from_binary
from src.controllers.db_controller import DBController, GoBDError
from src.utils.pdf_generator import PDFGenerator
from src.utils.pdfa import add_output_intent
from src.utils.einvoice_validation import validate_en16931
from src.utils.zugferd_generator import build_cii_xml, xrechnung_problems

logger = logging.getLogger(__name__)


def validate_invoice(db_controller: DBController, invoice) -> list:
    """EN 16931 Schematron check of the invoice's e-invoice data (runs before it is sealed)."""
    try:
        return validate_en16931(build_cii_xml(invoice, db_controller, "en16931"))
    except ValueError as e:
        return [str(e)]


def render_einvoice_pdf(db_controller: DBController, invoice) -> bytes:
    """Hybrid e-invoice: PDF/A-3 with embedded EN 16931 XML (ZUGFeRD 2 / Factur-X)."""
    seller = db_controller.seller_of(invoice)
    pdf = PDFGenerator(db_controller).render_invoice(invoice)
    xml = build_cii_xml(invoice, db_controller, "en16931")
    title = f"{'Stornorechnung' if invoice.cancels_invoice_id else 'Rechnung'} {invoice.invoice_number}"
    pdf = generate_from_binary(
        pdf, xml, flavor="factur-x", level="en16931", check_xsd=False, lang="de-DE",
        pdf_metadata={"author": seller.get("company_name") or "", "title": title,
                      "subject": title, "keywords": "Factur-X, ZUGFeRD, Rechnung"},
    )
    return add_output_intent(pdf)


def archive_invoice_document(db_controller: DBController, invoice_id: int) -> str:
    """Renders a finalized invoice once and stores it read-only in the archive (GoBD)."""
    invoice = db_controller.get_invoice(invoice_id)
    if invoice.pdf_path:
        return invoice.pdf_path
    with tempfile.TemporaryDirectory() as temp_dir:
        path = os.path.join(temp_dir, f"Rechnung_{invoice.invoice_number}.pdf")
        with open(path, "wb") as f:
            f.write(render_einvoice_pdf(db_controller, invoice))
        return db_controller.store_invoice_pdf(invoice_id, path)


def build_invoice_pdf(db_controller: DBController, invoice) -> str:
    """
    Path of the invoice PDF. Finalized invoices always come from the archive, so they are
    reproduced exactly as issued; drafts are rendered as a preview into the temp directory.
    """
    invoice = db_controller.get_invoice(invoice.id) # with items
    if not db_controller.is_finalized(invoice):
        preview = os.path.join(tempfile.gettempdir(), f"Schalk_Entwurf_{invoice.id}.pdf")
        PDFGenerator(db_controller).generate_invoice_pdf(invoice, preview)
        return preview
    return db_controller.get_archived_invoice_pdf(invoice) or archive_invoice_document(db_controller, invoice.id)


def export_xrechnung(db_controller: DBController, invoice, path: str):
    """Writes the invoice as XRechnung 3.0 (CII). Raises GoBDError if mandatory data is missing."""
    if not db_controller.is_finalized(invoice):
        raise GoBDError("Nur festgeschriebene Rechnungen können als XRechnung exportiert werden.")
    problems = xrechnung_problems(db_controller, invoice)
    if problems:
        raise GoBDError("Für eine XRechnung fehlen Angaben:\n• " + "\n• ".join(problems))
    with open(path, "wb") as f:
        f.write(build_cii_xml(invoice, db_controller, "xrechnung"))
