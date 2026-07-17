from qfluentwidgets import ComboBox, InfoBar, InfoBarPosition, PrimaryPushButton, PushButton, SubtitleLabel, TableWidget
from PySide6.QtWidgets import QHBoxLayout, QHeaderView, QTableWidgetItem, QVBoxLayout, QWidget
from PySide6.QtCore import Qt
from src.controllers.db_controller import DBController
import os
from src.utils.signal_bus import SignalBus


class ReminderInterface(QWidget):
    def __init__(self, db_controller: DBController, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("ReminderInterface")
        self.db_controller = db_controller
        self.init_ui()
        self._needs_reload = True
        SignalBus.get().dataChanged.connect(self.mark_dirty)

    def init_ui(self):
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(24, 24, 24, 24)
        
        # Header
        headerLayout = QHBoxLayout()
        self.titleLabel = SubtitleLabel("Mahnungen", self)
        headerLayout.addWidget(self.titleLabel)
        headerLayout.addStretch(1)
        self.vBoxLayout.addLayout(headerLayout)
        
        # Table
        self.table = TableWidget(self)
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(['Datum', 'Rechnungsnummer', 'Kunde', 'Betrag', 'Zahlungsziel', 'Status', 'Aktion'])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.table.setColumnWidth(0, 100)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.table.setColumnWidth(1, 150)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Interactive)
        self.table.setColumnWidth(3, 120)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Interactive)
        self.table.setColumnWidth(4, 100)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Interactive)
        self.table.setColumnWidth(5, 160)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Interactive)
        self.table.setColumnWidth(6, 260)

        # Performance optimization for scrolling with setCellWidget
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(50)
        from PySide6.QtWidgets import QAbstractItemView
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.itemDoubleClicked.connect(self.on_item_double_clicked)
        
        self.vBoxLayout.addWidget(self.table)
        self.load_data()

    def show_context_menu(self, pos):
        item = self.table.itemAt(pos)
        if not item: return
        row = item.row()
        inv_id_item = self.table.item(row, 0)
        if not inv_id_item: return
        inv_id = inv_id_item.data(Qt.UserRole)
        
        inv = self.db_controller.get_invoice(inv_id)
        if not inv: return

        from qfluentwidgets import RoundMenu, Action
        from qfluentwidgets import FluentIcon as FIF
        from datetime import datetime
        now = datetime.now()
        
        menu = RoundMenu(parent=self.table)
        
        # Payment action
        if inv.status != "Bezahlt":
            pay_action = Action(FIF.ACCEPT, "Als Bezahlt markieren", self)
            pay_action.triggered.connect(lambda: self.mark_as_paid(inv_id))
            menu.addAction(pay_action)
            
        # Reminder action
        inv_date = inv.invoice_date.replace(tzinfo=None) if inv.invoice_date else now
        last_rem_date = inv.last_reminder_date.replace(tzinfo=None) if inv.last_reminder_date else inv_date
        rem_delta = now - last_rem_date
        
        can_remind = False
        remind_text = "Mahnung erstellen"
        if inv.status != "Bezahlt":
            if inv.reminder_level == 0:
                remind_text = "1. Mahnung erstellen"
                can_remind = True
            elif inv.reminder_level == 1:
                if rem_delta.days > 14:
                    remind_text = "2. Mahnung erstellen"
                    can_remind = True
            elif inv.reminder_level == 2:
                if rem_delta.days > 14:
                    remind_text = "3. Mahnung erstellen"
                    can_remind = True

        if can_remind:
            remind_action = Action(FIF.MAIL, remind_text, self)
            remind_action.triggered.connect(lambda: self.generate_reminder(inv_id, inv.reminder_level + 1))
            menu.addAction(remind_action)
            
        # View action
        view_action = Action(FIF.DOCUMENT, "Rechnung anzeigen", self)
        view_action.triggered.connect(lambda: self.show_invoice(inv_id))
        menu.addAction(view_action)
        
        # Print action
        if inv.reminder_level > 0:
            print_action = Action(FIF.PRINT, "Drucken", self)
            print_action.triggered.connect(lambda: self.generate_reminder(inv_id, inv.reminder_level, print_only=True))
            menu.addAction(print_action)
            
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def on_item_double_clicked(self, item):
        row = item.row()
        inv_id_item = self.table.item(row, 0)
        if not inv_id_item: return
        inv_id = inv_id_item.data(Qt.UserRole)
        self.show_invoice(inv_id)

    def mark_dirty(self):
        self._needs_reload = True

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, '_needs_reload', True):
            self.load_data()
            self._needs_reload = False

    def load_data(self):
        v_scroll = self.table.verticalScrollBar().value()
        h_scroll = self.table.horizontalScrollBar().value()

        self.table.setRowCount(0)
        invoices = self.db_controller.get_invoices()
        
        from datetime import datetime, timedelta
        now = datetime.now()
        
        try:
            payment_terms = int(self.db_controller.get_setting("payment_terms_days") or 14)
        except ValueError:
            payment_terms = 14
        
        # Filter for open or overdue
        overdue_invoices = []
        for inv in invoices:
            inv_date = inv.invoice_date.replace(tzinfo=None) if inv.invoice_date else now
            delta = now - inv_date
            if inv.status == "Überfällig":
                overdue_invoices.append(inv)
            elif inv.status in ["Entwurf", "Offen"]:
                if delta.days > payment_terms:
                    overdue_invoices.append(inv)
            elif inv.reminder_level > 0 and inv.status not in ["Archiviert", "Bezahlt"]:
                overdue_invoices.append(inv)
        
        for i, inv in enumerate(overdue_invoices):
            self.table.insertRow(i)
            self.table.setRowHeight(i, 50)
            # Date calculation for row colors
            inv_date = inv.invoice_date.replace(tzinfo=None) if inv.invoice_date else now
            delta = now - inv_date
            
            row_color = None
            if inv.status == "Überfällig":
                if delta.days > payment_terms:
                    row_color = "#FFD6D6" # Red
                elif delta.days > payment_terms - 7:
                    row_color = "#FFF5C2" # Yellow
                else:
                    row_color = "#FFD6D6" # Red (Since it was manually set to Überfällig, highlight it)
            elif inv.status in ["Entwurf", "Offen"]:
                if delta.days > payment_terms:
                    row_color = "#FFD6D6" # Red
                elif delta.days > payment_terms - 7:
                    row_color = "#FFF5C2" # Yellow
            elif inv.status == "Bezahlt":
                row_color = "#D6FFD6" # Light Green
            
            def create_item(text):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                item.setData(Qt.UserRole, inv.id)
                if row_color:
                    from PySide6.QtGui import QBrush, QColor
                    item.setBackground(QBrush(QColor(row_color)))
                return item

            self.table.setItem(i, 0, create_item(inv.invoice_date.strftime("%d.%m.%Y")))
            self.table.setItem(i, 1, create_item(inv.invoice_number))
            customer_name = inv.customer.company_name if inv.customer.company_name else f"{inv.customer.first_name} {inv.customer.last_name}"
            self.table.setItem(i, 2, create_item(customer_name))
            self.table.setItem(i, 3, create_item(f"{inv.gross_amount:.2f} €"))
            
            due_date = inv.invoice_date + timedelta(days=payment_terms)
            self.table.setItem(i, 4, create_item(due_date.strftime("%d.%m.%Y")))
            
            status_combo = ComboBox()
            status_combo.addItems(["Entwurf", "Offen", "Bezahlt", "Überfällig"])
            status_combo.setCurrentText(inv.status)
            
            status_combo.currentTextChanged.connect(lambda text, inv_id=inv.id: self.change_invoice_status(inv_id, text))
            
            status_combo.setFocusPolicy(Qt.ClickFocus)
            status_combo.setFixedSize(130, 32)
            from PySide6.QtWidgets import QWidget, QHBoxLayout
            container = QWidget()
            container.setStyleSheet("background-color: transparent;")
            layout = QHBoxLayout(container)
            layout.setContentsMargins(0, 0, 20, 0)
            layout.setAlignment(Qt.AlignCenter)
            layout.addWidget(status_combo)
            self.table.setCellWidget(i, 5, container)
            
            from qfluentwidgets import PrimaryPushButton, PushButton
            
            inv_date = inv.invoice_date.replace(tzinfo=None) if inv.invoice_date else now
            last_rem_date = inv.last_reminder_date.replace(tzinfo=None) if inv.last_reminder_date else inv_date
            rem_delta = now - last_rem_date
            
            can_remind = False
            remind_text = "Mahnung erstellen"
            if inv.status != "Bezahlt":
                if inv.reminder_level == 0:
                    remind_text = "1. Mahnung erstellen"
                    can_remind = True
                elif inv.reminder_level == 1:
                    remind_text = "2. Mahnung erstellen"
                    if rem_delta.days >= 14:
                        can_remind = True
                elif inv.reminder_level >= 2:
                    remind_text = "3. Mahnung erstellen"
                    if rem_delta.days >= 14:
                        can_remind = True
            
            action_btn = PrimaryPushButton(remind_text) if can_remind else PushButton(remind_text)
            
            # Always connect the signal so it works if enabled later
            action_btn.clicked.connect(lambda checked=False, inv_id=inv.id, level=inv.reminder_level+1, btn=action_btn: self.generate_reminder(inv_id, level, btn))
            
            if not can_remind:
                action_btn.setEnabled(False)
                if inv.status != "Bezahlt" and inv.reminder_level > 0:
                    days_left = 14 - rem_delta.days
                    if days_left > 0:
                        day_str = "Tag" if days_left == 1 else "Tagen"
                        action_btn.setText(f"{remind_text} (in {days_left} {day_str})")
                        action_btn.setToolTip(f"Nächste Mahnung in {days_left} {day_str} möglich")
            
            action_btn.setFixedSize(240, 32)
            
            act_container = QWidget()
            act_container.setStyleSheet("background-color: transparent;")
            act_lay = QHBoxLayout(act_container)
            act_lay.setContentsMargins(0, 0, 20, 0)
            act_lay.setAlignment(Qt.AlignCenter)
            act_lay.addWidget(action_btn)
            self.table.setCellWidget(i, 6, act_container)
            

        self.table.verticalScrollBar().setValue(v_scroll)
        self.table.horizontalScrollBar().setValue(h_scroll)

    def change_invoice_status(self, invoice_id, new_status):
        if not new_status: return
        self.db_controller.update_invoice_status(invoice_id, new_status)
        
        # Invalidate cache so DB is fresh
        self.db_controller.invalidate_cache()
        
        from PySide6.QtCore import Qt
        # Update row visuals instead of reloading table
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.UserRole) == invoice_id:
                if new_status == "Bezahlt":
                    # Remove the row immediately
                    self.table.removeRow(row)
                else:
                    # Update row color
                    row_color = "#FFD6D6" if new_status == "Überfällig" else None
                    from PySide6.QtGui import QBrush, QColor
                    if row_color:
                        brush = QBrush(QColor(row_color))
                    else:
                        brush = QBrush(Qt.NoBrush)
                        
                    for col in range(5):
                        self.table.item(row, col).setBackground(brush)
                        
                # Update button state based on new status
                btn_container = self.table.cellWidget(row, 6)
                if btn_container:
                    btn = btn_container.layout().itemAt(0).widget()
                    if new_status == "Bezahlt":
                        btn.setEnabled(False)
                        btn.setToolTip("Rechnung ist bezahlt")
                    elif new_status == "Überfällig":
                        btn.setEnabled(True)
                        btn.setText(btn.text().split(" (")[0])
                        btn.setToolTip("")
                
                break
        
    def show_invoice(self, invoice_id):
        main_window = self.window()
        if hasattr(main_window, 'invoice_interface'):
            main_window.invoice_interface.show_editor_view(invoice_id)
            main_window.navigationInterface.setCurrentItem(main_window.invoice_interface.objectName())
            main_window.stackedWidget.setCurrentWidget(main_window.invoice_interface)

    def mark_as_paid(self, invoice_id):
        self.change_invoice_status(invoice_id, "Bezahlt")
        InfoBar.success("Status aktualisiert", "Die Rechnung wurde als bezahlt markiert.", position=InfoBarPosition.TOP_RIGHT, parent=self.window())

    def generate_reminder(self, invoice_id, level, btn=None, print_only=False):
        if btn:
            btn.blockSignals(True)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(150, lambda: self._do_generate_reminder(invoice_id, level, btn, print_only))

    def _do_generate_reminder(self, invoice_id, level, btn=None, print_only=False):
        from src.utils.pdf_generator import PDFGenerator
        import os
        from src.models.database import Invoice
        from datetime import datetime, timezone
        
        with self.db_controller.get_session() as session:
            inv = session.query(Invoice).filter(Invoice.id == invoice_id).first()
            if inv:
                try:
                    import tempfile
                    pdf_gen = PDFGenerator(self.db_controller)
                    
                    if print_only:
                        filepath = os.path.join(tempfile.gettempdir(), f"print_mahnung_{level}_{inv.invoice_number}.pdf")
                    else:
                        filepath = os.path.join(os.path.expanduser("~"), "Desktop", f"Mahnung_{level}_{inv.invoice_number}.pdf")
                        
                    pdf_gen.generate_reminder_pdf(inv, filepath, level)
                    
                    if not print_only:
                        inv.status = "Überfällig"
                        inv.reminder_level = level
                        inv.last_reminder_date = datetime.now(timezone.utc)
                        session.commit()
                        self.db_controller.db.save()
                        self.db_controller.invalidate_cache()
                        SignalBus.get().dataChanged.emit()
                    
                    if print_only:
                        os.startfile(filepath, "print")
                    else:
                        InfoBar.success(
                            title="Mahnung Erstellt",
                            content=f"Die Mahnung wurde als PDF auf dem Desktop gespeichert:\n{filepath}",
                            orient=Qt.Horizontal,
                            isClosable=True,
                            position=InfoBarPosition.TOP_RIGHT,
                            duration=5000,
                            parent=self.window()
                        )
                        # Recreate the button container exactly like in load_data
                        # to guarantee perfectly clean layout and no animation artifacts
                        target_row = -1
                        for row in range(self.table.rowCount()):
                            item = self.table.item(row, 0)
                            if item and item.data(Qt.UserRole) == invoice_id:
                                target_row = row
                                break
                                
                        if target_row != -1:
                            from qfluentwidgets import PushButton
                            new_btn = PushButton(f"{level + 1}. Mahnung erstellen (in 14 Tagen)")
                            new_btn.setFixedSize(240, 32)
                            new_btn.setEnabled(False)
                            new_btn.setToolTip("Nächste Mahnung in 14 Tagen möglich")
                            new_btn.clicked.connect(lambda checked=False, i_id=invoice_id, l=level+1, b=new_btn: self.generate_reminder(i_id, l, b))
                            
                            from PySide6.QtWidgets import QWidget, QHBoxLayout
                            act_container = QWidget()
                            act_container.setStyleSheet("background-color: transparent;")
                            act_lay = QHBoxLayout(act_container)
                            act_lay.setContentsMargins(0, 0, 20, 0)
                            act_lay.setAlignment(Qt.AlignCenter)
                            act_lay.addWidget(new_btn)
                            
                            self.table.setCellWidget(target_row, 6, act_container)
                            
                            # Also update row status and color directly if possible
                            for row in range(self.table.rowCount()):
                                item = self.table.item(row, 0)
                                if item and item.data(Qt.UserRole) == invoice_id:
                                    combo_container = self.table.cellWidget(row, 5)
                                    if combo_container:
                                        combo = combo_container.layout().itemAt(0).widget()
                                        combo.blockSignals(True)
                                        combo.setCurrentText("Überfällig")
                                        combo.blockSignals(False)
                                    from PySide6.QtGui import QBrush, QColor
                                    for col in range(5):
                                        self.table.item(row, col).setBackground(QBrush(QColor("#FFD6D6")))
                                    break
                        if btn:
                            btn.blockSignals(False)
                except Exception as e:
                    if btn:
                        btn.blockSignals(False)
                    InfoBar.error(
                        title="Fehler",
                        content=f"Die PDF konnte nicht erstellt werden: {str(e)}",
                        orient=Qt.Horizontal,
                        isClosable=True,
                        position=InfoBarPosition.TOP,
                        duration=8000,
                        parent=self.window()
                    )

