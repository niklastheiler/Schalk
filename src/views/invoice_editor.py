from datetime import datetime, timezone
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QFormLayout
from qfluentwidgets import CheckBox, LineEdit
from src.views.date_picker import GermanDatePicker
from src.views.document_editor import DocumentEditor, _german_number, _parse_number, _number_validator


def _qdate(value: datetime) -> QDate:
    return QDate(value.year, value.month, value.day)


def _to_datetime(picker: GermanDatePicker) -> datetime:
    d = picker.date
    return datetime(d.year(), d.month(), d.day(), tzinfo=timezone.utc)


class InvoiceEditor(DocumentEditor):
    NEW_TITLE = "Neue Rechnung"
    SAVE_TEXT = "Rechnung speichern"

    def add_document_fields(self, form: QFormLayout):
        self.invoiceDate = GermanDatePicker()
        form.addRow("Rechnungsdatum", self.invoiceDate)
        self.deliveryDate = GermanDatePicker()
        form.addRow("Leistungsdatum", self.deliveryDate)
        self.creditCheck = CheckBox("Gutschrift / Nachlass")
        self.creditCheck.stateChanged.connect(self._on_credit_toggled)
        form.addRow("", self.creditCheck)
        self.creditAmountEdit = LineEdit()
        self.creditAmountEdit.setPlaceholderText("Nettobetrag (€)")
        self.creditAmountEdit.setValidator(_number_validator())
        self.creditAmountEdit.textChanged.connect(self.update_totals)
        self.creditDescEdit = LineEdit()
        self.creditDescEdit.setPlaceholderText("Beschreibung")
        form.addRow("", self.creditAmountEdit)
        form.addRow("", self.creditDescEdit)
        self._on_credit_toggled()

    def _on_credit_toggled(self, state=None):
        visible = self.creditCheck.isChecked()
        self.creditAmountEdit.setVisible(visible)
        self.creditDescEdit.setVisible(visible)
        if not visible:
            self.creditAmountEdit.clear()
            self.creditDescEdit.clear()
        self.update_totals()

    def clear_document_fields(self):
        self.invoiceDate.setDate(QDate.currentDate())
        self.deliveryDate.setDate(QDate.currentDate())
        self.creditCheck.setChecked(False)

    def set_document_fields_enabled(self, enabled: bool):
        for widget in (self.invoiceDate, self.deliveryDate, self.creditCheck, self.creditAmountEdit, self.creditDescEdit):
            widget.setEnabled(enabled)

    def credit_amount(self) -> float:
        if not hasattr(self, "creditCheck") or not self.creditCheck.isChecked():
            return 0.0
        return max(0.0, _parse_number(self.creditAmountEdit.text(), 0.0))

    def load_invoice(self, invoice_id: int):
        self.clear_form()
        invoice = self.db_controller.get_invoice(invoice_id)
        if not invoice:
            return
        self.current_id = invoice_id
        self.invoiceDate.setDate(_qdate(invoice.invoice_date))
        self.deliveryDate.setDate(_qdate(invoice.delivery_date))
        if (invoice.credit_amount or 0) > 0:
            self.creditCheck.setChecked(True)
            self.creditAmountEdit.setText(_german_number(invoice.credit_amount))
            self.creditDescEdit.setText(invoice.credit_desc or "")
        self.load_items(invoice)

        if self.db_controller.is_finalized(invoice):
            # Show the recipient exactly as frozen on the issued invoice, not the current master data
            buyer = self.db_controller.buyer_of(invoice)
            self.customerSearch.setText(buyer["name"] or "")
            self.companyEdit.setText(buyer["name"] or "")
            self.nameEdit.clear()
            for edit, key in ((self.addressEdit, "address"), (self.postalCodeEdit, "postal_code"), (self.cityEdit, "city")):
                edit.setText(buyer.get(key) or "")
            # GoBD: finalized invoices are immutable
            self.set_read_only(True)
            suffix = "Archiviert" if invoice.archived_at else "festgeschrieben"
            self.titleLabel.setText(f"Rechnung {invoice.invoice_number} ({suffix})")
        else:
            self.titleLabel.setText("Rechnungsentwurf bearbeiten")

    def persist(self, customer_id: int, items: list, exemption_reason: str) -> int:
        credit = self.credit_amount()
        fields = dict(
            customer_id=customer_id,
            invoice_date=_to_datetime(self.invoiceDate),
            delivery_date=_to_datetime(self.deliveryDate),
            items=items,
            credit_amount=credit,
            credit_desc=self.creditDescEdit.text().strip() if credit > 0 else "",
            tax_exemption_reason=exemption_reason,
        )
        if self.current_id:
            self.db_controller.update_invoice(invoice_id=self.current_id, **fields)
            return self.current_id
        return self.db_controller.create_invoice(**fields)
