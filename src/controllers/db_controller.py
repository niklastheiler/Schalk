import getpass
import hashlib
import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime, timezone, timedelta
from typing import Callable, Dict, Iterable, List, Optional
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session, selectinload
from src.models.database import DatabaseManager, Setting, Customer, Invoice, InvoiceItem, Quote, QuoteItem, CashbookEntry, DocumentHistory, IncomingInvoice
from src.utils.signal_bus import SignalBus
from src.utils.calculations import calculate_totals, item_total
from src.utils.tax import TAX_RATE_OPTIONS, has_zero_rate, vat_category, EXEMPTION_REQUIRED_MESSAGE
from src.utils.archive import archive_file, is_pdf, verify_file
from src.utils import paths

logger = logging.getLogger(__name__)

DRAFT_PREFIX = "ENTWURF-"
INVOICE_STATUSES = ["Entwurf", "Offen", "Teilbezahlt", "Bezahlt", "Überfällig", "Storniert"]
# Process: draft -> issued -> (partly) paid; "Überfällig" is set automatically, "Bezahlt" can be
# taken back (e.g. returned direct debit), cancelling creates a Stornorechnung
INVOICE_TRANSITIONS = {
    "Entwurf": ["Offen"],
    "Offen": ["Teilbezahlt", "Bezahlt", "Storniert"],
    "Überfällig": ["Teilbezahlt", "Bezahlt", "Storniert"],
    "Teilbezahlt": ["Bezahlt", "Storniert"],
    "Bezahlt": ["Offen"],
    "Storniert": [],
}
QUOTE_STATUSES = ["Entwurf", "Versendet", "Angenommen", "Abgelehnt", "Abgelaufen"]
CASHBOOK_TYPES = ["Einnahme", "Barentnahme Privat", "Barentnahme Firma"]
CASHBOOK_INCOME_TYPES = ["Einnahme"]
DEFAULT_PAYMENT_TERMS = 14
NO_ITEMS_MESSAGE = "Rechnungen und Angebote benötigen mindestens eine Position mit Bezeichnung."

# Settings that describe the seller; they are frozen into every finalized invoice
SELLER_KEYS = ["company_name", "first_name", "last_name", "address", "postal_code", "city", "tax_id", "vat_id",
               "email", "phone", "bank_name", "iban", "bic", "account_holder"]


class GoBDError(Exception):
    """Raised when an action would violate GoBD rules or legal invoice requirements."""


def _current_user() -> str:
    try:
        return getpass.getuser() or "System"
    except Exception:
        return "System"


def _num(value):
    # -0.0 (e.g. negated zero tax of a Stornorechnung) is read back from SQLite as 0.0
    return None if value is None else float(value) + 0.0


def _iso(dt) -> Optional[str]:
    # Values come back from SQLite without tzinfo; normalize so hashes are reproducible
    return dt.replace(tzinfo=None).isoformat() if dt else None


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt else dt


class _EntityCache:
    """Objects of one table indexed by id; the sorted list is rebuilt lazily after changes."""

    def __init__(self, model, sort_key: Callable, reverse: bool, signal_name: str):
        self.model = model
        self.sort_key = sort_key
        self.reverse = reverse
        self.signal_name = signal_name
        self.by_id: Dict[int, object] = {}
        self._sorted = None

    def replace(self, objects: Iterable, ids: Optional[Iterable[int]] = None):
        if ids is None:
            self.by_id = {o.id: o for o in objects}
        else:
            for missing in set(ids):
                self.by_id.pop(missing, None)
            for o in objects:
                self.by_id[o.id] = o
        self._sorted = None

    def sorted(self) -> list:
        if self._sorted is None:
            self._sorted = sorted(self.by_id.values(), key=self.sort_key, reverse=self.reverse)
        return self._sorted


