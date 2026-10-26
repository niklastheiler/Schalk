"""
Creates sample e-invoices for every tax case: the ZUGFeRD PDF exactly as Schalk archives it and the
XRechnung export. The files can be checked with external validators (KoSIT, Mustang, veraPDF).

    python tools/create_sample_invoices.py [target folder]   (default: samples/e-rechnungen)
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
# Separate data folder, so the real data is never touched (must be set before src.utils.paths is imported)
TEMP_DATA_DIR = os.environ["SCHALK_DATA_DIR"] = tempfile.mkdtemp(prefix="schalk_samples_")
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]

from einvoice_cases import CASES, SELLER  # noqa: E402
from src.controllers.db_controller import DBController  # noqa: E402
from src.models.database import DatabaseManager  # noqa: E402
from src.utils import paths  # noqa: E402
from src.utils.invoice_documents import archive_invoice_document, build_invoice_pdf, export_xrechnung, validate_invoice  # noqa: E402


def create_samples(target: str) -> list:
    os.makedirs(target, exist_ok=True)
    controller = DBController(DatabaseManager(paths.DB_PATH, paths.KEY_PATH))
    controller.archiver = lambda invoice_id: archive_invoice_document(controller, invoice_id)
    controller.einvoice_validator = lambda invoice: validate_invoice(controller, invoice)
    controller.set_settings(SELLER)
    written = []
    try:
        for name, create in CASES.items():
            invoice = controller.get_invoice(create(controller))
            pdf = os.path.join(target, f"{name}.pdf")
            shutil.copyfile(build_invoice_pdf(controller, invoice), pdf)
            xml = os.path.join(target, f"{name}_XRechnung.xml")
            export_xrechnung(controller, invoice, xml)
            written += [pdf, xml]
    finally:
        controller.close()
        if os.path.abspath(paths.DATA_DIR) == os.path.abspath(TEMP_DATA_DIR):
            shutil.rmtree(TEMP_DATA_DIR, ignore_errors=True)
    return written


if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "samples", "e-rechnungen")
    for path in create_samples(folder):
        print(path)
