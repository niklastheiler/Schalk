"""
Recognises a receipt attached to a cashbook entry: amount, description, date and whether it is income or expense.

Income is always an invoice issued by Schalk itself (paid in cash). It is found by
1. the file being byte for byte an archived invoice (e.g. saved with "PDF speichern"),
2. the embedded e-invoice data carrying the number of an own invoice, or
3. the text containing the number of an own invoice together with the own company name.
Every other receipt (receipt of a shop, supplier invoice) is an expense.
"""
from dataclasses import dataclass
from datetime import date
from typing import Optional
from src.utils.archive import file_sha256
from src.utils.einvoice_parser import read_einvoice
from src.utils.pdf_text_guess import guess_from_text, read_pdf_text

INCOME = "Einnahme"
EXPENSE = "Barentnahme Firma" # business expense paid from the till


@dataclass
class ReceiptGuess:
    entry_type: str
    amount: float = 0.0
    description: str = ""
    receipt_date: Optional[date] = None # date of an expense receipt; income keeps the date of the cash payment
    invoice_id: Optional[int] = None # own invoice the cash income belongs to


def _own_invoices(controller) -> dict:
    """Issued own invoices by number (Stornorechnungen are no income)."""
    return {i.invoice_number: i for i in controller.get_invoices()
            if controller.is_finalized(i) and not i.cancels_invoice_id}


def _income(controller, invoice) -> ReceiptGuess:
    # Cash received for the invoice: the whole open amount (there are no partial payments)
    amount = controller.outstanding_amount(invoice) or invoice.gross_amount
    customer = controller.customer_display_name(invoice)
    return ReceiptGuess(INCOME, amount, f"Rechnung {invoice.invoice_number} – {customer}".strip(" –"), None, invoice.id)


def recognize_receipt(controller, path: str) -> ReceiptGuess:
    own = _own_invoices(controller)
    seller = controller.current_seller()
    own_names = [seller.get("company_name"), f"{seller.get('first_name', '')} {seller.get('last_name', '')}".strip()]

    file_hash = file_sha256(path)
    for invoice in own.values():
        if invoice.pdf_hash and invoice.pdf_hash == file_hash:
            return _income(controller, invoice)

    try:
        einvoice = read_einvoice(path)
    except Exception: # damaged or too large: the text may still help
        einvoice = None
    if einvoice:
        if einvoice.number in own and (not einvoice.seller_name or not seller.get("company_name")
                                       or einvoice.seller_name.casefold() == seller["company_name"].casefold()):
            return _income(controller, own[einvoice.number])
        amount = einvoice.payable_amount or einvoice.gross_amount
        return ReceiptGuess(EXPENSE, abs(amount), f"{einvoice.seller_name} {einvoice.number}".strip(), einvoice.issue_date)

    text, author = read_pdf_text(path)
    guess = guess_from_text(text, own_names, author)
    company = (seller.get("company_name") or "").casefold()
    if guess.number in own and company and company in text.casefold():
        return _income(controller, own[guess.number])
    return ReceiptGuess(EXPENSE, abs(guess.amount), f"{guess.supplier} {guess.number}".strip(), guess.invoice_date)
