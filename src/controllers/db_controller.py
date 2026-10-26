import getpass
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from sqlalchemy.orm import Session, joinedload
from src.models.database import DatabaseManager, Setting, Customer, Invoice, InvoiceItem, Quote, QuoteItem, CashbookEntry, DocumentHistory, IncomingInvoice
from src.utils.signal_bus import SignalBus
from src.utils.calculations import calculate_totals, item_total
from src.utils.tax import has_zero_rate, EXEMPTION_REQUIRED_MESSAGE
from src.utils.archive import archive_file, verify_file
from src.utils import paths

DRAFT_PREFIX = "ENTWURF-"
INVOICE_STATUSES = ["Entwurf", "Offen", "Teilbezahlt", "Bezahlt", "Überfällig", "Storniert"]
CASHBOOK_INCOME_TYPES = ["Einnahme"]


class GoBDError(Exception):
    """Raised when an action would violate GoBD rules (e.g. editing a finalized invoice)."""


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


class DBController:
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self._cache = {
            'invoices': None,
            'quotes': None,
            'customers': None,
            'cashbook': None,
            'incoming_invoices_lieferant': None,
            'incoming_invoices_sonstige': None,
        }
        self.invalidate_cache()

    def invalidate_cache(self):
        with self.get_session() as session:
            self._cache['customers'] = session.query(Customer).order_by(Customer.company_name, Customer.last_name).all()

            invoices = session.query(Invoice).options(joinedload(Invoice.customer), joinedload(Invoice.items)).order_by(Invoice.invoice_date.desc(), Invoice.id.desc()).all()

            now = datetime.now()
            payment_terms = self._payment_terms(session)
            changed = False
            for inv in invoices:
                # Only issued, unpaid invoices can become overdue (never drafts)
                if inv.status in ["Offen", "Teilbezahlt"] and inv.invoice_date:
                    if now > self._due_date(inv, payment_terms):
                        self._log(session, "Invoice", inv.id, f"Status: {inv.status} -> Überfällig (automatisch)")
                        inv.status = "Überfällig"
                        changed = True

            if changed:
                session.commit()
                self.db.save()

            self._cache['invoices'] = invoices
            self._cache['quotes'] = session.query(Quote).options(joinedload(Quote.customer), joinedload(Quote.items)).order_by(Quote.quote_date.desc(), Quote.id.desc()).all()
            self._cache['cashbook'] = session.query(CashbookEntry).order_by(CashbookEntry.entry_date.desc(), CashbookEntry.id.desc()).all()
            self._cache['incoming_invoices_lieferant'] = session.query(IncomingInvoice).filter(IncomingInvoice.invoice_type == "Lieferant").order_by(IncomingInvoice.date.desc()).all()
            self._cache['incoming_invoices_sonstige'] = session.query(IncomingInvoice).filter(IncomingInvoice.invoice_type == "Sonstige").order_by(IncomingInvoice.date.desc()).all()

    def get_session(self) -> Session:
        return self.db.Session()

    def _commit(self, session: Session, *signals):
        """Commits, persists the encrypted file, refreshes the cache and notifies the views."""
        session.commit()
        self.db.save()
        self.invalidate_cache()
        bus = SignalBus.get()
        for signal_name, entity_id in signals:
            getattr(bus, signal_name).emit(entity_id)
        bus.dataChanged.emit()

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
        with self.get_session() as session:
            setting = session.query(Setting).filter(Setting.key == key).first()
            return setting.value if setting else default

    def set_setting(self, key: str, value: str):
        self.set_settings({key: value})

    def set_settings(self, values: dict):
        with self.get_session() as session:
            for key, value in values.items():
                setting = session.query(Setting).filter(Setting.key == key).first()
                if setting:
                    setting.value = value
                else:
                    session.add(Setting(key=key, value=value))
            self._commit(session)

    def _payment_terms(self, session: Session = None) -> int:
        if session is None:
            value = self.get_setting("payment_terms_days")
        else:
            setting = session.query(Setting).filter(Setting.key == "payment_terms_days").first()
            value = setting.value if setting else ""
        try:
            return int(value) if value else 14
        except ValueError:
            return 14

    def get_payment_terms(self) -> int:
        return self._payment_terms()

    def _due_date(self, invoice: Invoice, payment_terms: int) -> datetime:
        return invoice.invoice_date.replace(tzinfo=None) + timedelta(days=payment_terms)

    def get_due_date(self, invoice: Invoice) -> datetime:
        return self._due_date(invoice, self._payment_terms())

    # --- Cashbook (GoBD) ---
    def get_last_cashbook_hash(self, session: Session = None) -> str:
        if session is None:
            with self.get_session() as own_session:
                return self.get_last_cashbook_hash(own_session)
        last_entry = session.query(CashbookEntry).order_by(CashbookEntry.id.desc()).first()
        return last_entry.hash_chain if last_entry and last_entry.hash_chain else "GENESIS"

    def get_next_receipt_number(self, session: Session = None) -> str:
        if session is None:
            with self.get_session() as own_session:
                return self.get_next_receipt_number(own_session)
        year = datetime.now().year
        numbers = session.query(CashbookEntry.receipt_number).filter(CashbookEntry.receipt_number.like(f"K{year}-%")).all()
        last_num = max((int(n.split('-')[1]) for (n,) in numbers if n.split('-')[1].isdigit()), default=0)
        return f"K{year}-{last_num + 1:06d}"

    @staticmethod
    def cashbook_signed_amount(entry) -> float:
        """Effect of an entry on the cash balance (income positive, withdrawals negative)."""
        return entry.amount if entry.entry_type in CASHBOOK_INCOME_TYPES else -entry.amount

    def get_cashbook_balance(self) -> float:
        return round(sum(self.cashbook_signed_amount(e) for e in self._cache['cashbook']), 2)

    @staticmethod
    def _cashbook_hash_payload(entry: CashbookEntry) -> str:
        return "|".join(str(v) for v in [
            entry.id, _iso(entry.entry_date), _num(entry.amount), entry.receipt_number, entry.description,
            entry.entry_type, entry.attachment_hash or "", int(bool(entry.is_storno)), entry.storno_of_id or ""
        ])

    def _add_cashbook_row(self, session: Session, user: str = None, **fields) -> CashbookEntry:
        prev_hash = self.get_last_cashbook_hash(session)
        entry = CashbookEntry(receipt_number=self.get_next_receipt_number(session), **fields)
        session.add(entry)
        session.flush() # Get ID
        entry.hash_chain = self._hash_record(self._cashbook_hash_payload(entry), prev_hash)
        self._log(session, "Cashbook", entry.id, "Storniert-Gegenbuchung" if entry.is_storno else "Created", user)
        return entry

    def add_cashbook_entry(self, entry_date: datetime, amount: float, description: str, category: str, entry_type: str, tax_percent: float, attachment_source: str = None, user: str = None) -> int:
        if amount <= 0:
            raise ValueError("Der Betrag muss größer als 0 sein.")
        signed = amount if entry_type in CASHBOOK_INCOME_TYPES else -amount
        if self.get_cashbook_balance() + signed < 0:
            raise ValueError("Der Kassenbestand darf nicht negativ werden!")

        attachment_path, attachment_hash = None, None
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
            self._commit(session, ("cashbookAdded", entry_id))
            return entry_id

    def storno_cashbook_entry(self, entry_id: int, user: str = None) -> int:
        """GoBD: entries are never changed or deleted; a correction is a reversing entry."""
        with self.get_session() as session:
            original = session.query(CashbookEntry).filter(CashbookEntry.id == entry_id).first()
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
            entry_id = entry.id
            self._commit(session, ("cashbookAdded", entry_id))
            return entry_id

    def get_cashbook_entries(self):
        return self._cache['cashbook']

    def get_cashbook_entry(self, entry_id: int) -> Optional[CashbookEntry]:
        return next((e for e in self._cache['cashbook'] if e.id == entry_id), None)

    @staticmethod
    def get_cashbook_attachment(entry) -> Optional[str]:
        return entry.attachment_path

    # --- Customers ---
    def add_customer(self, **kwargs):
        with self.get_session() as session:
            customer = Customer(**kwargs)
            session.add(customer)
            session.flush()
            customer_id = customer.id
            self._commit(session, ("customerAdded", customer_id))
            return customer_id

    def update_customer(self, customer_id: int, **kwargs):
        with self.get_session() as session:
            customer = session.query(Customer).filter(Customer.id == customer_id).first()
            if customer:
                for key, value in kwargs.items():
                    setattr(customer, key, value)
                self._commit(session, ("customerUpdated", customer_id))

    def delete_customer(self, customer_id: int):
        with self.get_session() as session:
            invoices = session.query(Invoice).filter(Invoice.customer_id == customer_id).count()
            quotes = session.query(Quote).filter(Quote.customer_id == customer_id).count()
            if invoices > 0 or quotes > 0:
                reasons = []
                if invoices > 0: reasons.append(f"{invoices} Rechnungen")
                if quotes > 0: reasons.append(f"{quotes} Angebote")
                return False, " und ".join(reasons)

            customer = session.query(Customer).filter(Customer.id == customer_id).first()
            if customer:
                session.delete(customer)
                self._commit(session, ("customerDeleted", customer_id))
                return True, ""
            return False, "Kunde nicht gefunden"

    def get_customers(self):
        return self._cache['customers']

    def get_customer(self, customer_id: int) -> Optional[Customer]:
        return next((c for c in self._cache['customers'] if c.id == customer_id), None)

    # --- Items (shared by invoices and quotes) ---
    @staticmethod
    def _normalize_items(items: list) -> list:
        normalized = []
        for item in items:
            quantity = float(item.get('quantity', 1.0))
            unit_price = float(item['unit_price'])
            discount = float(item.get('discount_percent') or 0.0)
            normalized.append({
                "title": item['title'],
                "description": item.get('description'),
                "quantity": quantity,
                "unit": item.get('unit') or "Stück",
                "unit_price": unit_price,
                "discount_percent": discount,
                "tax_percent": float(item.get('tax_percent', 19.0)),
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

    # --- Invoices ---
    @staticmethod
    def is_finalized(invoice: Invoice) -> bool:
        return invoice.finalized_at is not None

    def get_next_invoice_number(self, session: Session = None) -> str:
        # Format: RE + year + month + running number per year (at least 3 digits)
        if session is None:
            with self.get_session() as own_session:
                return self.get_next_invoice_number(own_session)
        now = datetime.now()
        prefix = f"RE{now.year}"
        numbers = session.query(Invoice.invoice_number).filter(Invoice.invoice_number.like(f"{prefix}%")).all()
        last_num = 0
        for (number,) in numbers:
            suffix = number[len(prefix) + 2:]
            if suffix.isdigit():
                last_num = max(last_num, int(suffix))
        return f"{prefix}{now.month:02d}{last_num + 1:03d}"

    def _invoice_hash_payload(self, session: Session, invoice: Invoice) -> str:
        items = session.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice.id).order_by(InvoiceItem.id).all()
        payload = {
            "id": invoice.id,
            "number": invoice.invoice_number,
            "invoice_date": _iso(invoice.invoice_date),
            "delivery_date": _iso(invoice.delivery_date),
            "finalized_at": _iso(invoice.finalized_at),
            "customer": [invoice.customer_name, invoice.customer_address, invoice.customer_postal_code,
                         invoice.customer_city, invoice.customer_country, invoice.customer_vat_id],
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
        """GoBD: assigns the final number, freezes recipient data and seals the invoice in the hash chain."""
        if invoice.finalized_at:
            return
        session.flush()
        if invoice.invoice_number.startswith(DRAFT_PREFIX):
            invoice.invoice_number = self.get_next_invoice_number(session)
        if not invoice.customer_name:
            customer = session.query(Customer).filter(Customer.id == invoice.customer_id).first()
            if customer:
                name = customer.company_name or f"{customer.first_name or ''} {customer.last_name or ''}".strip()
                invoice.customer_name = name
                invoice.customer_address = customer.address
                invoice.customer_postal_code = customer.postal_code
                invoice.customer_city = customer.city
                invoice.customer_country = customer.country
                invoice.customer_vat_id = customer.vat_id
        invoice.finalized_at = datetime.now(timezone.utc)
        session.flush()
        invoice.hash_chain = self._hash_record(self._invoice_hash_payload(session, invoice), self._last_invoice_hash(session, invoice.id))
        self._log(session, "Invoice", invoice.id, f"{action} als {invoice.invoice_number}", user)

    def _write_items(self, session: Session, model, fk_name: str, parent_id: int, items: list):
        session.query(model).filter(getattr(model, fk_name) == parent_id).delete()
        for item_data in items:
            session.add(model(**{fk_name: parent_id}, **item_data))

    def create_invoice(self, customer_id: int, invoice_date: datetime, delivery_date: datetime, items: list, user: str = None, **kwargs):
        items = self._normalize_items(items)
        credit_amount = kwargs.get("credit_amount", 0.0) or 0.0
        totals = calculate_totals(items, credit_amount)
        status = kwargs.get("status", "Entwurf")
        exemption_reason = self._exemption_reason(items, kwargs.get("tax_exemption_reason"))

        with self.get_session() as session:
            invoice = Invoice(
                # Final numbers are only assigned on finalization, so cancelled drafts leave no gaps
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
            self._commit(session, ("invoiceAdded", invoice_id))
            return invoice_id

    def get_invoices(self):
        return self._cache['invoices']

    def get_invoice(self, invoice_id: int):
        with self.get_session() as session:
            return session.query(Invoice).options(joinedload(Invoice.customer), joinedload(Invoice.items)).filter(Invoice.id == invoice_id).first()

    def update_invoice(self, invoice_id: int, customer_id: int, invoice_date: datetime, delivery_date: datetime, items: list, user: str = None, **kwargs):
        with self.get_session() as session:
            invoice = session.query(Invoice).filter(Invoice.id == invoice_id).first()
            if not invoice: return False
            if self.is_finalized(invoice):
                raise GoBDError(f"Rechnung {invoice.invoice_number} ist festgeschrieben und kann nicht mehr geändert werden. Bitte stornieren.")

            items = self._normalize_items(items)
            credit_amount = kwargs.get("credit_amount", 0.0) or 0.0
            totals = calculate_totals(items, credit_amount)
            exemption_reason = self._exemption_reason(items, kwargs.get("tax_exemption_reason"))

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

            self._commit(session, ("invoiceUpdated", invoice_id))
            return True

    def allowed_invoice_statuses(self, invoice: Invoice) -> list:
        if invoice.status == "Storniert":
            return ["Storniert"]
        if not self.is_finalized(invoice):
            return ["Entwurf", "Offen", "Bezahlt"]
        return ["Offen", "Teilbezahlt", "Bezahlt", "Überfällig", "Storniert"]

    def update_invoice_status(self, invoice_id: int, status: str, user: str = None):
        """Returns (success, message)."""
        if status == "Storniert":
            try:
                storno_id = self.cancel_invoice(invoice_id, user)
            except GoBDError as e:
                return False, str(e)
            storno = self.get_invoice(storno_id)
            return True, f"Stornorechnung {storno.invoice_number} wurde erstellt."

        with self.get_session() as session:
            invoice = session.query(Invoice).filter(Invoice.id == invoice_id).first()
            if not invoice:
                return False, "Rechnung nicht gefunden."
            if invoice.status == status:
                return True, ""
            if status not in self.allowed_invoice_statuses(invoice):
                if status == "Entwurf":
                    return False, "Eine festgeschriebene Rechnung kann nicht wieder zum Entwurf werden."
                return False, f"Statuswechsel von '{invoice.status}' nach '{status}' ist nicht erlaubt."

            message = ""
            if status != "Entwurf" and not self.is_finalized(invoice):
                self._finalize(session, invoice, user)
                message = f"Rechnung wurde als {invoice.invoice_number} festgeschrieben."
            self._log(session, "Invoice", invoice_id, f"Status: {invoice.status} -> {status}", user)
            invoice.status = status
            self._commit(session)
            return True, message

    def cancel_invoice(self, invoice_id: int, user: str = None) -> int:
        """GoBD/UStG: an issued invoice is cancelled by a Stornorechnung with negated amounts."""
        with self.get_session() as session:
            original = session.query(Invoice).filter(Invoice.id == invoice_id).first()
            if not original:
                raise GoBDError("Rechnung nicht gefunden.")
            if not self.is_finalized(original):
                raise GoBDError("Ein Entwurf kann nicht storniert werden, er kann gelöscht werden.")
            if original.status == "Storniert":
                raise GoBDError("Diese Rechnung ist bereits storniert.")

            items = session.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice_id).order_by(InvoiceItem.id).all()
            storno = Invoice(
                invoice_number=f"{DRAFT_PREFIX}{uuid.uuid4().hex}",
                customer_id=original.customer_id,
                invoice_date=datetime.combine(datetime.now().date(), datetime.min.time()),
                delivery_date=original.delivery_date,
                net_amount=-original.net_amount,
                tax_amount=-original.tax_amount,
                gross_amount=-original.gross_amount,
                credit_amount=-(original.credit_amount or 0.0),
                credit_desc=original.credit_desc,
                tax_exemption_reason=original.tax_exemption_reason,
                status="Storniert",
                cancels_invoice_id=original.id,
                customer_name=original.customer_name,
                customer_address=original.customer_address,
                customer_postal_code=original.customer_postal_code,
                customer_city=original.customer_city,
                customer_country=original.customer_country,
                customer_vat_id=original.customer_vat_id,
            )
            session.add(storno)
            session.flush()
            for item in items:
                session.add(InvoiceItem(
                    invoice_id=storno.id, title=item.title, description=item.description,
                    quantity=item.quantity, unit=item.unit, unit_price=-item.unit_price,
                    discount_percent=item.discount_percent, tax_percent=item.tax_percent,
                    total_price=-item.total_price
                ))
            self._log(session, "Invoice", storno.id, "Created", user)
            self._finalize(session, storno, user, f"Stornorechnung zu {original.invoice_number} festgeschrieben")

            self._log(session, "Invoice", original.id, f"Status: {original.status} -> Storniert (durch {storno.invoice_number})", user)
            original.status = "Storniert"
            storno_id = storno.id
            self._commit(session, ("invoiceAdded", storno_id))
            return storno_id

    def record_reminder(self, invoice_id: int, level: int, user: str = None):
        with self.get_session() as session:
            inv = session.query(Invoice).filter(Invoice.id == invoice_id).first()
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
            self._commit(session)
            return True

    def update_reminder_level(self, invoice_id: int, level: int, date: datetime):
        with self.get_session() as session:
            inv = session.query(Invoice).filter(Invoice.id == invoice_id).first()
            if inv:
                inv.reminder_level = level
                inv.last_reminder_date = date
                self._log(session, "Invoice", invoice_id, f"Mahnstufe auf {level} gesetzt")
                self._commit(session)
                return True
            return False

    def delete_invoice(self, invoice_id: int, user: str = None) -> bool:
        with self.get_session() as session:
            invoice = session.query(Invoice).filter(Invoice.id == invoice_id).first()
            if not invoice:
                return False
            if self.is_finalized(invoice):
                raise GoBDError("Festgeschriebene Rechnungen dürfen nicht gelöscht werden. Bitte stornieren.")
            self._log(session, "Invoice", invoice_id, "Entwurf gelöscht", user)
            session.delete(invoice)
            self._commit(session, ("invoiceDeleted", invoice_id))
            return True

    def archive_invoice(self, invoice_id: int, user: str = None):
        with self.get_session() as session:
            invoice = session.query(Invoice).filter(Invoice.id == invoice_id).first()
            if invoice and not invoice.archived_at:
                if not self.is_finalized(invoice):
                    self._finalize(session, invoice, user)
                    if invoice.status == "Entwurf":
                        invoice.status = "Offen"
                invoice.archived_at = datetime.now(timezone.utc)
                self._log(session, "Invoice", invoice.id, "Archived", user)
                self._commit(session, ("invoiceUpdated", invoice_id))
                return True
            return False

    def store_invoice_pdf(self, invoice_id: int, generated_pdf: str) -> str:
        """Archives the PDF of a finalized invoice exactly as issued. Returns the archive path."""
        with self.get_session() as session:
            invoice = session.query(Invoice).filter(Invoice.id == invoice_id).first()
            if not invoice or not self.is_finalized(invoice):
                raise GoBDError("Nur festgeschriebene Rechnungen werden archiviert.")
            if invoice.pdf_path:
                return invoice.pdf_path
            pdf_path, pdf_hash = archive_file(generated_pdf, paths.INVOICE_ARCHIVE_DIR, prefix=f"{invoice.invoice_number}_")
            invoice.pdf_path = pdf_path
            invoice.pdf_hash = pdf_hash
            self._log(session, "Invoice", invoice_id, "PDF archiviert")
            self._commit(session)
            return pdf_path

    def get_archived_invoice_pdf(self, invoice: Invoice) -> Optional[str]:
        """Path of the archived PDF; raises GoBDError if the archived file was altered or removed."""
        if not invoice.pdf_path:
            return None
        if not verify_file(invoice.pdf_path, invoice.pdf_hash):
            raise GoBDError(f"Das archivierte PDF der Rechnung {invoice.invoice_number} fehlt oder wurde verändert!")
        return invoice.pdf_path

    # --- Quotes ---
    def get_next_quote_number(self, session: Session = None) -> str:
        if session is None:
            with self.get_session() as own_session:
                return self.get_next_quote_number(own_session)
        year = datetime.now().year
        numbers = session.query(Quote.quote_number).filter(Quote.quote_number.like(f"A{year}-%")).all()
        last_num = max((int(n.split('-')[1]) for (n,) in numbers if n.split('-')[1].isdigit()), default=0)
        return f"A{year}-{last_num + 1:06d}"

    def create_quote(self, customer_id: int, quote_date: datetime, items: list, user: str = None, tax_exemption_reason: str = None):
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
            self._commit(session, ("quoteAdded", quote_id))
            return quote_id

    def get_quotes(self):
        return self._cache['quotes']

    def get_quote(self, quote_id: int):
        with self.get_session() as session:
            return session.query(Quote).options(joinedload(Quote.customer), joinedload(Quote.items)).filter(Quote.id == quote_id).first()

    def update_quote(self, quote_id: int, customer_id: int, quote_date: datetime, items: list, user: str = None, **kwargs):
        with self.get_session() as session:
            quote = session.query(Quote).filter(Quote.id == quote_id).first()
            if not quote: return False
            if quote.archived_at:
                raise GoBDError(f"Angebot {quote.quote_number} ist archiviert und kann nicht mehr geändert werden.")

            items = self._normalize_items(items)
            totals = calculate_totals(items)
            quote.tax_exemption_reason = self._exemption_reason(items, kwargs.get("tax_exemption_reason"))
            quote.customer_id = customer_id
            quote.quote_date = quote_date
            if "status" in kwargs:
                quote.status = kwargs["status"]
            quote.net_amount = totals["net_amount"]
            quote.tax_amount = totals["tax_amount"]
            quote.gross_amount = totals["gross_amount"]
            self._write_items(session, QuoteItem, "quote_id", quote_id, items)
            self._log(session, "Quote", quote_id, "Updated", user)
            self._commit(session, ("quoteUpdated", quote_id))
            return True

    def update_quote_status(self, quote_id: int, status: str, user: str = None):
        with self.get_session() as session:
            quote = session.query(Quote).filter(Quote.id == quote_id).first()
            if quote:
                self._log(session, "Quote", quote_id, f"Status: {quote.status} -> {status}", user)
                quote.status = status
                self._commit(session)
                return True
            return False

    def archive_quote(self, quote_id: int, user: str = None):
        with self.get_session() as session:
            quote = session.query(Quote).filter(Quote.id == quote_id).first()
            if quote and not quote.archived_at:
                quote.archived_at = datetime.now(timezone.utc)
                self._log(session, "Quote", quote.id, "Archived", user)
                self._commit(session, ("quoteUpdated", quote_id))
                return True
            return False

    def delete_quote(self, quote_id: int, user: str = None) -> bool:
        with self.get_session() as session:
            quote = session.query(Quote).filter(Quote.id == quote_id).first()
            if quote:
                if quote.archived_at:
                    raise GoBDError("Archivierte Angebote dürfen nicht gelöscht werden.")
                self._log(session, "Quote", quote_id, "Deleted", user)
                session.delete(quote)
                self._commit(session, ("quoteDeleted", quote_id))
                return True
            return False

    # --- Incoming Invoices ---
    def add_incoming_invoice(self, invoice_type: str, date: datetime, amount: float, description: str, source_path: str, user: str = None):
        file_path, file_hash = archive_file(source_path, paths.INCOMING_INVOICES_DIR)
        with self.get_session() as session:
            try:
                entry = IncomingInvoice(
                    invoice_type=invoice_type,
                    date=date,
                    amount=amount,
                    description=description,
                    file_path=file_path,
                    file_hash=file_hash
                )
                session.add(entry)
                session.flush()
                self._log(session, "IncomingInvoice", entry.id, "Created", user)
                entry_id = entry.id
                self._commit(session, ("incomingInvoiceAdded", entry_id))
                return entry_id
            except Exception as e:
                session.rollback()
                print(f"Error adding incoming invoice: {e}")
                return None

    def get_incoming_invoices(self, invoice_type: str = None, include_cancelled: bool = True) -> List[IncomingInvoice]:
        if invoice_type == "Lieferant":
            invoices = self._cache['incoming_invoices_lieferant']
        elif invoice_type == "Sonstige":
            invoices = self._cache['incoming_invoices_sonstige']
        else:
            invoices = self._cache['incoming_invoices_lieferant'] + self._cache['incoming_invoices_sonstige']
        if not include_cancelled:
            invoices = [i for i in invoices if not i.cancelled_at]
        return invoices

    def get_incoming_invoice(self, invoice_id: int) -> Optional[IncomingInvoice]:
        return next((i for i in self.get_incoming_invoices() if i.id == invoice_id), None)

    def cancel_incoming_invoice(self, invoice_id: int, user: str = None) -> bool:
        """GoBD: received invoices and their files are retained; they are only marked as cancelled."""
        with self.get_session() as session:
            entry = session.query(IncomingInvoice).filter(IncomingInvoice.id == invoice_id).first()
            if not entry or entry.cancelled_at:
                return False
            entry.cancelled_at = datetime.now(timezone.utc)
            self._log(session, "IncomingInvoice", invoice_id, "Storniert", user)
            self._commit(session, ("incomingInvoiceUpdated", invoice_id))
            return True

    # --- GoBD integrity check ---
    def verify_integrity(self) -> List[str]:
        """Recomputes all hash chains and file hashes. Returns a list of problems (empty = OK)."""
        problems = []
        with self.get_session() as session:
            prev = "GENESIS"
            for entry in session.query(CashbookEntry).order_by(CashbookEntry.id).all():
                if not entry.hash_chain or self._hash_record(self._cashbook_hash_payload(entry), prev) != entry.hash_chain:
                    problems.append(f"Kassenbuch: Eintrag {entry.receipt_number} wurde verändert oder die Kette ist unterbrochen.")
                if entry.attachment_path and not verify_file(entry.attachment_path, entry.attachment_hash):
                    problems.append(f"Kassenbuch: Beleg zu {entry.receipt_number} fehlt oder wurde verändert.")
                prev = entry.hash_chain or prev

            prev = "GENESIS"
            for inv in session.query(Invoice).filter(Invoice.finalized_at != None).order_by(Invoice.finalized_at, Invoice.id).all():
                if not inv.hash_chain or self._hash_record(self._invoice_hash_payload(session, inv), prev) != inv.hash_chain:
                    problems.append(f"Rechnung {inv.invoice_number} wurde verändert oder die Kette ist unterbrochen.")
                if inv.pdf_path and not verify_file(inv.pdf_path, inv.pdf_hash):
                    problems.append(f"Archiv-PDF der Rechnung {inv.invoice_number} fehlt oder wurde verändert.")
                prev = inv.hash_chain or prev

            for inv in session.query(IncomingInvoice).order_by(IncomingInvoice.id).all():
                if inv.file_hash and not verify_file(inv.file_path, inv.file_hash):
                    problems.append(f"Eingangsrechnung '{inv.description}' ({inv.date.strftime('%d.%m.%Y')}): Datei fehlt oder wurde verändert.")
                elif not inv.file_hash and not os.path.isfile(inv.file_path):
                    problems.append(f"Eingangsrechnung '{inv.description}' ({inv.date.strftime('%d.%m.%Y')}): Datei fehlt.")
        return problems
