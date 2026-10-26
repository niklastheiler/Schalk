from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QScrollArea
from PySide6.QtCore import Qt, QMargins
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtCharts import QChart, QChartView, QLineSeries, QCategoryAxis
from qfluentwidgets import SubtitleLabel, ComboBox, CardWidget
from datetime import datetime
from src.utils.signal_bus import SignalBus


class ChartCard(CardWidget):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(16, 16, 16, 16)
        
        self.titleLabel = SubtitleLabel(title, self)
        self.vBoxLayout.addWidget(self.titleLabel)
        
        self.chart = QChart()
        self.chart.setAnimationOptions(QChart.SeriesAnimations)
        self.chart.setBackgroundVisible(False)
        self.chart.layout().setContentsMargins(0, 0, 0, 0)
        self.chart.setMargins(QMargins(0, 0, 0, 0))
        
        self.chartView = QChartView(self.chart, self)
        self.chartView.setRenderHint(QPainter.Antialiasing)
        self.chartView.setStyleSheet("background: transparent;")
        self.chartView.setMinimumHeight(400)
        
        self.vBoxLayout.addWidget(self.chartView)
        
    def setup_chart(self, series_data: dict, colors: dict):
        self.chart.removeAllSeries()
        
        # Remove old axes
        for axis in self.chart.axes():
            self.chart.removeAxis(axis)
            
        axisX = QCategoryAxis()
        axisX.setLabelsPosition(QCategoryAxis.AxisLabelsPositionOnValue)
        months = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]
        for i, m in enumerate(months):
            axisX.append(m, i + 1)
        axisX.setRange(1, 12)
        
        max_val = 0
        min_val = 0
        
        for name, data_list in series_data.items():
            series = QLineSeries()
            series.setName(name)
            pen = QPen(QColor(colors.get(name, "#000000")))
            pen.setWidth(3)
            series.setPen(pen)
            
            for month, val in data_list.items():
                series.append(month, val)
                if val > max_val: max_val = val
                if val < min_val: min_val = val
                    
            self.chart.addSeries(series)
            
        axisY = QCategoryAxis()
        axisY.setLabelsPosition(QCategoryAxis.AxisLabelsPositionOnValue)
        
        # Dynamic Y-axis steps
        range_val = max_val - min_val
        if range_val <= 1000:
            step = 100
        elif range_val <= 5000:
            step = 500
        elif range_val <= 10000:
            step = 1000
        elif range_val <= 50000:
            step = 5000
        else:
            step = 10000
            
        import math
        min_axis = math.floor(min_val / step) * step if min_val < 0 else 0
        max_axis = math.ceil(max_val / step) * step
        if max_axis == min_axis:
            max_axis = min_axis + step
            
        axisY.setRange(min_axis, max_axis)
        ticks = int((max_axis - min_axis) / step) + 1
        
        for i in range(ticks):
            val = min_axis + i * step
            axisY.append(f"{val} €", val)
        
        self.chart.addAxis(axisX, Qt.AlignBottom)
        self.chart.addAxis(axisY, Qt.AlignLeft)
        
        for series in self.chart.series():
            series.attachAxis(axisX)
            series.attachAxis(axisY)


