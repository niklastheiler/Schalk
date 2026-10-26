"""
Building blocks shared by all pages: virtual table model (no widgets per row, so tens of
thousands of records stay fluid), filter proxy, list page base class and message helpers.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, List, Optional
from PySide6.QtCore import QAbstractTableModel, QItemSelection, QItemSelectionModel, QModelIndex, QSortFilterProxyModel, Qt, QTimer
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QAbstractItemView, QHBoxLayout, QHeaderView, QVBoxLayout, QWidget
from qfluentwidgets import (ComboBox, InfoBar, InfoBarPosition, MessageBox, PrimaryPushButton, PushButton,
                            RoundMenu, SearchLineEdit, SubtitleLabel, TableView)

RECORD_ROLE = Qt.UserRole + 1

COLOR_GREEN = QColor("#D3EBCD")
COLOR_RED = QColor("#FFD6D6")
COLOR_YELLOW = QColor("#FFF5C2")
COLOR_GREY = QColor("#E6E6E6")

MONTHS = ["Alle Monate"] + [f"{m:02d}" for m in range(1, 13)]


def fmt_money(value: float) -> str:
    return f"{value:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_date(value: Optional[datetime]) -> str:
    # Noticeably faster than strftime when formatting tens of thousands of rows
    return f"{value.day:02d}.{value.month:02d}.{value.year}" if value else ""


# --- Messages ---
def notify_success(parent, title: str, text: str = "", duration: int = 3000):
    InfoBar.success(title, text, orient=Qt.Horizontal, isClosable=True, position=InfoBarPosition.TOP,
                    duration=duration, parent=parent.window())


def notify_error(parent, title: str, text: str = "", duration: int = 6000):
    InfoBar.error(title, text, orient=Qt.Horizontal, isClosable=True, position=InfoBarPosition.TOP,
                  duration=duration, parent=parent.window())


def notify_warning(parent, title: str, text: str = "", duration: int = 5000):
    InfoBar.warning(title, text, orient=Qt.Horizontal, isClosable=True, position=InfoBarPosition.TOP,
                    duration=duration, parent=parent.window())


def confirm(parent, title: str, text: str) -> bool:
    box = MessageBox(title, text, parent.window())
    box.yesButton.setText("Ja")
    box.cancelButton.setText("Nein")
    return bool(box.exec())


def show_message(parent, title: str, text: str):
    box = MessageBox(title, text, parent.window())
    box.cancelButton.hide()
    box.exec()


# --- Table model ---
@dataclass
class Column:
    title: str
    text: Callable[[Any], str]
    sort: Optional[Callable[[Any], Any]] = None
    width: Optional[int] = None # None = stretch
    align: Qt.AlignmentFlag = Qt.AlignLeft | Qt.AlignVCenter


class RecordTableModel(QAbstractTableModel):
    """Read-only model over a list of records; texts are computed lazily for visible cells only."""

    def __init__(self, columns: List[Column], row_color: Callable[[Any], Optional[QColor]] = None, parent=None):
        super().__init__(parent)
        self.columns = columns
        self.row_color = row_color
        self._rows: list = []
        self._texts: dict = {}
        self._search: dict = {}
        self._sort_column = None
        self._sort_order = Qt.AscendingOrder

    def set_rows(self, rows: list):
        self.beginResetModel()
        self._rows = self._sorted(rows)
        # Texts are cached per record object: changed records arrive as new objects from the
        # controller, unchanged ones keep their cached texts across refreshes and re-sorting
        self._texts = {r: self._texts[r] for r in self._rows if r in self._texts}
        self._search = {r: self._search[r] for r in self._rows if r in self._search}
        self.endResetModel()

    def sort(self, column: int, order=Qt.AscendingOrder):
        # Sorting in Python with a key function is a single C-level pass; sorting through
        # QSortFilterProxyModel would call back into Python for every comparison
        self._sort_column, self._sort_order = column, order
        self.set_rows(self._rows)

    def _sorted(self, rows) -> list:
        if self._sort_column is None:
            return list(rows)
        column = self.columns[self._sort_column]
        key = column.sort or column.text

        def safe_key(record):
            value = key(record)
            return (value is None, value if value is not None else 0)
        try:
            return sorted(rows, key=safe_key, reverse=self._sort_order == Qt.DescendingOrder)
        except TypeError:
            return sorted(rows, key=lambda r: str(key(r)), reverse=self._sort_order == Qt.DescendingOrder)

    def record(self, row: int):
        return self._rows[row]

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.columns[section].title
        return None

    def _record_texts(self, record) -> list:
        texts = self._texts.get(record)
        if texts is None:
            texts = self._texts[record] = [column.text(record) or "" for column in self.columns]
        return texts

    def text(self, row: int, col: int) -> str:
        return self._record_texts(self._rows[row])[col]

    def search_text(self, row: int) -> str:
        record = self._rows[row]
        text = self._search.get(record)
        if text is None:
            text = self._search[record] = " ".join(self._record_texts(record)).lower()
        return text

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        if role == Qt.DisplayRole:
            return self.text(row, col)
        if role == Qt.TextAlignmentRole:
            return int(self.columns[col].align)
        if role == Qt.BackgroundRole and self.row_color:
            color = self.row_color(self._rows[row])
            return QBrush(color) if color else None
        if role == RECORD_ROLE:
            return self._rows[row]
        return None


class RecordFilterProxy(QSortFilterProxyModel):
    def __init__(self, date_of: Callable[[Any], Optional[datetime]] = None, parent=None):
        super().__init__(parent)
        self.date_of = date_of
        self.year = None
        self.month = None
        self.search = ""
        self.predicate: Optional[Callable[[Any], bool]] = None

    def set_filters(self, year=None, month=None, search=""):
        self.beginFilterChange()
        self.year, self.month, self.search = year, month, search.lower().strip()
        self.endFilterChange(QSortFilterProxyModel.Direction.Rows)

    def filterAcceptsRow(self, source_row, source_parent):
        model: RecordTableModel = self.sourceModel()
        record = model.record(source_row)
        if self.predicate and not self.predicate(record):
            return False
        if self.date_of and (self.year or self.month):
            value = self.date_of(record)
            if not value or (self.year and value.year != self.year) or (self.month and value.month != self.month):
                return False
        return not self.search or self.search in model.search_text(source_row)


# --- List page ---
class ListPage(QWidget):
    """
    Header (title, year/month filter, search, buttons) and a virtual table.
    Subclasses implement records() and optionally fill_context_menu() / on_activated().
    The table is refreshed lazily: changes while the page is hidden only mark it dirty.
    """

    def __init__(self, title: str, columns: List[Column], change_signals=(), date_of=None, row_color=None, parent=None):
        super().__init__(parent)
        self._dirty = True
        self._refresh_scheduled = False
        self.date_of = date_of

        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(24, 24, 24, 24)

        self.headerLayout = QHBoxLayout()
        self.titleLabel = SubtitleLabel(title, self)
        self.headerLayout.addWidget(self.titleLabel)
        self.headerLayout.addStretch(1)

        if date_of:
            self.yearCombo = ComboBox(self)
            self.yearCombo.addItem("Alle Jahre")
            self.yearCombo.setFixedWidth(130)
            self.yearCombo.currentTextChanged.connect(self.apply_filters)
            self.monthCombo = ComboBox(self)
            self.monthCombo.addItems(MONTHS)
            self.monthCombo.setFixedWidth(130)
            self.monthCombo.currentTextChanged.connect(self.apply_filters)
            self.headerLayout.addWidget(self.yearCombo)
            self.headerLayout.addWidget(self.monthCombo)

        self.searchEdit = SearchLineEdit(self)
        self.searchEdit.setPlaceholderText("Suchen...")
        self.searchEdit.setFixedWidth(220)
        self._search_timer = QTimer(self, singleShot=True, interval=200)
        self._search_timer.timeout.connect(self.apply_filters)
        self.searchEdit.textChanged.connect(lambda: self._search_timer.start())
        self.headerLayout.addWidget(self.searchEdit)
        self.vBoxLayout.addLayout(self.headerLayout)

        self.model = RecordTableModel(columns, row_color, self)
        self.proxy = RecordFilterProxy(date_of, self)
        self.proxy.setSourceModel(self.model)

        self.table = TableView(self)
        self.table.setModel(self.proxy)
        header = self.table.horizontalHeader()
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.setSortIndicator(-1, Qt.AscendingOrder)
        header.sortIndicatorChanged.connect(self.model.sort)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(38)
        for i, column in enumerate(columns):
            if column.width:
                header.setSectionResizeMode(i, QHeaderView.Interactive)
                self.table.setColumnWidth(i, column.width)
            else:
                header.setSectionResizeMode(i, QHeaderView.Stretch)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.doubleClicked.connect(lambda index: self.on_activated(index.data(RECORD_ROLE)))
        self.vBoxLayout.addWidget(self.table)

        for signal in change_signals:
            signal.connect(self.mark_dirty)

    # --- To implement ---
    def records(self) -> list:
        raise NotImplementedError

    def fill_context_menu(self, menu: RoundMenu, record):
        pass

    def on_activated(self, record):
        pass

    # --- Helpers for subclasses ---
    def add_header_button(self, text: str, slot, primary: bool = False):
        button = (PrimaryPushButton if primary else PushButton)(text, self)
        button.clicked.connect(slot)
        self.headerLayout.addWidget(button)
        return button

    def selected_records(self) -> list:
        return [index.data(RECORD_ROLE) for index in self.table.selectionModel().selectedRows()]

    def selected_record(self):
        records = self.selected_records()
        return records[0] if records else None

    def visible_records(self) -> list:
        return [self.proxy.index(r, 0).data(RECORD_ROLE) for r in range(self.proxy.rowCount())]

    # --- Refresh ---
    def mark_dirty(self):
        self._dirty = True
        if self.isVisible() and not self._refresh_scheduled:
            # Coalesce bursts of change signals into one refresh
            self._refresh_scheduled = True
            QTimer.singleShot(0, self.refresh)

    def showEvent(self, event):
        super().showEvent(event)
        if self._dirty:
            self.refresh()

    def refresh(self):
        self._refresh_scheduled = False
        self._dirty = False
        records = self.records()
        selected_ids = {getattr(r, "id", None) for r in self.selected_records()}
        self.model.set_rows(records)
        if self.date_of:
            self._update_years(records)
        self.apply_filters()
        if selected_ids:
            self._reselect(selected_ids)
        self.on_refreshed(records)

    def on_refreshed(self, records: list):
        pass

    def _update_years(self, records):
        years = sorted({d.year for d in (self.date_of(r) for r in records) if d}, reverse=True)
        current = self.yearCombo.currentText()
        self.yearCombo.blockSignals(True)
        self.yearCombo.clear()
        self.yearCombo.addItem("Alle Jahre")
        self.yearCombo.addItems([str(y) for y in years])
        self.yearCombo.setCurrentText(current if current in [str(y) for y in years] else "Alle Jahre")
        self.yearCombo.blockSignals(False)

    def apply_filters(self):
        year = month = None
        if self.date_of:
            year_text, month_text = self.yearCombo.currentText(), self.monthCombo.currentText()
            year = int(year_text) if year_text.isdigit() else None
            month = int(month_text) if month_text.isdigit() else None
        self.proxy.set_filters(year, month, self.searchEdit.text())

    def _reselect(self, ids: set):
        selection = QItemSelection()
        last_column = self.proxy.columnCount() - 1
        for r in range(self.proxy.rowCount()):
            if getattr(self.proxy.index(r, 0).data(RECORD_ROLE), "id", None) in ids:
                selection.select(self.proxy.index(r, 0), self.proxy.index(r, last_column))
        self.table.selectionModel().select(selection, QItemSelectionModel.ClearAndSelect)

    def _show_context_menu(self, pos):
        index = self.table.indexAt(pos)
        if not index.isValid():
            return
        if not self.table.selectionModel().isRowSelected(index.row(), index.parent()):
            self.table.selectRow(index.row())
        menu = RoundMenu(parent=self.table)
        self.fill_context_menu(menu, index.data(RECORD_ROLE))
        if menu.actions():
            menu.exec(self.table.viewport().mapToGlobal(pos))
