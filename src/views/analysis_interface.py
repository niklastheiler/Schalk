import math
from datetime import datetime
from PySide6.QtCharts import QCategoryAxis, QChart, QChartView, QLineSeries
from PySide6.QtCore import QMargins, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget
from qfluentwidgets import CardWidget, ComboBox, SubtitleLabel
from src.utils.signal_bus import SignalBus
from src.views.common import style_scrollbars

MONTH_NAMES = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]


def _nice_step(value_range: float) -> float:
    if value_range <= 0:
        return 100
    magnitude = 10 ** math.floor(math.log10(value_range / 5))
    for factor in (1, 2, 5, 10):
        if value_range / (factor * magnitude) <= 10:
            return factor * magnitude
    return 10 * magnitude


class ChartCard(CardWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(SubtitleLabel(title, self))
        self.chart = QChart()
        self.chart.setBackgroundVisible(False)
        self.chart.layout().setContentsMargins(0, 0, 0, 0)
        self.chart.setMargins(QMargins(0, 0, 0, 0))
        self.chartView = QChartView(self.chart, self)
        self.chartView.setRenderHint(QPainter.Antialiasing)
        self.chartView.setStyleSheet("background: transparent;")
        self.chartView.setMinimumHeight(380)
        layout.addWidget(self.chartView)

    def setup_chart(self, series_data: dict, colors: dict):
        self.chart.removeAllSeries()
        for axis in self.chart.axes():
            self.chart.removeAxis(axis)

        axis_x = QCategoryAxis()
        axis_x.setLabelsPosition(QCategoryAxis.AxisLabelsPositionOnValue)
        for i, name in enumerate(MONTH_NAMES):
            axis_x.append(name, i + 1)
        axis_x.setRange(1, 12)

        values = [v for data in series_data.values() for v in data] or [0]
        min_val, max_val = min(0, min(values)), max(values)
        for name, data in series_data.items():
            series = QLineSeries()
            series.setName(name)
            pen = QPen(QColor(colors.get(name, "#000000")))
            pen.setWidth(3)
            series.setPen(pen)
            for month, value in enumerate(data, 1):
                series.append(month, value)
            self.chart.addSeries(series)

        step = _nice_step(max_val - min_val)
        low = math.floor(min_val / step) * step
        high = max(math.ceil(max_val / step) * step, low + step)
        axis_y = QCategoryAxis()
        axis_y.setLabelsPosition(QCategoryAxis.AxisLabelsPositionOnValue)
        axis_y.setRange(low, high)
        for i in range(int(round((high - low) / step)) + 1):
            value = low + i * step
            axis_y.append(f"{value:,.0f} €".replace(",", "."), value)

        self.chart.addAxis(axis_x, Qt.AlignBottom)
        self.chart.addAxis(axis_y, Qt.AlignLeft)
        for series in self.chart.series():
            series.attachAxis(axis_x)
            series.attachAxis(axis_y)


class AnalysisInterface(QWidget):
    def __init__(self, db_controller, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("AnalysisInterface")
        self.db_controller = db_controller
        self._dirty = True
        bus = SignalBus.get()
        for signal in (bus.invoicesChanged, bus.cashbookChanged, bus.incomingInvoicesChanged):
            signal.connect(self._mark_dirty)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        style_scrollbars(scroll)
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(36, 36, 36, 36)
        layout.setSpacing(24)

        header = QHBoxLayout()
        header.addWidget(SubtitleLabel("Auswertung", self))
        header.addStretch(1)
        self.yearCombo = ComboBox(self)
        self.yearCombo.setFixedWidth(150)
        self.yearCombo.currentTextChanged.connect(self.load_data)
        header.addWidget(self.yearCombo)
        layout.addLayout(header)

        self.invoiceCard = ChartCard("Rechnungsübersicht (brutto)", self)
        self.cashbookCard = ChartCard("Kassenbestand (Monatsende)", self)
        layout.addWidget(self.invoiceCard)
        layout.addWidget(self.cashbookCard)
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

    def _mark_dirty(self):
        self._dirty = True
        if self.isVisible():
            self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        if self._dirty:
            self.refresh()

    def refresh(self):
        self._dirty = False
        c = self.db_controller
        years = {datetime.now().year}
        years.update(i.invoice_date.year for i in c.get_invoices())
        years.update(i.date.year for i in c.get_incoming_invoices())
        years.update(e.entry_date.year for e in c.get_cashbook_entries())
        current = self.yearCombo.currentText()
        self.yearCombo.blockSignals(True)
        self.yearCombo.clear()
        self.yearCombo.addItems([str(y) for y in sorted(years, reverse=True)])
        self.yearCombo.setCurrentText(current if current in [str(y) for y in years] else str(datetime.now().year))
        self.yearCombo.blockSignals(False)
        self.load_data()

    def load_data(self):
        if not self.yearCombo.currentText():
            return
        year = int(self.yearCombo.currentText())
        c = self.db_controller

        paid = [0.0] * 12
        for invoice in c.get_invoices():
            if invoice.status == "Bezahlt" and invoice.invoice_date.year == year:
                paid[invoice.invoice_date.month - 1] += invoice.gross_amount
        supplier, other = [0.0] * 12, [0.0] * 12
        for invoice in c.get_incoming_invoices(include_cancelled=False):
            if invoice.date.year == year:
                (supplier if invoice.invoice_type == "Lieferant" else other)[invoice.date.month - 1] += invoice.amount

        # Running cash balance at the end of each month
        start_balance = 0.0
        changes = [0.0] * 12
        for entry in c.get_cashbook_entries():
            signed = c.cashbook_signed_amount(entry)
            if entry.entry_date.year < year:
                start_balance += signed
            elif entry.entry_date.year == year:
                changes[entry.entry_date.month - 1] += signed
        balance, running = [], start_balance
        for change in changes:
            running += change
            balance.append(running)

        self.invoiceCard.setup_chart(
            {"Kundenrechnungen (Bezahlt)": paid, "Lieferantenrechnungen": supplier, "Sonstige Rechnungen": other},
            {"Kundenrechnungen (Bezahlt)": "#009688", "Lieferantenrechnungen": "#F44336", "Sonstige Rechnungen": "#FF9800"})
        self.cashbookCard.setup_chart({"Kassenbestand": balance}, {"Kassenbestand": "#2196F3"})