class AnalysisInterface(QWidget):
    def __init__(self, db_controller, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("AnalysisInterface")
        self.db_controller = db_controller
        self._needs_reload = True
        SignalBus.get().dataChanged.connect(self.mark_dirty)
        self.init_ui()
        
    def init_ui(self):
        self.mainLayout = QVBoxLayout(self)
        self.mainLayout.setContentsMargins(0, 0, 0, 0)
        
        # Scroll Area
        self.scrollArea = QScrollArea(self)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        self.scrollWidget = QWidget()
        self.scrollWidget.setStyleSheet("background: transparent;")
        self.scrollLayout = QVBoxLayout(self.scrollWidget)
        self.scrollLayout.setContentsMargins(36, 36, 36, 36)
        self.scrollLayout.setSpacing(24)
        
        # Header
        headerLayout = QHBoxLayout()
        self.titleLabel = SubtitleLabel("Auswertung", self)
        
        self.yearCombo = ComboBox(self)
        self.yearCombo.setFixedWidth(150)
        self.yearCombo.currentTextChanged.connect(self.load_data)
        
        headerLayout.addWidget(self.titleLabel)
        headerLayout.addStretch(1)
        headerLayout.addWidget(self.yearCombo)
        
        self.scrollLayout.addLayout(headerLayout)
        
        # Charts
        self.invoiceCard = ChartCard("Rechnungsübersicht", self)
        self.cashbookCard = ChartCard("Kassenbuch", self)
        
        self.scrollLayout.addWidget(self.invoiceCard)
        self.scrollLayout.addWidget(self.cashbookCard)
        
        self.scrollArea.setWidget(self.scrollWidget)
        self.mainLayout.addWidget(self.scrollArea)
        
    def mark_dirty(self):
        self._needs_reload = True

    def showEvent(self, event):
        super().showEvent(event)
        self.populate_years()
        self.load_data()
        
    def populate_years(self):
        from src.models.database import Invoice, IncomingInvoice, CashbookEntry
        years = set()
        years.add(datetime.now().year)
        
        with self.db_controller.get_session() as session:
            for inv in session.query(Invoice.invoice_date).all():
                if inv.invoice_date:
                    years.add(inv.invoice_date.year)
            for inv in session.query(IncomingInvoice.date).all():
                if inv.date:
                    years.add(inv.date.year)
            for cb in session.query(CashbookEntry.entry_date).all():
                if cb.entry_date:
                    years.add(cb.entry_date.year)
                    
        current = self.yearCombo.currentText()
        self.yearCombo.blockSignals(True)
        self.yearCombo.clear()
        for y in sorted(list(years), reverse=True):
            self.yearCombo.addItem(str(y))
            
        if current in [str(y) for y in years]:
            self.yearCombo.setCurrentText(current)
        else:
            self.yearCombo.setCurrentText(str(datetime.now().year))
        self.yearCombo.blockSignals(False)

    def load_data(self):
        year_str = self.yearCombo.currentText()
        if not year_str:
            return
        year = int(year_str)
        
        from src.models.database import Invoice, IncomingInvoice, CashbookEntry
        
        # Init dicts
        inv_out = {m: 0.0 for m in range(1, 13)}
        inv_lief = {m: 0.0 for m in range(1, 13)}
        inv_sonst = {m: 0.0 for m in range(1, 13)}
        
        cb_balance = {m: 0.0 for m in range(1, 13)}
        
        with self.db_controller.get_session() as session:
            # 1. Outgoing Invoices (Only Paid)
            for inv in session.query(Invoice.invoice_date, Invoice.gross_amount).filter(Invoice.status == "Bezahlt").all():
                if inv.invoice_date and inv.invoice_date.year == year:
                    inv_out[inv.invoice_date.month] += inv.gross_amount
                    
            # 2. Incoming Invoices
            for inv in session.query(IncomingInvoice.date, IncomingInvoice.amount, IncomingInvoice.invoice_type).filter(IncomingInvoice.cancelled_at == None).all():
                if inv.date and inv.date.year == year:
                    if inv.invoice_type == "Lieferant":
                        inv_lief[inv.date.month] += inv.amount
                    elif inv.invoice_type == "Sonstige":
                        inv_sonst[inv.date.month] += inv.amount
                        
            # 3. Cashbook Balance (Kassenbestand)
            running_balance = 0.0
            
            # Start balance from before the selected year
            from datetime import datetime
            for cb in session.query(CashbookEntry.amount, CashbookEntry.entry_type).filter(CashbookEntry.entry_date < datetime(year, 1, 1)).all():
                if cb.entry_type == "Einnahme":
                    running_balance += cb.amount
                elif cb.entry_type in ["Ausgabe", "Barentnahme Privat", "Barentnahme Firma"]:
                    running_balance -= cb.amount
            
            # Add running balance up to the end of each month
            for m in range(1, 13):
                if m == 12:
                    end_date = datetime(year+1, 1, 1)
                else:
                    end_date = datetime(year, m+1, 1)
                start_date = datetime(year, m, 1)
                
                for cb in session.query(CashbookEntry.amount, CashbookEntry.entry_type).filter(CashbookEntry.entry_date >= start_date, CashbookEntry.entry_date < end_date).all():
                    if cb.entry_type == "Einnahme":
                        running_balance += cb.amount
                    elif cb.entry_type in ["Ausgabe", "Barentnahme Privat", "Barentnahme Firma"]:
                        running_balance -= cb.amount
                
                cb_balance[m] = running_balance
                        
        # Setup Chart 1
        self.invoiceCard.setup_chart({
            "Kundenrechnungen (Bezahlt)": inv_out,
            "Lieferantenrechnungen": inv_lief,
            "Sonstige Rechnungen": inv_sonst
        }, {
            "Kundenrechnungen (Bezahlt)": "#009688", # Teal
            "Lieferantenrechnungen": "#F44336", # Red
            "Sonstige Rechnungen": "#FF9800" # Orange
        })
        
        # Setup Chart 2
        self.cashbookCard.setup_chart({
            "Kassenbestand": cb_balance
        }, {
            "Kassenbestand": "#2196F3" # Blue
        })