class DBController:
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        # Callable(invoice_id) that renders and archives the PDF of a freshly finalized invoice
        self.archiver: Optional[Callable[[int], None]] = None
        # Callable(invoice) -> list of problems; checks the e-invoice data before an invoice is sealed
        self.einvoice_validator: Optional[Callable[[Invoice], List[str]]] = None
        self._finalized_pending: List[int] = []
        self._caches = {
            "invoices": _EntityCache(Invoice, lambda i: (_naive(i.invoice_date), i.id), True, "invoicesChanged"),
            "quotes": _EntityCache(Quote, lambda q: (_naive(q.quote_date), q.id), True, "quotesChanged"),
            "customers": _EntityCache(Customer, lambda c: (c.display_name.lower(), c.id), False, "customersChanged"),
            "cashbook": _EntityCache(CashbookEntry, lambda e: (e.entry_date, e.id), True, "cashbookChanged"),
            "incoming": _EntityCache(IncomingInvoice, lambda i: (i.date, i.id), True, "incomingInvoicesChanged"),
        }
        with self.get_session() as session:
            self._settings = {s.key: s.value for s in session.query(Setting).all()}
        for kind in self._caches:
            self._reload(kind)
        self.refresh_overdue()

    # --- Infrastructure ---
    def get_session(self) -> Session:
        # All sessions share the single in-memory connection: a session opened while another one
        # has an open transaction would roll that transaction back when it closes
        if self.db.memory_conn.in_transaction:
            raise RuntimeError("Verschachtelte Datenbank-Session: die äußere Transaktion würde verworfen.")
        return self.db.Session()

    def _reload(self, kind: str, ids: Optional[Iterable[int]] = None):
        cache = self._caches[kind]
        with self.get_session() as session:
            query = session.query(cache.model)
            if ids is not None:
                ids = list(ids)
                if not ids:
                    return
                query = query.filter(cache.model.id.in_(ids))
            cache.replace(query.all(), ids)

    def _commit(self, session: Session, **changes):
        """
        Commits, persists the encrypted file (in the background), refreshes only the changed
        records in the cache and notifies the views. changes: kind -> ids (None = reload all).
        """
        session.commit()
        self.db.save()
        bus = SignalBus.get()
        for kind, ids in changes.items():
            self._reload(kind, ids)
            getattr(bus, self._caches[kind].signal_name).emit()

        pending, self._finalized_pending = self._finalized_pending, []
        for invoice_id in pending:
            self._archive_finalized(invoice_id)

    def _archive_finalized(self, invoice_id: int):
        if not self.archiver:
            return
        try:
            self.archiver(invoice_id)
        except Exception:
            # The PDF is generated again on the next request; the sealed data is already safe
            logger.exception("Archivierung der Rechnung %s fehlgeschlagen", invoice_id)

    def close(self):
        self.db.close()

    def _hash_record(self, data: str, prev_hash: str) -> str:
        sha256 = hashlib.sha256()
        sha256.update(f"{data}{prev_hash}".encode('utf-8'))
        return sha256.hexdigest()

    def _log(self, session: Session, document_type: str, document_id: int, action: str, user: str = None):
        session.add(DocumentHistory(
            document_type=document_type,
            document_id=document_id,
            user=user or _current_user(),
            action=action
        ))

    def get_document_history(self, document_type: str, document_id: int) -> List[DocumentHistory]:
        with self.get_session() as session:
            return session.query(DocumentHistory).filter(
                DocumentHistory.document_type == document_type,
                DocumentHistory.document_id == document_id
            ).order_by(DocumentHistory.id).all()

    # --- Settings ---
    def get_setting(self, key: str, default: str = "") -> str:
        return self._settings.get(key) or default

    def set_setting(self, key: str, value: str):
        self.set_settings({key: value})

    def set_settings(self, values: dict):
        with self.get_session() as session:
            for key, value in values.items():
                session.merge(Setting(key=key, value=value))
            session.commit()
        self._settings.update(values)
        self.db.save()
        SignalBus.get().settingsChanged.emit()

    def get_payment_terms(self) -> int:
        try:
            return int(self.get_setting("payment_terms_days") or DEFAULT_PAYMENT_TERMS)
        except ValueError:
            return DEFAULT_PAYMENT_TERMS

    def is_small_business(self) -> bool:
        return self.get_setting("small_business") == "1"

    def current_seller(self) -> dict:
        return {key: self.get_setting(key) for key in SELLER_KEYS}

    # --- Cashbook (GoBD) ---
    def _last_cashbook_hash(self, session: Session) -> str:
        last_entry = session.query(CashbookEntry).order_by(CashbookEntry.id.desc()).first()
        return last_entry.hash_chain if last_entry and last_entry.hash_chain else "GENESIS"

    @staticmethod
    def _next_number(session: Session, column, prefix: str, start: int) -> int:
        numbers = session.query(column).filter(column.like(f"{prefix}%")).all()
        last_num = 0
        for (number,) in numbers:
            suffix = number[start:]
            if suffix.isdigit():
                last_num = max(last_num, int(suffix))
        return last_num + 1

    def get_next_receipt_number(self, session: Session) -> str:
        prefix = f"K{datetime.now().year}-"
        return f"{prefix}{self._next_number(session, CashbookEntry.receipt_number, prefix, len(prefix)):06d}"

    @staticmethod
    def cashbook_signed_amount(entry) -> float:
        """Effect of an entry on the cash balance (income positive, withdrawals negative)."""
        return entry.amount if entry.entry_type in CASHBOOK_INCOME_TYPES else -entry.amount

    def get_cashbook_balance(self) -> float:
        return round(sum(self.cashbook_signed_amount(e) for e in self._caches["cashbook"].by_id.values()), 2)

    @staticmethod
    def _cashbook_hash_payload(entry: CashbookEntry) -> str:
        return "|".join(str(v) for v in [
            entry.id, _iso(entry.entry_date), _num(entry.amount), entry.receipt_number, entry.description,
            entry.entry_type, entry.attachment_hash or "", int(bool(entry.is_storno)), entry.storno_of_id or ""
        ])

    def _add_cashbook_row(self, session: Session, user: str = None, **fields) -> CashbookEntry:
        prev_hash = self._last_cashbook_hash(session)
        entry = CashbookEntry(receipt_number=self.get_next_receipt_number(session), **fields)
        session.add(entry)
        session.flush() # Get ID
        entry.hash_chain = self._hash_record(self._cashbook_hash_payload(entry), prev_hash)
        self._log(session, "Cashbook", entry.id, "Storno-Gegenbuchung" if entry.is_storno else "Created", user)
        return entry

    def add_cashbook_entry(self, entry_date: datetime, amount: float, description: str, category: str, entry_type: str, tax_percent: float, attachment_source: str = None, user: str = None) -> int:
        if amount <= 0:
            raise ValueError("Der Betrag muss größer als 0 sein.")
        if entry_type not in CASHBOOK_TYPES:
            raise ValueError(f"Unbekannte Buchungsart: {entry_type}")
        signed = amount if entry_type in CASHBOOK_INCOME_TYPES else -amount
        if self.get_cashbook_balance() + signed < 0:
            raise ValueError("Der Kassenbestand darf nicht negativ werden!")

        attachment_path, attachment_hash = None, None
        if attachment_source and not is_pdf(attachment_source):
            raise ValueError("Als Beleg sind nur PDF-Dateien erlaubt.")
        if attachment_source:
            attachment_path, attachment_hash = archive_file(attachment_source, paths.RECEIPTS_DIR)

        with self.get_session() as session:
            entry = self._add_cashbook_row(
                session, user,
                entry_date=entry_date,
                amount=amount,
                description=description or "Keine Angabe",
                category=category,
                entry_type=entry_type,
                tax_percent=tax_percent,
                attachment_path=attachment_path,
                attachment_hash=attachment_hash,
            )
            entry_id = entry.id
            self._commit(session, cashbook=[entry_id])
            return entry_id

    def storno_cashbook_entry(self, entry_id: int, user: str = None) -> int:
        """GoBD: entries are never changed or deleted; a correction is a reversing entry."""
        with self.get_session() as session:
            original = session.get(CashbookEntry, entry_id)
            if not original:
                raise GoBDError("Eintrag nicht gefunden.")
            if original.is_storno:
                raise GoBDError("Eine Storno-Buchung kann nicht erneut storniert werden.")
            if session.query(CashbookEntry).filter(CashbookEntry.storno_of_id == entry_id).count():
                raise GoBDError("Dieser Eintrag wurde bereits storniert.")
            if self.get_cashbook_balance() - self.cashbook_signed_amount(original) < 0:
                raise ValueError("Durch die Stornierung würde der Kassenbestand negativ werden!")

            entry = self._add_cashbook_row(
                session, user,
                entry_date=datetime.combine(datetime.now().date(), datetime.min.time()),
                amount=-original.amount,
                description=f"Storno zu {original.receipt_number}",
                category=original.category,
                entry_type=original.entry_type,
                tax_percent=original.tax_percent,
                is_storno=True,
                storno_of_id=original.id,
            )
            self._log(session, "Cashbook", original.id, f"Storniert durch {entry.receipt_number}", user)
            new_id = entry.id
            self._commit(session, cashbook=[new_id])
            return new_id

    def get_cashbook_entries(self) -> list:
        return self._caches["cashbook"].sorted()

    def get_cashbook_entry(self, entry_id: int) -> Optional[CashbookEntry]:
        return self._caches["cashbook"].by_id.get(entry_id)

    def cancelled_cashbook_ids(self) -> set:
        return {e.storno_of_id for e in self._caches["cashbook"].by_id.values() if e.storno_of_id}

    # --- Customers ---
    def add_customer(self, **kwargs) -> int:
        with self.get_session() as session:
            customer = Customer(**kwargs)
            session.add(customer)
            session.flush()
            customer_id = customer.id
            self._commit(session, customers=[customer_id])
            return customer_id

    def update_customer(self, customer_id: int, **kwargs):
        with self.get_session() as session:
            customer = session.get(Customer, customer_id)
            if not customer:
                return
            changed = False
            for key, value in kwargs.items():
                if getattr(customer, key) != value:
                    setattr(customer, key, value)
                    changed = True
            if not changed:
                return
            # Cached drafts and quotes show the customer, so refresh those as well
            invoice_ids = [i.id for i in self._caches["invoices"].by_id.values() if i.customer_id == customer_id]
            quote_ids = [q.id for q in self._caches["quotes"].by_id.values() if q.customer_id == customer_id]
            self._commit(session, customers=[customer_id], invoices=invoice_ids, quotes=quote_ids)

    def delete_customer(self, customer_id: int):
        invoices = sum(1 for i in self._caches["invoices"].by_id.values() if i.customer_id == customer_id)
        quotes = sum(1 for q in self._caches["quotes"].by_id.values() if q.customer_id == customer_id)
        if invoices or quotes:
            reasons = []
            if invoices: reasons.append(f"{invoices} Rechnungen")
            if quotes: reasons.append(f"{quotes} Angebote")
            return False, " und ".join(reasons)
        with self.get_session() as session:
            customer = session.get(Customer, customer_id)
            if not customer:
                return False, "Kunde nicht gefunden"
            session.delete(customer)
            self._commit(session, customers=[customer_id])
            return True, ""

    def get_customers(self) -> list:
        return self._caches["customers"].sorted()

    def get_customer(self, customer_id: int) -> Optional[Customer]:
        return self._caches["customers"].by_id.get(customer_id)

    # --- Items (shared by invoices and quotes) ---
    @staticmethod
    def _normalize_items(items: list) -> list:
        if not items:
            raise ValueError(NO_ITEMS_MESSAGE)
        normalized = []
        for item in items:
            quantity = float(item.get('quantity', 1.0))
            unit_price = float(item['unit_price'])
            discount = float(item.get('discount_percent') or 0.0)
            if not (item.get('title') or "").strip():
                raise ValueError("Jede Position benötigt eine Bezeichnung.")
            if quantity <= 0:
                raise ValueError(f"Die Menge der Position '{item['title']}' muss größer als 0 sein.")
            tax_percent = float(item.get('tax_percent', TAX_RATE_OPTIONS[0]))
            if tax_percent not in TAX_RATE_OPTIONS:
                raise ValueError(f"Unzulässiger Steuersatz {tax_percent} % bei '{item['title']}'.")
            normalized.append({
                "title": item['title'].strip(),
                "description": item.get('description'),
                "quantity": quantity,
                "unit": (item.get('unit') or "Stück").strip(),
                "unit_price": unit_price,
                "discount_percent": discount,
                "tax_percent": tax_percent,
                "total_price": item_total(quantity, unit_price, discount),
            })
        return normalized

    @staticmethod
    def _exemption_reason(items: list, reason: str) -> Optional[str]:
        """Validates the VAT exemption reason; it is only kept if an item has 0 % VAT."""
        if not has_zero_rate(items):
            return None
        reason = (reason or "").strip()
        if not reason:
            raise ValueError(EXEMPTION_REQUIRED_MESSAGE)
        return reason

    @staticmethod
    def _write_items(session: Session, model, fk_name: str, parent_id: int, items: list):
        session.query(model).filter(getattr(model, fk_name) == parent_id).delete()
        for item_data in items:
            session.add(model(**{fk_name: parent_id}, **item_data))

    # --- Invoices: seller/buyer data ---
    @staticmethod
    def is_finalized(invoice: Invoice) -> bool:
        return invoice.finalized_at is not None

    @staticmethod
    def is_draft_number(number: str) -> bool:
        return number.startswith(DRAFT_PREFIX)

    def seller_of(self, invoice: Invoice) -> dict:
        """Seller data as frozen at finalization (drafts use the current settings)."""
        if invoice.seller_snapshot:
            return json.loads(invoice.seller_snapshot)
        return self.current_seller()

    def buyer_of(self, invoice: Invoice) -> dict:
        """Recipient data as frozen at finalization (drafts use the current customer)."""
        if invoice.customer_name:
            return {
                "name": invoice.customer_name, "address": invoice.customer_address,
                "postal_code": invoice.customer_postal_code, "city": invoice.customer_city,
                "country": invoice.customer_country, "vat_id": invoice.customer_vat_id,
                "email": invoice.customer_email, "buyer_reference": invoice.customer_buyer_reference,
            }
        customer = self.get_customer(invoice.customer_id)
        return {
            "name": customer.display_name, "address": customer.address, "postal_code": customer.postal_code,
            "city": customer.city, "country": customer.country, "vat_id": customer.vat_id,
            "email": customer.email, "buyer_reference": customer.buyer_reference,
        }

    def payment_terms_of(self, invoice: Invoice) -> int:
        return invoice.payment_terms_days if invoice.payment_terms_days is not None else self.get_payment_terms()

    def get_due_date(self, invoice: Invoice) -> datetime:
        return _naive(invoice.invoice_date) + timedelta(days=self.payment_terms_of(invoice))

    def customer_display_name(self, document) -> str:
        if getattr(document, "customer_name", None):
            return document.customer_name
        customer = self.get_customer(document.customer_id)
        return customer.display_name if customer else ""

    # --- Invoices: validation and sealing ---
    def check_invoice_requirements(self, invoice: Invoice, items: list) -> List[str]:
        """Mandatory content of an invoice (§ 14 Abs. 4 UStG, EN 16931). Returns a list of problems."""
        problems = []
        seller = self.seller_of(invoice)
        buyer = self.buyer_of(invoice)
        if not (seller.get("company_name") or seller.get("last_name")):
            problems.append("Firmenname fehlt (Einstellungen > Firmendaten).")
        for key, label in (("address", "Straße"), ("postal_code", "PLZ"), ("city", "Ort")):
            if not seller.get(key):
                problems.append(f"{label} der eigenen Firma fehlt (Einstellungen > Firmendaten).")
        if not (seller.get("tax_id") or seller.get("vat_id")):
            problems.append("Steuernummer oder USt-IdNr. der eigenen Firma fehlt (Einstellungen > Firmendaten).")
        if not buyer.get("name"):
            problems.append("Name des Kunden fehlt.")
        for key, label in (("address", "Straße"), ("postal_code", "PLZ"), ("city", "Ort")):
            if not buyer.get(key):
                problems.append(f"{label} des Kunden fehlt.")
        if not items:
            problems.append("Die Rechnung hat keine Positionen.")
        if not invoice.delivery_date:
            problems.append("Leistungsdatum fehlt.")
        if has_zero_rate(items) and not invoice.tax_exemption_reason:
            problems.append(EXEMPTION_REQUIRED_MESSAGE)
        categories = {vat_category(i.tax_percent, invoice.tax_exemption_reason) for i in items}
        if categories & {"AE", "K"}:
            if not seller.get("vat_id"):
                problems.append("Bei Reverse Charge / innergemeinschaftlicher Lieferung ist die eigene USt-IdNr. Pflicht.")
            if not buyer.get("vat_id"):
                problems.append("Bei Reverse Charge / innergemeinschaftlicher Lieferung ist die USt-IdNr. des Kunden Pflicht (Kundenstamm).")
        if (invoice.gross_amount or 0) < 0:
            problems.append("Der Rechnungsbetrag darf nicht negativ sein (Gutschrift zu hoch).")
        return problems

    def get_next_invoice_number(self, session: Session) -> str:
        # Format: RE + year + month + running number per year (at least 3 digits)
        now = datetime.now()
        prefix = f"RE{now.year}"
        return f"{prefix}{now.month:02d}{self._next_number(session, Invoice.invoice_number, prefix, len(prefix) + 2):03d}"

    def _invoice_hash_payload(self, invoice: Invoice, items: list) -> str:
        payload = {
            "id": invoice.id,
            "number": invoice.invoice_number,
            "invoice_date": _iso(invoice.invoice_date),
            "delivery_date": _iso(invoice.delivery_date),
            "finalized_at": _iso(invoice.finalized_at),
            "payment_terms_days": invoice.payment_terms_days,
            "seller": invoice.seller_snapshot,
            "customer": [invoice.customer_name, invoice.customer_address, invoice.customer_postal_code,
                         invoice.customer_city, invoice.customer_country, invoice.customer_vat_id,
                         invoice.customer_email, invoice.customer_buyer_reference],
            "items": [[i.title, i.description, _num(i.quantity), i.unit, _num(i.unit_price), _num(i.discount_percent),
                       _num(i.tax_percent), _num(i.total_price)] for i in items],
            "net": _num(invoice.net_amount),
            "tax": _num(invoice.tax_amount),
            "gross": _num(invoice.gross_amount),
            "credit": [_num(invoice.credit_amount or 0.0), invoice.credit_desc or ""],
            "tax_exemption_reason": invoice.tax_exemption_reason,
            "cancels": invoice.cancels_invoice_id,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    def _last_invoice_hash(self, session: Session, exclude_id: int) -> str:
        last = session.query(Invoice).filter(Invoice.finalized_at != None, Invoice.id != exclude_id).order_by(Invoice.finalized_at.desc(), Invoice.id.desc()).first()
        return last.hash_chain if last and last.hash_chain else "GENESIS"

    def _finalize(self, session: Session, invoice: Invoice, user: str = None, action: str = "Festgeschrieben"):
        """GoBD: checks the mandatory content, assigns the final number, freezes seller and
        recipient data and seals the invoice in the hash chain."""
        if invoice.finalized_at:
            return
        session.flush()
        if not invoice.customer_name:
            customer = session.get(Customer, invoice.customer_id)
            invoice.customer_name = customer.display_name
            invoice.customer_address = customer.address
            invoice.customer_postal_code = customer.postal_code
            invoice.customer_city = customer.city
            invoice.customer_country = customer.country
            invoice.customer_vat_id = customer.vat_id
            invoice.customer_email = customer.email
            invoice.customer_buyer_reference = customer.buyer_reference
        if not invoice.seller_snapshot:
            invoice.seller_snapshot = json.dumps(self.current_seller(), ensure_ascii=False, sort_keys=True)
        if invoice.payment_terms_days is None:
            invoice.payment_terms_days = self.get_payment_terms()

        items = session.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice.id).order_by(InvoiceItem.id).all()
        if not invoice.cancels_invoice_id:
            problems = self.check_invoice_requirements(invoice, items)
            if problems:
                session.rollback()
                raise GoBDError("Die Rechnung kann nicht festgeschrieben werden:\n• " + "\n• ".join(problems))

        if self.is_draft_number(invoice.invoice_number):
            invoice.invoice_number = self.get_next_invoice_number(session)
        invoice.finalized_at = datetime.now(timezone.utc)
        session.flush()
        if self.einvoice_validator:
            problems = self.einvoice_validator(invoice)
            if problems:
                session.rollback()
                raise GoBDError("Die E-Rechnungsdaten verletzen EN 16931:\n• " + "\n• ".join(problems))
        invoice.hash_chain = self._hash_record(self._invoice_hash_payload(invoice, items), self._last_invoice_hash(session, invoice.id))
        self._log(session, "Invoice", invoice.id, f"{action} als {invoice.invoice_number}", user)
        self._finalized_pending.append(invoice.id)

    # --- Invoices: CRUD ---
    def create_invoice(self, customer_id: int, invoice_date: datetime, delivery_date: datetime, items: list, user: str = None, **kwargs) -> int:
        items = self._normalize_items(items)
        credit_amount = kwargs.get("credit_amount", 0.0) or 0.0
        totals = calculate_totals(items, credit_amount)
        status = kwargs.get("status", "Entwurf")
        exemption_reason = self._exemption_reason(items, kwargs.get("tax_exemption_reason"))

        with self.get_session() as session:
            invoice = Invoice(
                # Final numbers are only assigned on finalization, so deleted drafts leave no gaps
                invoice_number=f"{DRAFT_PREFIX}{uuid.uuid4().hex}",
                customer_id=customer_id,
                invoice_date=invoice_date,
                delivery_date=delivery_date,
                net_amount=totals["net_amount"],
                tax_amount=totals["tax_amount"],
                gross_amount=totals["gross_amount"],
                credit_amount=totals["credit_amount"],
                credit_desc=kwargs.get("credit_desc", ""),
                tax_exemption_reason=exemption_reason,
                status="Entwurf"
            )
            session.add(invoice)
            session.flush()
            invoice.invoice_number = f"{DRAFT_PREFIX}{invoice.id}"
            self._write_items(session, InvoiceItem, "invoice_id", invoice.id, items)
            self._log(session, "Invoice", invoice.id, "Created", user)

            if status != "Entwurf":
                self._finalize(session, invoice, user)
                invoice.status = status

            invoice_id = invoice.id
            self._commit(session, invoices=[invoice_id])
            return invoice_id

    def get_invoices(self) -> list:
        return self._caches["invoices"].sorted()

    def get_invoice_header(self, invoice_id: int) -> Optional[Invoice]:
        """Header data from the cache, without items; never touches the database."""
        return self._caches["invoices"].by_id.get(invoice_id)

    def get_invoice(self, invoice_id: int) -> Optional[Invoice]:
        """Invoice including its items (the list cache only holds the header data)."""
        if invoice_id not in self._caches["invoices"].by_id:
            return None
        with self.get_session() as session:
            return session.query(Invoice).options(selectinload(Invoice.items)).filter(Invoice.id == invoice_id).first()

    def update_invoice(self, invoice_id: int, customer_id: int, invoice_date: datetime, delivery_date: datetime, items: list, user: str = None, **kwargs):
        items = self._normalize_items(items)
        credit_amount = kwargs.get("credit_amount", 0.0) or 0.0
        totals = calculate_totals(items, credit_amount)
        exemption_reason = self._exemption_reason(items, kwargs.get("tax_exemption_reason"))

        with self.get_session() as session:
            invoice = session.get(Invoice, invoice_id)
            if not invoice: return False
            if self.is_finalized(invoice):
                raise GoBDError(f"Rechnung {invoice.invoice_number} ist festgeschrieben und kann nicht mehr geändert werden. Bitte stornieren.")

            invoice.customer_id = customer_id
            invoice.tax_exemption_reason = exemption_reason
            invoice.invoice_date = invoice_date
            invoice.delivery_date = delivery_date
            invoice.net_amount = totals["net_amount"]
            invoice.tax_amount = totals["tax_amount"]
            invoice.gross_amount = totals["gross_amount"]
            invoice.credit_amount = totals["credit_amount"]
            invoice.credit_desc = kwargs.get("credit_desc", "")
            self._write_items(session, InvoiceItem, "invoice_id", invoice_id, items)
            self._log(session, "Invoice", invoice_id, "Updated", user)

            status = kwargs.get("status")
            if status and status != "Entwurf":
                self._finalize(session, invoice, user)
                invoice.status = status

            self._commit(session, invoices=[invoice_id])
            return True

    def next_invoice_statuses(self, invoice: Invoice) -> list:
        """The statuses that make sense next in the invoice process (empty = final)."""
        if invoice.cancels_invoice_id:
            return [] # a Stornorechnung is final
        return list(INVOICE_TRANSITIONS.get(invoice.status, []))

    def update_invoice_status(self, invoice_id: int, status: str, user: str = None):
        """Returns (success, message)."""
        if status == "Storniert":
            try:
                storno_id = self.cancel_invoice(invoice_id, user)
            except GoBDError as e:
                return False, str(e)
            return True, f"Stornorechnung {self.get_invoice(storno_id).invoice_number} wurde erstellt."

        try:
            with self.get_session() as session:
                invoice = session.get(Invoice, invoice_id)
                if not invoice:
                    return False, "Rechnung nicht gefunden."
                if invoice.status == status:
                    return True, ""
                if status not in self.next_invoice_statuses(invoice):
                    if status == "Entwurf":
                        return False, "Eine festgeschriebene Rechnung kann nicht wieder zum Entwurf werden."
                    return False, f"Statuswechsel von '{invoice.status}' nach '{status}' ist nicht vorgesehen."

                message = ""
                if not self.is_finalized(invoice):
                    self._finalize(session, invoice, user)
                    message = f"Rechnung wurde als {invoice.invoice_number} festgeschrieben."
                self._log(session, "Invoice", invoice_id, f"Status: {invoice.status} -> {status}", user)
                invoice.status = status
                self._commit(session, invoices=[invoice_id])
                return True, message
        except GoBDError as e:
            return False, str(e)

    def cancel_invoice(self, invoice_id: int, user: str = None) -> int:
        """GoBD/UStG: an issued invoice is cancelled by a Stornorechnung with negated amounts."""
        with self.get_session() as session:
            original = session.get(Invoice, invoice_id)
            if not original:
                raise GoBDError("Rechnung nicht gefunden.")
            if not self.is_finalized(original):
                raise GoBDError("Ein Entwurf kann nicht storniert werden, er kann gelöscht werden.")
            if original.status == "Storniert":
                raise GoBDError("Diese Rechnung ist bereits storniert.")
            if original.cancels_invoice_id:
                raise GoBDError("Eine Stornorechnung kann nicht storniert werden.")

            items = session.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice_id).order_by(InvoiceItem.id).all()
            storno = Invoice(
                invoice_number=f"{DRAFT_PREFIX}{uuid.uuid4().hex}",
                customer_id=original.customer_id,
                invoice_date=datetime.combine(datetime.now().date(), datetime.min.time()),
                delivery_date=original.delivery_date,
                net_amount=0.0 - original.net_amount,
                tax_amount=0.0 - original.tax_amount,
                gross_amount=0.0 - original.gross_amount,
                credit_amount=0.0 - (original.credit_amount or 0.0),
                credit_desc=original.credit_desc,
                tax_exemption_reason=original.tax_exemption_reason,
                status="Storniert",
                cancels_invoice_id=original.id,
                payment_terms_days=original.payment_terms_days,
                seller_snapshot=original.seller_snapshot,
                customer_name=original.customer_name,
                customer_address=original.customer_address,
                customer_postal_code=original.customer_postal_code,
                customer_city=original.customer_city,
                customer_country=original.customer_country,
                customer_vat_id=original.customer_vat_id,
                customer_email=original.customer_email,
                customer_buyer_reference=original.customer_buyer_reference,
            )
            session.add(storno)
            session.flush()
            for item in items:
                session.add(InvoiceItem(
                    invoice_id=storno.id, title=item.title, description=item.description,
                    quantity=item.quantity, unit=item.unit, unit_price=0.0 - item.unit_price,
                    discount_percent=item.discount_percent, tax_percent=item.tax_percent,
                    total_price=0.0 - item.total_price
                ))
            self._log(session, "Invoice", storno.id, "Created", user)
            self._finalize(session, storno, user, f"Stornorechnung zu {original.invoice_number} festgeschrieben")

            self._log(session, "Invoice", original.id, f"Status: {original.status} -> Storniert (durch {storno.invoice_number})", user)
            original.status = "Storniert"
            storno_id = storno.id
            self._commit(session, invoices=[storno_id, original.id])
            return storno_id

    def refresh_overdue(self):
        """Marks issued, unpaid invoices past their due date as overdue (cheap scan of the cache)."""
        now = datetime.now()
        overdue = [i.id for i in self._caches["invoices"].by_id.values()
                   if i.status in ("Offen", "Teilbezahlt") and i.finalized_at and now > self.get_due_date(i)]
        if not overdue:
            return
        with self.get_session() as session:
            for invoice in session.query(Invoice).filter(Invoice.id.in_(overdue)).all():
                self._log(session, "Invoice", invoice.id, f"Status: {invoice.status} -> Überfällig (automatisch)", "System")
                invoice.status = "Überfällig"
            self._commit(session, invoices=overdue)

    def record_reminder(self, invoice_id: int, level: int, user: str = None):
        with self.get_session() as session:
            inv = session.get(Invoice, invoice_id)
            if not inv:
                return False
            if not self.is_finalized(inv):
                raise GoBDError("Für Entwürfe können keine Mahnungen erstellt werden.")
            if inv.status != "Überfällig":
                self._log(session, "Invoice", invoice_id, f"Status: {inv.status} -> Überfällig", user)
                inv.status = "Überfällig"
            inv.reminder_level = level
            inv.last_reminder_date = datetime.now(timezone.utc)
            self._log(session, "Invoice", invoice_id, f"{level}. Mahnung erstellt", user)
            self._commit(session, invoices=[invoice_id])
            return True

    def delete_invoice(self, invoice_id: int, user: str = None) -> bool:
        with self.get_session() as session:
            invoice = session.get(Invoice, invoice_id)
            if not invoice:
                return False
            if self.is_finalized(invoice):
                raise GoBDError("Festgeschriebene Rechnungen dürfen nicht gelöscht werden. Bitte stornieren.")
            self._log(session, "Invoice", invoice_id, "Entwurf gelöscht", user)
            session.delete(invoice)
            self._commit(session, invoices=[invoice_id])
            return True

    def archive_invoice(self, invoice_id: int, user: str = None):
        """Returns (success, message)."""
        try:
            with self.get_session() as session:
                invoice = session.get(Invoice, invoice_id)
                if not invoice or invoice.archived_at:
                    return False, "Rechnung ist bereits archiviert."
                if not self.is_finalized(invoice):
                    self._finalize(session, invoice, user)
                    if invoice.status == "Entwurf":
                        invoice.status = "Offen"
                invoice.archived_at = datetime.now(timezone.utc)
                self._log(session, "Invoice", invoice.id, "Archived", user)
                self._commit(session, invoices=[invoice_id])
                return True, ""
        except GoBDError as e:
            return False, str(e)

    def store_invoice_pdf(self, invoice_id: int, generated_pdf: str) -> str:
        """Archives the PDF of a finalized invoice exactly as issued. Returns the archive path."""
        with self.get_session() as session:
            invoice = session.get(Invoice, invoice_id)
            if not invoice or not self.is_finalized(invoice):
                raise GoBDError("Nur festgeschriebene Rechnungen werden archiviert.")
            if invoice.pdf_path:
                return invoice.pdf_path
            pdf_path, pdf_hash = archive_file(generated_pdf, paths.INVOICE_ARCHIVE_DIR, prefix=f"{invoice.invoice_number}_")
            invoice.pdf_path = pdf_path
            invoice.pdf_hash = pdf_hash
            self._log(session, "Invoice", invoice_id, "PDF archiviert")
            self._commit(session, invoices=[invoice_id])
            return pdf_path

    def get_archived_invoice_pdf(self, invoice: Invoice) -> Optional[str]:
        """Path of the archived PDF; raises GoBDError if the archived file was altered or removed."""
        if not invoice.pdf_path:
            return None
        if not verify_file(invoice.pdf_path, invoice.pdf_hash):
            raise GoBDError(f"Das archivierte PDF der Rechnung {invoice.invoice_number} fehlt oder wurde verändert!")
        return invoice.pdf_path

    def log_actions(self, document_type: str, document_ids: list, action: str):
        with self.get_session() as session:
            for document_id in document_ids:
                self._log(session, document_type, document_id, action)
            session.commit()
        self.db.save()

    # --- Quotes ---
    def get_next_quote_number(self, session: Session) -> str:
        prefix = f"A{datetime.now().year}-"
        return f"{prefix}{self._next_number(session, Quote.quote_number, prefix, len(prefix)):06d}"

    def create_quote(self, customer_id: int, quote_date: datetime, items: list, user: str = None, tax_exemption_reason: str = None) -> int:
        items = self._normalize_items(items)
        totals = calculate_totals(items)
        exemption_reason = self._exemption_reason(items, tax_exemption_reason)
        with self.get_session() as session:
            quote = Quote(
                quote_number=self.get_next_quote_number(session),
                customer_id=customer_id,
                quote_date=quote_date,
                net_amount=totals["net_amount"],
                tax_amount=totals["tax_amount"],
                gross_amount=totals["gross_amount"],
                tax_exemption_reason=exemption_reason
            )
            session.add(quote)
            session.flush()
            self._write_items(session, QuoteItem, "quote_id", quote.id, items)
            self._log(session, "Quote", quote.id, "Created", user)
            quote_id = quote.id
            self._commit(session, quotes=[quote_id])
            return quote_id

    def create_invoice_from_quote(self, quote_id: int, user: str = None) -> int:
        """Creates an invoice draft with the items of the quote."""
        quote = self.get_quote(quote_id)
        if not quote:
            raise ValueError("Angebot nicht gefunden.")
        today = datetime.combine(datetime.now().date(), datetime.min.time())
        items = [{"title": i.title, "description": i.description, "quantity": i.quantity, "unit": i.unit,
                  "unit_price": i.unit_price, "discount_percent": i.discount_percent, "tax_percent": i.tax_percent}
                 for i in quote.items]
        invoice_id = self.create_invoice(quote.customer_id, today, today, items, user,
                                         tax_exemption_reason=quote.tax_exemption_reason)
        self.log_actions("Quote", [quote_id], f"In Rechnung übernommen (Entwurf #{invoice_id})")
        if quote.status in ("Entwurf", "Versendet"):
            self.update_quote_status(quote_id, "Angenommen", user)
        return invoice_id

    def get_quotes(self) -> list:
        return self._caches["quotes"].sorted()

    def get_quote(self, quote_id: int) -> Optional[Quote]:
        """Quote including its items (the list cache only holds the header data)."""
        if quote_id not in self._caches["quotes"].by_id:
            return None
        with self.get_session() as session:
            return session.query(Quote).options(selectinload(Quote.items)).filter(Quote.id == quote_id).first()

    def update_quote(self, quote_id: int, customer_id: int, quote_date: datetime, items: list, user: str = None, **kwargs):
        items = self._normalize_items(items)
        totals = calculate_totals(items)
        exemption_reason = self._exemption_reason(items, kwargs.get("tax_exemption_reason"))
        with self.get_session() as session:
            quote = session.get(Quote, quote_id)
            if not quote: return False
            if quote.archived_at:
                raise GoBDError(f"Angebot {quote.quote_number} ist archiviert und kann nicht mehr geändert werden.")
            quote.tax_exemption_reason = exemption_reason
            quote.customer_id = customer_id
            quote.quote_date = quote_date
            quote.net_amount = totals["net_amount"]
            quote.tax_amount = totals["tax_amount"]
            quote.gross_amount = totals["gross_amount"]
            self._write_items(session, QuoteItem, "quote_id", quote_id, items)
            self._log(session, "Quote", quote_id, "Updated", user)
            self._commit(session, quotes=[quote_id])
            return True

    def update_quote_status(self, quote_id: int, status: str, user: str = None):
        if status not in QUOTE_STATUSES:
            raise ValueError(f"Unbekannter Status: {status}")
        with self.get_session() as session:
            quote = session.get(Quote, quote_id)
            if not quote or quote.status == status:
                return False
            self._log(session, "Quote", quote_id, f"Status: {quote.status} -> {status}", user)
            quote.status = status
            self._commit(session, quotes=[quote_id])
            return True

    def archive_quote(self, quote_id: int, user: str = None):
        with self.get_session() as session:
            quote = session.get(Quote, quote_id)
            if quote and not quote.archived_at:
                quote.archived_at = datetime.now(timezone.utc)
                self._log(session, "Quote", quote.id, "Archived", user)
                self._commit(session, quotes=[quote_id])
                return True
            return False

    def delete_quote(self, quote_id: int, user: str = None) -> bool:
        with self.get_session() as session:
            quote = session.get(Quote, quote_id)
            if not quote:
                return False
            if quote.archived_at:
                raise GoBDError("Archivierte Angebote dürfen nicht gelöscht werden.")
            self._log(session, "Quote", quote_id, "Deleted", user)
            session.delete(quote)
            self._commit(session, quotes=[quote_id])
            return True

    # --- Incoming Invoices ---
    def add_incoming_invoice(self, invoice_type: str, date: datetime, amount: float, description: str, source_path: str,
                             user: str = None, einvoice_format: str = None, invoice_number: str = None, supplier_name: str = None) -> int:
        if not (is_pdf(source_path) or (source_path.lower().endswith(".xml") and einvoice_format)):
            raise ValueError("Eingangsrechnungen müssen als PDF oder als XRechnung (XML) vorliegen.")
        file_path, file_hash = archive_file(source_path, paths.INCOMING_INVOICES_DIR)
        with self.get_session() as session:
            entry = IncomingInvoice(
                invoice_type=invoice_type,
                date=date,
                amount=amount,
                description=description,
                file_path=file_path,
                file_hash=file_hash,
                einvoice_format=einvoice_format,
                invoice_number=invoice_number,
                supplier_name=supplier_name,
            )
            session.add(entry)
            session.flush()
            self._log(session, "IncomingInvoice", entry.id, "Created", user)
            entry_id = entry.id
            self._commit(session, incoming=[entry_id])
            return entry_id

    def get_incoming_invoices(self, invoice_type: str = None, include_cancelled: bool = True) -> List[IncomingInvoice]:
        invoices = self._caches["incoming"].sorted()
        if invoice_type:
            invoices = [i for i in invoices if i.invoice_type == invoice_type]
        if not include_cancelled:
            invoices = [i for i in invoices if not i.cancelled_at]
        return invoices

    def get_incoming_invoice(self, invoice_id: int) -> Optional[IncomingInvoice]:
        return self._caches["incoming"].by_id.get(invoice_id)

    def cancel_incoming_invoice(self, invoice_id: int, user: str = None) -> bool:
        """GoBD: received invoices and their files are retained; they are only marked as cancelled."""
        with self.get_session() as session:
            entry = session.get(IncomingInvoice, invoice_id)
            if not entry or entry.cancelled_at:
                return False
            entry.cancelled_at = datetime.now(timezone.utc)
            self._log(session, "IncomingInvoice", invoice_id, "Storniert", user)
            self._commit(session, incoming=[invoice_id])
            return True

    # --- GoBD integrity check ---
    def verify_integrity(self, check_files: bool = True) -> List[str]:
        """
        Recomputes all hash chains and (optionally) the hashes of all archived files.
        Returns a list of problems (empty = OK).
        """
        with self.get_session() as session:
            return self._verify(session, check_files)

    def verify_integrity_async(self, on_done: Callable[[List[str]], None], check_files: bool = False):
        """Runs the check on a worker thread with its own in-memory copy, so the UI never waits."""
        snapshot = self.db.memory_conn.serialize()

        def run():
            try:
                conn = sqlite3.connect(":memory:", check_same_thread=False)
                conn.deserialize(snapshot)
                engine = create_engine("sqlite://", creator=lambda: conn, poolclass=StaticPool)
                with Session(engine) as session:
                    problems = self._verify(session, check_files)
                conn.close()
            except Exception as e:
                logger.exception("Integritätsprüfung fehlgeschlagen")
                problems = [f"Die Integritätsprüfung ist fehlgeschlagen: {e}"]
            on_done(problems)

        threading.Thread(target=run, name="schalk-integrity-check", daemon=True).start()

    def _verify(self, session: Session, check_files: bool) -> List[str]:
        problems = []
        prev = "GENESIS"
        for entry in session.execute(select(CashbookEntry.__table__).order_by(CashbookEntry.id)):
            if not entry.hash_chain or self._hash_record(self._cashbook_hash_payload(entry), prev) != entry.hash_chain:
                problems.append(f"Kassenbuch: Eintrag {entry.receipt_number} wurde verändert oder die Kette ist unterbrochen.")
            if check_files and entry.attachment_path and not verify_file(entry.attachment_path, entry.attachment_hash):
                problems.append(f"Kassenbuch: Beleg zu {entry.receipt_number} fehlt oder wurde verändert.")
            prev = entry.hash_chain or prev

        # Plain rows instead of ORM objects: fast even with tens of thousands of invoices
        items_by_invoice = {}
        for item in session.execute(select(InvoiceItem.__table__).order_by(InvoiceItem.id)):
            items_by_invoice.setdefault(item.invoice_id, []).append(item)
        prev = "GENESIS"
        invoices = select(Invoice.__table__).where(Invoice.finalized_at != None).order_by(Invoice.finalized_at, Invoice.id)
        for inv in session.execute(invoices):
            if not inv.hash_chain or self._hash_record(self._invoice_hash_payload(inv, items_by_invoice.get(inv.id, [])), prev) != inv.hash_chain:
                problems.append(f"Rechnung {inv.invoice_number} wurde verändert oder die Kette ist unterbrochen.")
            if check_files and inv.pdf_path and not verify_file(inv.pdf_path, inv.pdf_hash):
                problems.append(f"Archiv-PDF der Rechnung {inv.invoice_number} fehlt oder wurde verändert.")
            prev = inv.hash_chain or prev

        if not check_files:
            return problems
        for inv in session.query(IncomingInvoice).order_by(IncomingInvoice.id).all():
            if not verify_file(inv.file_path, inv.file_hash):
                problems.append(f"Eingangsrechnung '{inv.description}' ({inv.date.strftime('%d.%m.%Y')}): Datei fehlt oder wurde verändert.")
        return problems
