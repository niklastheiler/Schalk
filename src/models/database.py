import os
import base64
import logging
import sqlite3
import struct
import threading
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Text, Boolean, Index
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from sqlalchemy.pool import StaticPool
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger(__name__)

Base = declarative_base()


def _utcnow():
    return datetime.now(timezone.utc)


class Setting(Base):
    __tablename__ = 'settings'
    key = Column(String, primary_key=True)
    value = Column(String, nullable=False)

class Customer(Base):
    __tablename__ = 'customers'
    id = Column(Integer, primary_key=True, autoincrement=True)
    company_name = Column(String)
    first_name = Column(String)
    last_name = Column(String)
    address = Column(String)
    postal_code = Column(String)
    city = Column(String)
    country = Column(String, default="DE")
    email = Column(String)
    phone = Column(String)
    vat_id = Column(String)
    # Käuferreferenz (BT-10), for public authorities the Leitweg-ID
    buyer_reference = Column(String)
    created_at = Column(DateTime, default=_utcnow)

    @property
    def display_name(self) -> str:
        return self.company_name or f"{self.first_name or ''} {self.last_name or ''}".strip()

class Invoice(Base):
    __tablename__ = 'invoices'
    __table_args__ = (Index('ix_invoices_date', 'invoice_date'), Index('ix_invoices_customer', 'customer_id'))
    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_number = Column(String, unique=True, nullable=False)
    customer_id = Column(Integer, ForeignKey('customers.id'), nullable=False)
    invoice_date = Column(DateTime, nullable=False)
    delivery_date = Column(DateTime, nullable=False)
    status = Column(String, nullable=False, default="Entwurf") # Entwurf, Offen, Teilbezahlt, Bezahlt, Überfällig, Storniert
    net_amount = Column(Float, default=0.0)
    tax_amount = Column(Float, default=0.0)
    gross_amount = Column(Float, default=0.0)
    credit_amount = Column(Float, default=0.0)
    credit_desc = Column(String)
    tax_exemption_reason = Column(String) # Required on the invoice if items have 0 % VAT
    hash_chain = Column(String) # GoBD: SHA-256 chain over all finalized invoices
    created_at = Column(DateTime, default=_utcnow)
    archived_at = Column(DateTime)
    reminder_level = Column(Integer, default=0)
    last_reminder_date = Column(DateTime)

    # GoBD: set once when the invoice is finalized (leaves "Entwurf"); content is immutable afterwards
    finalized_at = Column(DateTime)
    payment_terms_days = Column(Integer)
    # Snapshots taken at finalization, so later changes of settings or customers don't alter issued invoices
    seller_snapshot = Column(Text) # JSON
    customer_name = Column(String)
    customer_address = Column(String)
    customer_postal_code = Column(String)
    customer_city = Column(String)
    customer_country = Column(String)
    customer_vat_id = Column(String)
    customer_email = Column(String)
    customer_buyer_reference = Column(String)
    # Stornorechnung: references the cancelled invoice
    cancels_invoice_id = Column(Integer)
    # Archived PDF/A-3 (ZUGFeRD) exactly as issued
    pdf_path = Column(String)
    pdf_hash = Column(String)

    # Not loaded for the list cache; DBController.get_invoice() loads them for one document
    customer = relationship("Customer")
    items = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceItem.id")

