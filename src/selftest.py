"""
Self-test of the built program: Schalk.exe --selbsttest

Runs the main path of the program in a temporary data folder: creates and finalizes an invoice, renders the
ZUGFeRD PDF, checks its embedded XML with the EN 16931 rules, exports and checks the XRechnung and writes a
backup. The release workflow runs it on the EXE, so files PyInstaller did not bundle are found before a
release instead of on the users' computers. Exit code 0 = everything works; otherwise the error is written to
%TEMP%\\schalk_selbsttest.log.
"""
import os
import tempfile
import traceback
from datetime import datetime, timezone

REPORT = os.path.join(tempfile.gettempdir(), "schalk_selbsttest.log")
_app = None
SELLER = {
    "company_name": "Selbsttest GmbH", "first_name": "Max", "last_name": "Muster", "address": "Hauptstr. 1",
    "postal_code": "10115", "city": "Berlin", "tax_id": "12/345/67890", "vat_id": "DE100000008",
    "email": "info@example.com", "phone": "030 123456", "iban": "DE02120300000000202051", "bic": "BYLADEM1001",
}


def _check(controller):
    from facturx import get_facturx_xml_from_pdf
    from src.utils.backup import create_backup
    from src.utils.einvoice_parser import read_einvoice
    from src.utils.einvoice_validation import validate_en16931
    from src.utils.invoice_documents import build_invoice_pdf, export_xrechnung
    from src.utils import paths

    controller.set_settings(SELLER)
    customer_id = controller.add_customer(company_name="Łukasz Wiśniewski Kunde AG", address="Weg 2", postal_code="20095",
                                          city="Hamburg", email="rechnung@example.com")
    day = datetime.now(timezone.utc)
    invoice_id = controller.create_invoice(customer_id, day, day, [
        {"title": "Beratung", "quantity": 2, "unit": "Stunde", "unit_price": 100.0, "tax_percent": 19.0},
        {"title": "Fachbuch", "quantity": 1, "unit": "Stück", "unit_price": 20.0, "tax_percent": 7.0},
    ], status="Offen")
    invoice = controller.get_invoice(invoice_id)
    with open(build_invoice_pdf(controller, invoice), "rb") as f:
        _, xml = get_facturx_xml_from_pdf(f.read(), check_xsd=True)
    problems = validate_en16931(xml)
    if problems:
        raise AssertionError("ZUGFeRD verletzt EN 16931: " + "; ".join(problems))
    target = os.path.join(paths.DATA_DIR, "xrechnung.xml")
    export_xrechnung(controller, invoice, target)
    if read_einvoice(target).number != invoice.invoice_number:
        raise AssertionError("XRechnung kann nicht wieder gelesen werden")
    create_backup(controller.db.snapshot(), os.path.join(paths.DATA_DIR, "test.backup"), {"app_data": paths.APP_DATA_DIR})
    problems = controller.verify_integrity(check_files=True)
    if problems:
        raise AssertionError("Integritätsprüfung: " + "; ".join(problems))


def run() -> int:
    """
    Only call with SCHALK_DATA_DIR pointing to a temporary folder (see run.py). Never raises: the windowed EXE
    would show an error dialog that nobody closes on the build server.
    """
    from src.utils import paths
    from src.utils.archive import remove_tree

    global _app
    controller = None
    try:
        from PySide6.QtCore import QCoreApplication
        from src.controllers.db_controller import DBController
        from src.models.database import DatabaseManager
        from src.utils.invoice_documents import archive_invoice_document, validate_invoice

        _app = QCoreApplication.instance() or QCoreApplication([]) # the signals of the controller need an application
        controller = DBController(DatabaseManager(paths.DB_PATH, paths.KEY_PATH))
        controller.archiver = lambda invoice_id: archive_invoice_document(controller, invoice_id)
        controller.einvoice_validator = lambda invoice: validate_invoice(controller, invoice)
        _check(controller)
        controller.close()
        controller = None
        result = 0
        message = "Selbsttest erfolgreich\n"
    except BaseException:
        result = 1
        message = traceback.format_exc()
    finally:
        if controller is not None:
            try:
                controller.close()
            except Exception:
                pass
        try:
            remove_tree(paths.DATA_DIR)
        except OSError:
            pass # only a temporary folder
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write(message)
    return result
