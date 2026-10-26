"""German texts for the few English strings qfluentwidgets shows (it ships no German translation)."""
from PySide6.QtCore import QCoreApplication, QTranslator

GERMAN = {
    "January": "Januar", "February": "Februar", "March": "März", "April": "April", "May": "Mai", "June": "Juni",
    "July": "Juli", "August": "August", "September": "September", "October": "Oktober", "November": "November",
    "December": "Dezember", "month": "Monat", "day": "Tag", "year": "Jahr",
}


class GermanTranslator(QTranslator):
    def translate(self, context, source_text, disambiguation=None, n=-1):
        # None (not "") for unknown texts: Qt then keeps the original text instead of showing nothing
        return GERMAN.get(source_text)

    def isEmpty(self) -> bool:
        return False


def install_german_translations(app: QCoreApplication) -> QTranslator:
    translator = GermanTranslator(app)
    app.installTranslator(translator)
    return translator
