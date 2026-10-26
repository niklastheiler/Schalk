from PySide6.QtCore import QDate
from qfluentwidgets import DatePicker


class GermanDatePicker(DatePicker):
    """DatePicker in German order: Tag – Monat – Jahr (month names come from the German translator)."""

    DD_MM_YYYY = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDateFormat(self.DD_MM_YYYY)

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

    def panelInitialValue(self):
        if any(self.value()):
            return self.value()
        today = QDate.currentDate()
        return [self.encodeValue(self.dayIndex, today.day()), self.encodeValue(self.monthIndex, today.month()),
                self.encodeValue(self.yearIndex, today.year())]
