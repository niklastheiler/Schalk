import hashlib
from datetime import datetime, timezone
from typing import List, Optional
from sqlalchemy.orm import Session
from src.models.database import DatabaseManager, Setting, Customer, Invoice, InvoiceItem, Quote, QuoteItem, CashbookEntry, DocumentHistory, IncomingInvoice
from src.utils.signal_bus import SignalBus

class DBController:
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        
        # Auto-migrate schema if needed
        with self.get_session() as session:
            try:
                from sqlalchemy import text
                session.execute(text("ALTER TABLE invoices ADD COLUMN credit_amount FLOAT DEFAULT 0.0"))
                session.execute(text("ALTER TABLE invoices ADD COLUMN credit_desc VARCHAR"))
                session.commit()
            except Exception:
                session.rollback()
                
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
        from sqlalchemy.orm import joinedload
        from datetime import datetime
        with self.get_session() as session:
            self._cache['customers'] = session.query(Customer).order_by(Customer.company_name, Customer.last_name).all()
            
            invoices = session.query(Invoice).options(joinedload(Invoice.customer), joinedload(Invoice.items)).order_by(Invoice.invoice_date.desc()).all()
            
            now = datetime.now()
            setting = session.query(Setting).filter(Setting.key == "payment_terms_days").first()
            payment_terms = 14
            if setting and setting.value:
                try: payment_terms = int(setting.value)
                except ValueError: pass
                    
            changed = False
            for inv in invoices:
                if inv.status in ["Entwurf", "Offen"]:
                    inv_date = inv.invoice_date.replace(tzinfo=None) if inv.invoice_date else now
                    if (now - inv_date).days > payment_terms:
                        inv.status = "Überfällig"
                        changed = True
                        
            if changed:
                session.commit()
                self.db.save()
                
            self._cache['invoices'] = invoices
            self._cache['quotes'] = session.query(Quote).options(joinedload(Quote.customer), joinedload(Quote.items)).order_by(Quote.quote_date.desc()).all()
            self._cache['cashbook'] = session.query(CashbookEntry).order_by(CashbookEntry.entry_date.desc()).all()
            self._cache['incoming_invoices_lieferant'] = session.query(IncomingInvoice).filter(IncomingInvoice.invoice_type == "Lieferant").order_by(IncomingInvoice.date.desc()).all()
            self._cache['incoming_invoices_sonstige'] = session.query(IncomingInvoice).filter(IncomingInvoice.invoice_type == "Sonstige").order_by(IncomingInvoice.date.desc()).all()

    def get_session(self) -> Session:
        return self.db.Session()

    def _hash_record(self, data: str, prev_hash: str) -> str:
        sha256 = hashlib.sha256()
        sha256.update(f"{data}{prev_hash}".encode('utf-8'))
        return sha256.hexdigest()

    # --- Settings ---
    def get_setting(self, key: str, default: str = "") -> str:
        with self.get_session() as session:
            setting = session.query(Setting).filter(Setting.key == key).first()
            return setting.value if setting else default

    def set_setting(self, key: str, value: str):
        with self.get_session() as session:
            setting = session.query(Setting).filter(Setting.key == key).first()
            if setting:
                setting.value = value
            else:
                setting = Setting(key=key, value=value)
                session.add(setting)
            session.commit()
            self.db.save()
            self.invalidate_cache()
            SignalBus.get().dataChanged.emit()

    # --- Cashbook (GoBD) ---
    def get_last_cashbook_hash(self) -> str:
        with self.get_session() as session:
            last_entry = session.query(CashbookEntry).order_by(CashbookEntry.id.desc()).first()
            return last_entry.hash_chain if last_entry and last_entry.hash_chain else "GENESIS"

    def get_next_receipt_number(self) -> str:
        year = datetime.now().year
        with self.get_session() as session:
            last_entry = session.query(CashbookEntry).filter(CashbookEntry.receipt_number.like(f"K{year}-%")).order_by(CashbookEntry.id.desc()).first()
            if last_entry:
                last_num = int(last_entry.receipt_number.split('-')[1])
                return f"K{year}-{last_num + 1:06d}"
            else:
                return f"K{year}-000001"

    def add_cashbook_entry(self, entry_date: datetime, amount: float, description: str, category: str, entry_type: str, tax_percent: float):
        with self.get_session() as session:
            prev_hash = self.get_last_cashbook_hash()
            
            receipt_number = self.get_next_receipt_number()
            
            entry = CashbookEntry(
                entry_date=entry_date,
                amount=amount,
                receipt_number=receipt_number,
                description=description,
                category=category,
                entry_type=entry_type,
                tax_percent=tax_percent
            )
            session.add(entry)
            session.flush() # Get ID
            
            # Hash calculation
            data_to_hash = f"{entry.id}|{entry_date.isoformat()}|{amount}|{receipt_number}|{description}|{entry_type}"
            entry.hash_chain = self._hash_record(data_to_hash, prev_hash)
            
            session.commit()
            self.db.save()
            self.invalidate_cache()
            SignalBus.get().dataChanged.emit()

    def get_cashbook_entries(self):
        return self._cache['cashbook']

    # --- Customers ---
    def add_customer(self, **kwargs):
        with self.get_session() as session:
            customer = Customer(**kwargs)
            session.add(customer)
            session.commit()
            self.db.save()
            self.invalidate_cache()
            SignalBus.get().dataChanged.emit()
            return customer.id

    def update_customer(self, customer_id: int, **kwargs):
        with self.get_session() as session:
            customer = session.query(Customer).filter(Customer.id == customer_id).first()
            if customer:
                for key, value in kwargs.items():
                    setattr(customer, key, value)
                session.commit()
                self.db.save()
                self.invalidate_cache()
                SignalBus.get().dataChanged.emit()

    def delete_customer(self, customer_id: int):
        from src.models.database import Invoice, Quote
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
                session.commit()
                self.db.save()
                self.invalidate_cache()
                SignalBus.get().dataChanged.emit()
                return True, ""
            return False, "Kunde nicht gefunden"

    def get_customers(self):
        return self._cache['customers']

    # --- Invoices ---
    def get_next_invoice_number(self) -> str:
        # Example format: 2026-000001
        year = datetime.now().year
        with self.get_session() as session:
            last_invoice = session.query(Invoice).filter(Invoice.invoice_number.like(f"RE{year}%")).order_by(Invoice.id.desc()).first()
            if last_invoice:
                last_num = int(last_invoice.invoice_number[-3:])
                return f"RE{year}{datetime.now().month:02d}{last_num + 1:03d}"
            else:
                return f"RE{year}{datetime.now().month:02d}001"

    def create_invoice(self, customer_id: int, invoice_date: datetime, delivery_date: datetime, items: list, user: str = "System", **kwargs):
        with self.get_session() as session:
            invoice_num = self.get_next_invoice_number()
            
            # Calculate totals
            net_amount = sum(item['total_price'] for item in items)
            tax_amount = sum(item['total_price'] * (item['tax_percent'] / 100) for item in items)
            
            credit_amount = kwargs.get("credit_amount", 0.0)
            credit_desc = kwargs.get("credit_desc", "")
            
            if credit_amount > 0 and tax_amount > 0:
                tax_amount -= credit_amount * 0.19
                
            gross_amount = net_amount - credit_amount + tax_amount

            invoice = Invoice(
                invoice_number=invoice_num,
                customer_id=customer_id,
                invoice_date=invoice_date,
                delivery_date=delivery_date,
                net_amount=net_amount,
                tax_amount=tax_amount,
                gross_amount=gross_amount,
                credit_amount=credit_amount,
                credit_desc=credit_desc,
                status=kwargs.get("status", "Entwurf")
            )
            session.add(invoice)
            session.flush()

            for item_data in items:
                item = InvoiceItem(
                    invoice_id=invoice.id,
                    **item_data
                )
                session.add(item)
                
            history = DocumentHistory(
                document_type="Invoice",
                document_id=invoice.id,
                user=user,
                action="Created"
            )
            session.add(history)

            session.commit()
            self.db.save()
            self.invalidate_cache()
            SignalBus.get().dataChanged.emit()
            return invoice.id

    def get_invoices(self):
        return self._cache['invoices']

    def get_invoice(self, invoice_id: int):
        from sqlalchemy.orm import joinedload
        with self.get_session() as session:
            return session.query(Invoice).options(joinedload(Invoice.customer), joinedload(Invoice.items)).filter(Invoice.id == invoice_id).first()

    def update_invoice(self, invoice_id: int, customer_id: int, invoice_date: datetime, delivery_date: datetime, items: list, user: str = "System", **kwargs):
        with self.get_session() as session:
            invoice = session.query(Invoice).filter(Invoice.id == invoice_id).first()
            if not invoice: return False
            
            # 1. Archive old hash chain
            # ... GoBD logic
            
            # 2. Update values
            invoice.customer_id = customer_id
            invoice.invoice_date = invoice_date
            invoice.delivery_date = delivery_date
            if "status" in kwargs:
                invoice.status = kwargs["status"]
            
            net_amount = sum(item['total_price'] for item in items)
            tax_amount = sum(item['total_price'] * (item['tax_percent'] / 100) for item in items)
            
            credit_amount = kwargs.get("credit_amount", 0.0)
            credit_desc = kwargs.get("credit_desc", "")
            
            if credit_amount > 0 and tax_amount > 0:
                tax_amount -= credit_amount * 0.19
                
            gross_amount = net_amount - credit_amount + tax_amount
            
            invoice.net_amount = net_amount
            invoice.tax_amount = tax_amount
            invoice.gross_amount = gross_amount
            invoice.credit_amount = credit_amount
            invoice.credit_desc = credit_desc
            
            # 3. Update items
            session.query(InvoiceItem).filter(InvoiceItem.invoice_id == invoice_id).delete()
            for item_data in items:
                new_item = InvoiceItem(
                    invoice_id=invoice_id,
                    title=item_data['title'],
                    quantity=item_data['quantity'],
                    unit=item_data['unit'],
                    unit_price=item_data['unit_price'],
                    tax_percent=item_data['tax_percent'],
                    total_price=item_data['total_price']
                )
                session.add(new_item)
                
            session.commit()
            self.db.save()
            self.invalidate_cache()
            SignalBus.get().dataChanged.emit()
            return True

    def update_invoice_status(self, invoice_id: int, status: str):
        with self.get_session() as session:
            invoice = session.query(Invoice).filter(Invoice.id == invoice_id).first()
            if invoice:
                invoice.status = status
                session.commit()
                self.db.save()
                self.invalidate_cache()
                SignalBus.get().dataChanged.emit()
                return True
            return False

    def update_reminder_level(self, invoice_id: int, level: int, date: datetime):
        with self.get_session() as session:
            inv = session.query(Invoice).filter(Invoice.id == invoice_id).first()
            if inv:
                inv.reminder_level = level
                inv.last_reminder_date = date
                session.commit()
                self.db.save()
                self.invalidate_cache()
                SignalBus.get().dataChanged.emit()
                return True
            return False

    def delete_invoice(self, invoice_id: int) -> bool:
        with self.get_session() as session:
            invoice = session.query(Invoice).filter(Invoice.id == invoice_id).first()
            if invoice:
                session.delete(invoice)
                session.commit()
                self.db.save()
                self.invalidate_cache()
                SignalBus.get().dataChanged.emit()
                return True
            return False

    def archive_invoice(self, invoice_id: int, user: str = "System"):
        with self.get_session() as session:
            invoice = session.query(Invoice).filter(Invoice.id == invoice_id).first()
            if invoice and not invoice.archived_at:
                invoice.archived_at = datetime.now(timezone.utc)
                history = DocumentHistory(document_type="Invoice", document_id=invoice.id, user=user, action="Archived")
                session.add(history)
                session.commit()
                self.db.save()
                self.invalidate_cache()
                SignalBus.get().dataChanged.emit()
                return True
            return False

    # --- Quotes ---
    def get_next_quote_number(self) -> str:
        year = datetime.now().year
        with self.get_session() as session:
            last_quote = session.query(Quote).filter(Quote.quote_number.like(f"A{year}-%")).order_by(Quote.id.desc()).first()
            if last_quote:
                last_num = int(last_quote.quote_number.split('-')[1])
                return f"A{year}-{last_num + 1:06d}"
            else:
                return f"A{year}-000001"

    def create_quote(self, customer_id: int, quote_date: datetime, items: list, user: str = "System"):
        with self.get_session() as session:
            quote_num = self.get_next_quote_number()
            
            net_amount = sum(item['total_price'] for item in items)
            tax_amount = sum(item['total_price'] * (item['tax_percent'] / 100) for item in items)
            gross_amount = net_amount + tax_amount

            quote = Quote(
                quote_number=quote_num,
                customer_id=customer_id,
                quote_date=quote_date,
                net_amount=net_amount,
                tax_amount=tax_amount,
                gross_amount=gross_amount
            )
            session.add(quote)
            session.flush()

            for item_data in items:
                item = QuoteItem(
                    quote_id=quote.id,
                    **item_data
                )
                session.add(item)
                
            history = DocumentHistory(
                document_type="Quote",
                document_id=quote.id,
                user=user,
                action="Created"
            )
            session.add(history)

            session.commit()
            self.db.save()
            self.invalidate_cache()
            SignalBus.get().dataChanged.emit()
            return quote.id

    def get_quotes(self):
        return self._cache['quotes']

    def get_quote(self, quote_id: int):
        from sqlalchemy.orm import joinedload
        with self.get_session() as session:
            return session.query(Quote).options(joinedload(Quote.customer), joinedload(Quote.items)).filter(Quote.id == quote_id).first()

    def update_quote(self, quote_id: int, customer_id: int, quote_date: datetime, items: list, user: str = "System", **kwargs):
        with self.get_session() as session:
            quote = session.query(Quote).filter(Quote.id == quote_id).first()
            if not quote: return False
            
            quote.customer_id = customer_id
            quote.quote_date = quote_date
            if "status" in kwargs:
                quote.status = kwargs["status"]
            
            net_amount = sum(item['total_price'] for item in items)
            tax_amount = sum(item['total_price'] * (item['tax_percent'] / 100) for item in items)
            gross_amount = net_amount + tax_amount
            
            quote.net_amount = net_amount
            quote.tax_amount = tax_amount
            quote.gross_amount = gross_amount
            
            session.query(QuoteItem).filter(QuoteItem.quote_id == quote_id).delete()
            for item_data in items:
                new_item = QuoteItem(
                    quote_id=quote_id,
                    title=item_data['title'],
                    quantity=item_data['quantity'],
                    unit=item_data['unit'],
                    unit_price=item_data['unit_price'],
                    tax_percent=item_data['tax_percent'],
                    total_price=item_data['total_price']
                )
                session.add(new_item)
                
            session.commit()
            self.db.save()
            self.invalidate_cache()
            SignalBus.get().dataChanged.emit()
            return True
            
    def update_quote_status(self, quote_id: int, status: str):
        with self.get_session() as session:
            quote = session.query(Quote).filter(Quote.id == quote_id).first()
            if quote:
                quote.status = status
                session.commit()
                self.db.save()
                self.invalidate_cache()
                SignalBus.get().dataChanged.emit()
                return True
            return False

    def archive_quote(self, quote_id: int, user: str = "System"):
        with self.get_session() as session:
            quote = session.query(Quote).filter(Quote.id == quote_id).first()
            if quote and not quote.archived_at:
                quote.archived_at = datetime.now(timezone.utc)
                history = DocumentHistory(document_type="Quote", document_id=quote.id, user=user, action="Archived")
                session.add(history)
                session.commit()
                self.db.save()
                self.invalidate_cache()
                SignalBus.get().dataChanged.emit()
                return True
            return False

    def delete_quote(self, quote_id: int) -> bool:
        with self.get_session() as session:
            quote = session.query(Quote).filter(Quote.id == quote_id).first()
            if quote:
                session.delete(quote)
                session.commit()
                self.db.save()
                self.invalidate_cache()
                SignalBus.get().dataChanged.emit()
                return True
            return False

    # --- Incoming Invoices ---
    def add_incoming_invoice(self, invoice_type: str, date: datetime, amount: float, description: str, file_path: str):
        with self.get_session() as session:
            try:
                entry = IncomingInvoice(
                    invoice_type=invoice_type,
                    date=date,
                    amount=amount,
                    description=description,
                    file_path=file_path
                )
                session.add(entry)
                session.commit()
                self.db.save()
                self.invalidate_cache()
                SignalBus.get().dataChanged.emit()
                return entry.id
            except Exception as e:
                session.rollback()
                print(f"Error adding incoming invoice: {e}")
                return None

    def get_incoming_invoices(self, invoice_type: str = None) -> List[IncomingInvoice]:
        if invoice_type == "Lieferant":
            return self._cache['incoming_invoices_lieferant']
        elif invoice_type == "Sonstige":
            return self._cache['incoming_invoices_sonstige']
        else:
            return self._cache['incoming_invoices_lieferant'] + self._cache['incoming_invoices_sonstige']

    def delete_incoming_invoice(self, invoice_id: int) -> bool:
        with self.get_session() as session:
            try:
                entry = session.query(IncomingInvoice).filter(IncomingInvoice.id == invoice_id).first()
                if entry:
                    session.delete(entry)
                    session.commit()
                    self.db.save()
                    self.invalidate_cache()
                    SignalBus.get().incomingInvoiceDeleted.emit(invoice_id)
                    return True
                return False
            except Exception as e:
                session.rollback()
                print(f"Error deleting incoming invoice: {e}")
                return False
