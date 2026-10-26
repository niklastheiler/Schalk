from PySide6.QtCore import QDate
from PySide6.QtWidgets import QFormLayout
from src.views.date_picker import GermanDatePicker
from src.views.document_editor import DocumentEditor
from src.views.invoice_editor import _qdate, _to_datetime


class QuoteEditor(DocumentEditor):
    NEW_TITLE = "Neues Angebot"
    SAVE_TEXT = "Angebot speichern"

    def add_document_fields(self, form: QFormLayout):
        self.quoteDate = GermanDatePicker()
        form.addRow("Angebotsdatum", self.quoteDate)

    def clear_document_fields(self):
        self.quoteDate.setDate(QDate.currentDate())

    def set_document_fields_enabled(self, enabled: bool):
        self.quoteDate.setEnabled(enabled)

    def load_quote(self, quote_id: int):
        self.clear_form()
        quote = self.db_controller.get_quote(quote_id)
        if not quote:
            return
        self.current_id = quote_id
        self.quoteDate.setDate(_qdate(quote.quote_date))
        self.load_items(quote)
        if quote.archived_at:
            self.set_read_only(True)
            self.titleLabel.setText(f"Angebot {quote.quote_number} (Archiviert)")
        else:
            self.titleLabel.setText(f"Angebot {quote.quote_number} bearbeiten")

    def persist(self, customer_id: int, items: list, exemption_reason: str) -> int:
        fields = dict(customer_id=customer_id, quote_date=_to_datetime(self.quoteDate), items=items,
                      tax_exemption_reason=exemption_reason)
        if self.current_id:
            self.db_controller.update_quote(quote_id=self.current_id, **fields)
            return self.current_id
        return self.db_controller.create_quote(**fields)
