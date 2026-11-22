"""
Performance baseline of the bookkeeping core: python tools/benchmark.py [number of invoices]

Measures in a temporary data folder (no real data is touched):
- creating and finalizing invoices (database, hash chain, without PDF/e-invoice)
- the e-invoice check (EN 16931 Schematron) and the ZUGFeRD PDF of one invoice
- saving the encrypted database, the GoBD integrity check and the start of the controller
Results are printed as a table; docs/AUDIT.md lists the values before and after the audit.
"""
import os
import sys
import tempfile
import time
from datetime import datetime, timezone

os.environ["SCHALK_DATA_DIR"] = tempfile.mkdtemp(prefix="schalk_benchmark_")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PySide6.QtWidgets import QApplication  # noqa: E402

DAY = datetime(2026, 10, 1, tzinfo=timezone.utc)
SELLER = {
    "company_name": "Benchmark GmbH", "first_name": "Max", "last_name": "Muster", "address": "Hauptstr. 1",
    "postal_code": "10115", "city": "Berlin", "tax_id": "12/345/67890", "vat_id": "DE100000008",
    "email": "info@example.com", "phone": "030 123456", "iban": "DE02120300000000202051", "bic": "BYLADEM1001",
}
ITEMS = [
    {"title": "Beratung", "quantity": 2, "unit": "Stunde", "unit_price": 100.0, "tax_percent": 19.0},
    {"title": "Fachbuch", "quantity": 3, "unit": "Stück", "unit_price": 19.99, "discount_percent": 10, "tax_percent": 7.0},
    {"title": "Material", "quantity": 1.5, "unit": "kg", "unit_price": 12.5, "tax_percent": 19.0},
]


def _timed(label: str, results: list, function, repeat: int = 1):
    start = time.perf_counter()
    value = None
    for _ in range(repeat):
        value = function()
    elapsed = (time.perf_counter() - start) / repeat
    results.append((label, elapsed))
    return value


def main(count: int = 1000) -> list:
    QApplication.instance() or QApplication([])
    from src.controllers.db_controller import DBController
    from src.models.database import DatabaseManager
    from src.utils import paths
    from src.utils.invoice_documents import render_einvoice_pdf, validate_invoice

    results = []
    controller = DBController(DatabaseManager(paths.DB_PATH, paths.KEY_PATH))
    controller.set_settings(SELLER)
    customer_id = controller.add_customer(company_name="Kunde AG", address="Weg 2", postal_code="20095", city="Hamburg")

    def create_all():
        for _ in range(count):
            controller.create_invoice(customer_id, DAY, DAY, ITEMS, status="Offen")
    _timed(f"{count} Rechnungen anlegen und festschreiben (gesamt)", results, create_all)
    results.append(("  je Rechnung", results[-1][1] / count))

    invoice = controller.get_invoice(controller.get_invoices()[0].id)
    _timed("E-Rechnungsprüfung EN 16931, erste (mit Laden der Regeln)", results, lambda: validate_invoice(controller, invoice))
    _timed("E-Rechnungsprüfung EN 16931, weitere", results, lambda: validate_invoice(controller, invoice), repeat=5)
    _timed("ZUGFeRD-PDF (PDF/A-3 mit XML) erzeugen", results, lambda: render_einvoice_pdf(controller, invoice), repeat=3)
    _timed("Datenbank verschlüsselt speichern", results, lambda: (controller.db.save(), controller.db.flush()), repeat=5)
    _timed("GoBD-Integritätsprüfung (ohne Dateien)", results, lambda: controller.verify_integrity(check_files=False), repeat=3)
    controller.close()
    _timed("Start: Datenbank öffnen und Controller laden", results,
           lambda: DBController(DatabaseManager(paths.DB_PATH, paths.KEY_PATH)).close())
    results.append(("Größe der verschlüsselten Datenbank (MB)", os.path.getsize(paths.DB_PATH) / 1e6))
    return results


if __name__ == "__main__":
    for label, value in main(int(sys.argv[1]) if len(sys.argv) > 1 else 1000):
        unit = "" if "MB" in label else " s"
        print(f"{label:<60} {value:10.4f}{unit}")
