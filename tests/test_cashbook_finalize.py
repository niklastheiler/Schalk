from datetime import datetime
import pytest
from src.controllers.db_controller import GoBDError
from src.models.database import CashbookEntry


def test_drafts_are_editable_until_finalized(controller):
    c = controller
    late = c.add_cashbook_entry(datetime(2026, 10, 5), 100, "Einnahme spät", "A", "Einnahme", 19)
    early = c.add_cashbook_entry(datetime(2026, 10, 1), 50, "Tippfehler", "A", "Einnahme", 19)
    wrong = c.add_cashbook_entry(datetime(2026, 10, 2), 10, "Falsch", "A", "Barentnahme Firma", 19)
    assert c.get_cashbook_entry(early).receipt_number is None and c.cashbook_draft_count() == 3

    c.update_cashbook_entry(early, datetime(2026, 10, 1), 60, "Einlage", "Einnahme")
    assert c.get_cashbook_entry(early).amount == 60 and c.get_cashbook_entry(early).description == "Einlage"
    c.delete_cashbook_entry(wrong)
    assert c.get_cashbook_entry(wrong) is None
    with pytest.raises(GoBDError):
        c.storno_cashbook_entry(early)

    assert c.finalize_cashbook() == 2
    # Receipt numbers follow the booking date, not the order of input
    assert c.get_cashbook_entry(early).receipt_number < c.get_cashbook_entry(late).receipt_number
    assert c.cashbook_draft_count() == 0 and c.finalize_cashbook() == 0

    with pytest.raises(GoBDError):
        c.update_cashbook_entry(early, datetime(2026, 10, 1), 70, "Geändert", "Einnahme")
    with pytest.raises(GoBDError):
        c.delete_cashbook_entry(early)
    c.storno_cashbook_entry(early)

    # Later drafts continue the existing chain
    c.add_cashbook_entry(datetime(2026, 10, 6), 5, "Nachtrag", "A", "Einnahme", 19)
    c.finalize_cashbook()
    assert c.verify_integrity() == []


def test_tampering_with_finalized_entry_is_detected(controller):
    c = controller
    entry_id = c.add_cashbook_entry(datetime(2026, 10, 1), 100, "Einlage", "A", "Einnahme", 19)
    c.finalize_cashbook()
    with c.get_session() as session:
        session.get(CashbookEntry, entry_id).amount = 999
        session.commit()
    assert any("Kassenbuch" in p for p in c.verify_integrity())


def test_cashbook_ui_edit_and_finalize(window, controller, qapp, monkeypatch):
    import src.views.cashbook_interface as module
    monkeypatch.setattr(module, "confirm", lambda *a: True)
    cb = window.cashbook_interface
    window.switchTo(cb)
    cb.amountEdit.setText("40,00")
    cb.descEdit.setText("Erst")
    cb.add_entry()
    qapp.processEvents()
    entry = cb.model.record(0)
    assert cb.finalizeBtn.isEnabled() and "(1)" in cb.finalizeBtn.text()

    cb.on_activated(entry)
    assert cb.addBtn.text() == "Änderung speichern" and cb.amountEdit.text() == "40,00"
    cb.descEdit.setText("Korrigiert")
    cb.add_entry()
    qapp.processEvents()
    assert controller.get_cashbook_entry(entry.id).description == "Korrigiert"
    assert cb.editing_id is None and cb.model.rowCount() == 1

    cb.finalize_cashbook()
    qapp.processEvents()
    assert controller.get_cashbook_entry(entry.id).receipt_number
    assert not cb.finalizeBtn.isEnabled()
