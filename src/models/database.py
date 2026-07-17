import os
import hashlib
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Text, Date, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import sqlite3
from sqlalchemy.pool import StaticPool

Base = declarative_base()

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
    country = Column(String, default="Deutschland")
    email = Column(String)
    phone = Column(String)
    vat_id = Column(String)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class Invoice(Base):
    __tablename__ = 'invoices'
    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_number = Column(String, unique=True, nullable=False)
    customer_id = Column(Integer, ForeignKey('customers.id'), nullable=False)
    invoice_date = Column(DateTime, nullable=False)
    delivery_date = Column(DateTime, nullable=False)
    status = Column(String, nullable=False, default="Entwurf") # Entwurf, Offen, Bezahlt, Teilbezahlt, Überfällig, Storniert, Archiviert
    net_amount = Column(Float, default=0.0)
    tax_amount = Column(Float, default=0.0)
    gross_amount = Column(Float, default=0.0)
    payment_terms = Column(String)
    credit_amount = Column(Float, default=0.0)
    credit_desc = Column(String)
    hash_chain = Column(String) # For GoBD immutability
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    archived_at = Column(DateTime)
    reminder_level = Column(Integer, default=0)
    last_reminder_date = Column(DateTime)
    
    customer = relationship("Customer")
    items = relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")

class InvoiceItem(Base):
    __tablename__ = 'invoice_items'
    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id = Column(Integer, ForeignKey('invoices.id'))
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
    customer_id = Column(Integer, ForeignKey('customers.id'), nullable=False)
    quote_date = Column(DateTime, nullable=False)
    status = Column(String, nullable=False, default="Entwurf") # Entwurf, Versendet, Angenommen, Abgelehnt, Abgelaufen, Archiviert
    net_amount = Column(Float, default=0.0)
    tax_amount = Column(Float, default=0.0)
    gross_amount = Column(Float, default=0.0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    archived_at = Column(DateTime)
    
    customer = relationship("Customer")
    items = relationship("QuoteItem", back_populates="quote", cascade="all, delete-orphan")

class QuoteItem(Base):
    __tablename__ = 'quote_items'
    id = Column(Integer, primary_key=True, autoincrement=True)
    quote_id = Column(Integer, ForeignKey('quotes.id'))
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
    entry_date = Column(DateTime, nullable=False)
    amount = Column(Float, nullable=False)
    receipt_number = Column(String, nullable=False)
    description = Column(String, nullable=False)
    category = Column(String)
    entry_type = Column(String, nullable=False) # Einnahme, Ausgabe, Umbuchung
    tax_percent = Column(Float, default=0.0)
    is_storno = Column(Boolean, default=False)
    hash_chain = Column(String) # For GoBD
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class IncomingInvoice(Base):
    __tablename__ = 'incoming_invoices'
    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_type = Column(String, nullable=False) # "Lieferant" or "Sonstige"
    date = Column(DateTime, nullable=False)
    amount = Column(Float, nullable=False)
    description = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class DocumentHistory(Base):
    __tablename__ = 'document_history'
    id = Column(Integer, primary_key=True, autoincrement=True)
    document_type = Column(String, nullable=False) # Invoice, Quote
    document_id = Column(Integer, nullable=False)
    user = Column(String, nullable=False)
    action = Column(String, nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class DatabaseManager:
    def __init__(self, db_path="schalk.db.enc", password: str = "default_secure_password_for_now"):
        self.db_path = db_path
        self.password = password
        self.engine = None
        self.Session = None
        self.memory_conn = None
        
        self._init_encryption_key()
        self.connect()
        
    def _init_encryption_key(self):
        salt = b'schalk_secure_salt_123'
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(self.password.encode()))
        self.fernet = Fernet(key)

    def connect(self):
        # We use an in-memory database to ensure the unencrypted data is never written to disk.
        self.memory_conn = sqlite3.connect(':memory:', check_same_thread=False)
        
        if os.path.exists(self.db_path):
            with open(self.db_path, "rb") as f:
                encrypted_data = f.read()
            if encrypted_data:
                try:
                    decrypted_data = self.fernet.decrypt(encrypted_data)
                    # We need to write this temporarily to load it into sqlite, or load it via backup
                    # sqlite3 doesn't support loading from bytes directly.
                    # We will create a temp file, backup, and delete immediately.
                    temp_path = self.db_path + ".tmp"
                    with open(temp_path, "wb") as f:
                        f.write(decrypted_data)
                    
                    temp_conn = sqlite3.connect(temp_path)
                    temp_conn.backup(self.memory_conn)
                    temp_conn.close()
                    os.remove(temp_path)
                except Exception as e:
                    print(f"Error decrypting database: {e}")
                    raise
                    
        self.engine = create_engine(
            "sqlite://", 
            creator=lambda: self.memory_conn,
            poolclass=StaticPool,
            connect_args={'check_same_thread': False}
        )
        Base.metadata.create_all(self.engine)
        
        # Migrations
        try:
            self.memory_conn.execute("ALTER TABLE invoices ADD COLUMN reminder_level INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            self.memory_conn.execute("ALTER TABLE invoices ADD COLUMN last_reminder_date DATETIME")
        except Exception:
            pass
            
        self.Session = sessionmaker(bind=self.engine, expire_on_commit=False)
        
    def save(self):
        if not self.memory_conn:
            return
            
        temp_path = self.db_path + ".tmp"
        temp_conn = sqlite3.connect(temp_path)
        self.memory_conn.backup(temp_conn)
        temp_conn.close()
        
        with open(temp_path, "rb") as f:
            db_bytes = f.read()
            
        encrypted_data = self.fernet.encrypt(db_bytes)
        with open(self.db_path, "wb") as f:
            f.write(encrypted_data)
            
        os.remove(temp_path)
