from PySide6.QtCore import Qt
from src.views.common import Column, RecordTableModel, natural_key


class Row:
    def __init__(self, number, amount, name):
        self.number, self.amount, self.name = number, amount, name


def _model():
    columns = [
        Column("Nummer", lambda r: r.number, descending=True),
        Column("Betrag", lambda r: f"{r.amount}", sort=lambda r: r.amount, descending=True),
        Column("Name", lambda r: r.name),
    ]
    model = RecordTableModel(columns)
    model.set_rows([Row("K2026-9", 5.0, "Ärzte"), Row("K2026-10", None, "bäcker"), Row("K2026-100", 50.0, ""), Row("K2026-2", 0.0, "Anton")])
    return model


def _column(model, col):
    return [model.text(r, col) for r in range(model.rowCount())]


def test_natural_key_numbers_case_and_umlauts():
    assert sorted(["K2026-10", "K2026-9", "K2026-100"], key=natural_key) == ["K2026-9", "K2026-10", "K2026-100"]
    assert sorted(["Zebra", "äpfel", "Birne"], key=natural_key) == ["äpfel", "Birne", "Zebra"]


def test_sort_both_directions(qapp):
    model = _model()
    model.sort(0, Qt.DescendingOrder)
    assert _column(model, 0) == ["K2026-100", "K2026-10", "K2026-9", "K2026-2"]
    model.sort(0, Qt.AscendingOrder)
    assert _column(model, 0) == ["K2026-2", "K2026-9", "K2026-10", "K2026-100"]


def test_empty_values_stay_at_the_end(qapp):
    model = _model()
    model.sort(1, Qt.DescendingOrder)
    assert _column(model, 1) == ["50.0", "5.0", "0.0", "None"]
    model.sort(1, Qt.AscendingOrder)
    assert _column(model, 1) == ["0.0", "5.0", "50.0", "None"]
    model.sort(2, Qt.AscendingOrder)
    assert _column(model, 2) == ["Anton", "Ärzte", "bäcker", ""]


def test_header_click_uses_column_direction_then_toggles(window, qapp):
    page = window.invoice_interface.list_page
    header = page.table.horizontalHeader()
    # Lists with a date start sorted by date, newest first
    assert (header.sortIndicatorSection(), header.sortIndicatorOrder()) == (0, Qt.DescendingOrder)
    page._on_header_clicked(2) # customer: A-Z first
    assert page.model.sort_state == (2, Qt.AscendingOrder)
    page._on_header_clicked(2)
    assert page.model.sort_state == (2, Qt.DescendingOrder)
    page._on_header_clicked(3) # amount: largest first
    assert page.model.sort_state == (3, Qt.DescendingOrder) and header.sortIndicatorOrder() == Qt.DescendingOrder
