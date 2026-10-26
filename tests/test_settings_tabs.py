from src.version import APP_AUTHOR, APP_VERSION


def test_settings_tabs_and_about(window):
    settings = window.settings_interface
    assert [item.text() for item in settings.pivot.items.values()] == [
        "Firmendaten", "Bankdaten && Zahlungsziel", "Sicherheit && GoBD"]
    assert settings.paymentTermsSpin.window() is window and "iban" in settings.edits
    assert APP_VERSION in settings.aboutLabel.text() and APP_AUTHOR in settings.aboutLabel.text()