class InvoiceItem(Base):
    __tablename__ = 'invoice_items'
    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id = Column(Integer, ForeignKey('invoices.id'), index=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    quantity = Column(Float, nullable=False, default=1.0)
    unit = Column(String, nullable=False, default="Stück")
    unit_price = Column(Float, nullable=False)
    discount_percent = Column(Float, default=0.0)
    tax_percent = Column(Float, default=19.0)
    total_price = Column(Float, nullable=False)

    invoice = relationship("Invoice", back_populates="items")

class Quote(Base):
    __tablename__ = 'quotes'
    id = Column(Integer, primary_key=True, autoincrement=True)
    quote_number = Column(String, unique=True, nullable=False)
    customer_id = Column(Integer, ForeignKey('customers.id'), nullable=False, index=True)
    quote_date = Column(DateTime, nullable=False)
    status = Column(String, nullable=False, default="Entwurf") # Entwurf, Versendet, Angenommen, Abgelehnt, Abgelaufen
    net_amount = Column(Float, default=0.0)
    tax_amount = Column(Float, default=0.0)
    gross_amount = Column(Float, default=0.0)
    tax_exemption_reason = Column(String)
    created_at = Column(DateTime, default=_utcnow)
    archived_at = Column(DateTime)

    customer = relationship("Customer")
    items = relationship("QuoteItem", back_populates="quote", cascade="all, delete-orphan", order_by="QuoteItem.id")

class QuoteItem(Base):
    __tablename__ = 'quote_items'
    id = Column(Integer, primary_key=True, autoincrement=True)
    quote_id = Column(Integer, ForeignKey('quotes.id'), index=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    quantity = Column(Float, nullable=False, default=1.0)
    unit = Column(String, nullable=False, default="Stück")
    unit_price = Column(Float, nullable=False)
    discount_percent = Column(Float, default=0.0)
    tax_percent = Column(Float, default=19.0)
    total_price = Column(Float, nullable=False)

    quote = relationship("Quote", back_populates="items")

class CashbookEntry(Base):
    __tablename__ = 'cashbook_entries'
    id = Column(Integer, primary_key=True, autoincrement=True)
    entry_date = Column(DateTime, nullable=False, index=True)
    amount = Column(Float, nullable=False)
    receipt_number = Column(String, unique=True) # assigned when the cashbook is finalized
    description = Column(String, nullable=False)
    category = Column(String)
    entry_type = Column(String, nullable=False) # Einnahme, Barentnahme Privat, Barentnahme Firma
    tax_percent = Column(Float, default=0.0)
    is_storno = Column(Boolean, default=False)
    hash_chain = Column(String) # GoBD
    created_at = Column(DateTime, default=_utcnow)
    attachment_path = Column(String)
    attachment_hash = Column(String)
    storno_of_id = Column(Integer)
    finalized_at = Column(DateTime, index=True) # None = draft, still editable

class IncomingInvoice(Base):
    __tablename__ = 'incoming_invoices'
    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_type = Column(String, nullable=False, index=True) # "Lieferant" or "Sonstige"
    date = Column(DateTime, nullable=False)
    amount = Column(Float, nullable=False)
    description = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    created_at = Column(DateTime, default=_utcnow)
    file_hash = Column(String)
    # E-Rechnung: format of the received document (None = no structured data)
    einvoice_format = Column(String)
    invoice_number = Column(String)
    supplier_name = Column(String)
    # GoBD: incoming invoices are never deleted, only cancelled
    cancelled_at = Column(DateTime)

class DocumentHistory(Base):
    __tablename__ = 'document_history'
    __table_args__ = (Index('ix_history_document', 'document_type', 'document_id'),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    document_type = Column(String, nullable=False) # Invoice, Quote, Cashbook, IncomingInvoice
    document_id = Column(Integer, nullable=False)
    user = Column(String, nullable=False)
    action = Column(String, nullable=False)
    timestamp = Column(DateTime, default=_utcnow)


class WrongPasswordError(Exception):
    pass


class KeyMissingError(Exception):
    pass


# Database file: MAGIC | Fernet token (key protected by Windows DPAPI, see key_store)
FILE_MAGIC = b"SCHALK2\x00"
# Backup file: MAGIC | iterations (uint32 BE) | salt (16 bytes) | Fernet token (key derived from backup password)
BACKUP_MAGIC = b"SCHALKB\x00"
SALT_SIZE = 16
KDF_ITERATIONS = 600_000


def _derive_fernet(password: bytes, salt: bytes, iterations: int) -> Fernet:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return Fernet(base64.urlsafe_b64encode(kdf.derive(password)))


def _write_atomic(path: str, payload: bytes):
    # Atomic replace: a crash while writing never leaves a half-written file behind
    temp_path = path + ".tmp"
    with open(temp_path, "wb") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp_path, path)


class _BackgroundWriter:
    """
    Encrypts and writes database snapshots on a worker thread. Snapshots that arrive while a
    write is running are coalesced, so bursts of changes cost a single write.
    """

    def __init__(self, path: str, fernet: Fernet, on_error=None):
        self._path = path
        self._fernet = fernet
        self._on_error = on_error
        self._pending = None
        self._busy = False
        self._closed = False
        self._cond = threading.Condition()
        self.last_error = None
        self._thread = threading.Thread(target=self._run, name="schalk-db-writer", daemon=True)
        self._thread.start()

    def submit(self, snapshot: bytes):
        with self._cond:
            if self._closed:
                raise RuntimeError("Die Datenbank ist bereits geschlossen.")
            self._pending = snapshot
            self._cond.notify_all()

    def _run(self):
        while True:
            with self._cond:
                while self._pending is None and not self._closed:
                    self._cond.wait()
                if self._pending is None:
                    return
                snapshot, self._pending = self._pending, None
                self._busy = True
            try:
                _write_atomic(self._path, FILE_MAGIC + self._fernet.encrypt(snapshot))
                self.last_error = None
            except Exception as e:
                logger.exception("Speichern der Datenbank fehlgeschlagen")
                self.last_error = e
                if self._on_error:
                    self._on_error(e)
            finally:
                with self._cond:
                    self._busy = False
                    self._cond.notify_all()

    def flush(self):
        with self._cond:
            while self._pending is not None or self._busy:
                self._cond.wait()
        if self.last_error:
            raise self.last_error

    def close(self):
        try:
            self.flush()
        finally:
            with self._cond:
                self._closed = True
                self._cond.notify_all()
            self._thread.join(timeout=30)


class DatabaseManager:
    """
    Holds the SQLite database in memory only. On disk it exists solely as an encrypted file;
    the plaintext database is never written to disk.
    The random encryption key is stored protected by Windows DPAPI (bound to the Windows user
    account), so no password prompt is needed at startup.
    """

    def __init__(self, db_path: str, key_path: str, key_store=None, on_save_error=None):
        if key_store is None:
            from src.utils import key_store
        self.db_path = db_path
        self.key_path = key_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

        data = b""
        if os.path.exists(self.db_path):
            with open(self.db_path, "rb") as f:
                data = f.read()
        if data and not data.startswith(FILE_MAGIC):
            raise WrongPasswordError(f"Die Datei {self.db_path} ist keine Schalk-Datenbank.")

        if os.path.exists(self.key_path):
            self.fernet = Fernet(key_store.load_key(self.key_path))
        elif data:
            raise KeyMissingError(
                f"Der Schlüssel zur Datenbank fehlt ({self.key_path}) oder gehört zu einem anderen Windows-Benutzer. "
                "Bitte die Daten über ein Backup wiederherstellen."
            )
        else:
            key = Fernet.generate_key()
            key_store.save_key(self.key_path, key)
            self.fernet = Fernet(key)

        plaintext = None
        if data:
            try:
                plaintext = self.fernet.decrypt(data[len(FILE_MAGIC):])
            except InvalidToken:
                raise WrongPasswordError("Die Datenbank passt nicht zum gespeicherten Schlüssel.")

        self._connect(plaintext)
        self._restored = False
        self._closed = False
        self._writer = _BackgroundWriter(self.db_path, self.fernet, on_save_error)

    def _connect(self, plaintext=None):
        self.memory_conn = sqlite3.connect(':memory:', check_same_thread=False)
        if plaintext:
            # Load straight from memory; no decrypted copy ever touches the disk
            self.memory_conn.deserialize(plaintext)
        self.memory_conn.execute("PRAGMA foreign_keys = ON")

        self.engine = create_engine(
            "sqlite://",
            creator=lambda: self.memory_conn,
            poolclass=StaticPool,
            connect_args={'check_same_thread': False}
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)

    def save(self):
        """Persists the current state; encryption and disk I/O run in the background."""
        if self._restored:
            return # a restored backup must not be overwritten until the restart
        self._writer.submit(self.memory_conn.serialize())

    def flush(self):
        """Blocks until all pending changes are on disk. Raises if the last write failed."""
        if not self._restored:
            self._writer.flush()

    def close(self):
        """Writes the final state and stops the writer. Raises (and stays usable) if writing fails."""
        if self._restored or self._closed:
            return
        self.save()
        self._writer.flush()
        self._writer.close()
        self._closed = True

    # --- Backups (portable, protected by a backup password instead of the machine-bound key) ---
    def export_backup(self, path: str, password: str):
        salt = os.urandom(SALT_SIZE)
        token = _derive_fernet(password.encode("utf-8"), salt, KDF_ITERATIONS).encrypt(self.memory_conn.serialize())
        _write_atomic(path, BACKUP_MAGIC + struct.pack(">I", KDF_ITERATIONS) + salt + token)

    def restore_backup(self, data: bytes, password: str):
        """
        Replaces the database file with the backup, re-encrypted with this computer's key.
        The application must be restarted afterwards.
        """
        if not data.startswith(BACKUP_MAGIC):
            raise ValueError("Die Datei ist kein gültiges Schalk-Backup.")
        offset = len(BACKUP_MAGIC)
        (iterations,) = struct.unpack(">I", data[offset:offset + 4])
        salt = data[offset + 4:offset + 4 + SALT_SIZE]
        try:
            plaintext = _derive_fernet((password or "").encode("utf-8"), salt, iterations).decrypt(data[offset + 4 + SALT_SIZE:])
        except InvalidToken:
            raise WrongPasswordError("Falsches Backup-Passwort.")

        # Make sure it really is a SQLite database before replacing anything
        check = sqlite3.connect(':memory:')
        try:
            check.deserialize(plaintext)
            check.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except sqlite3.DatabaseError:
            raise ValueError("Die Datei enthält keine gültige Datenbank.")
        finally:
            check.close()

        # No further background writes may overwrite the restored file
        self._writer.close()
        self._restored = True
        _write_atomic(self.db_path, FILE_MAGIC + self.fernet.encrypt(plaintext))
