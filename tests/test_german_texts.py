from PySide6.QtCore import QDate
from PySide6.QtWidgets import QPushButton
from qfluentwidgets import DatePicker
from src.utils.translations import install_german_translations


def test_date_picker_shows_german_month(qapp):
    translator = install_german_translations(qapp)
    try:
        picker = DatePicker()
        picker.setDate(QDate(2026, 10, 9))
        assert "Oktober" in [b.text() for b in picker.findChildren(QPushButton)]
    finally:
        qapp.removeTranslator(translator)


def test_security_tab_shows_ampersand(window):
    pivot = window.settings_interface.pivot
    assert any(item.text() == "Sicherheit && GoBD" for item in pivot.items.values())


def test_date_picker_in_german_order(qapp):
    from src.views.date_picker import GermanDatePicker
    translator = install_german_translations(qapp)
    try:
        picker = GermanDatePicker()
        picker.show()
        picker.setDate(QDate(2026, 10, 9))
        assert [b.text() for b in picker.findChildren(QPushButton)][:3] == ["9", "Oktober", "2026"]
        assert picker.panelInitialValue() == ["9", "Oktober", "2026"]
        # Choosing a value in the panel yields the right date
        picker._onConfirmed(["31", "Dezember", "2025"])
        assert picker.date == QDate(2025, 12, 31)
    finally:
        qapp.removeTranslator(translator)
