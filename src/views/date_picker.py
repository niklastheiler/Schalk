from PySide6.QtCore import QSize, QDate
from PySide6.QtGui import QFontMetrics
from qfluentwidgets import DatePicker


class GermanDatePicker(DatePicker):
    """DatePicker in German order: Tag – Monat – Jahr (month names come from the German translator)."""

    DD_MM_YYYY = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDateFormat(self.DD_MM_YYYY)

    # The columns have fixed widths; without this a layout squeezes the picker and the next field covers the year
    def sizeHint(self):
        hint = super().sizeHint()
        return QSize(max(hint.width(), sum(column.width() for column in self.columns)), hint.height())

    def minimumSizeHint(self):
        return self.sizeHint()

    def setDateFormat(self, format: int):
        if format != self.DD_MM_YYYY:
            return super().setDateFormat(format)
        self.clearColumns()
        year = QDate.currentDate().year()
        self.dateFormat = format
        self.dayIndex, self.monthIndex, self.yearIndex = 0, 1, 2
        self.addColumn(self.DAY, range(1, 32), 80, formatter=self.dayFormatter())
        self.addColumn(self.MONTH, range(1, 13), 80, formatter=self.monthFormatter())
        self.addColumn(self.YEAR, range(year - 100, year + 101), 80, formatter=self.yearFormatter())
        self.setColumnWidth(self.monthIndex, self._monthColumnWidth())

    def _monthColumnWidth(self):
        # Room for the longest German month name ("September") plus the padding of the button;
        # the tight width of the library cut off names like "November"
        names = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember")
        # Measured with the font of the month button: it comes from the style sheet, which is applied
        # only when the button is polished, so this is done first
        button = self.columns[self.monthIndex] if len(self.columns) > self.monthIndex else self
        button.ensurePolished()
        metrics = QFontMetrics(button.font())
        widest = max(metrics.boundingRect(name).width() for name in names)
        return max(widest + 56, 130)

    def showEvent(self, event):
        super().showEvent(event)
        # The final font (and display scaling) is known only now
        self.setColumnWidth(self.monthIndex, self._monthColumnWidth())

    def panelInitialValue(self):
        if any(self.value()):
            return self.value()
        today = QDate.currentDate()
        return [self.encodeValue(self.dayIndex, today.day()), self.encodeValue(self.monthIndex, today.month()),
                self.encodeValue(self.yearIndex, today.year())]
