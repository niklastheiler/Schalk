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
