"""A minimal PDF receipt for cashbook entries that require one (Einnahme, Barentnahme Firma)."""
import os
import tempfile

RECEIPT = os.path.join(tempfile.mkdtemp(prefix="schalk_beleg_"), "beleg.pdf")
with open(RECEIPT, "wb") as f:
    f.write(b"%PDF-1.4 Testbeleg\n%%EOF\n")
