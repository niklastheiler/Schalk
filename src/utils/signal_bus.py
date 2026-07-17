from PySide6.QtCore import QObject, Signal

class SignalBus(QObject):
    """
    Global Signal Bus to broadcast events across the application.
    Used for cache invalidation when data changes.
    """
    dataChanged = Signal() # Keep for global settings
    
    invoiceAdded = Signal(int)
    invoiceUpdated = Signal(int)
    invoiceDeleted = Signal(int)
    
    quoteAdded = Signal(int)
    quoteUpdated = Signal(int)
    quoteDeleted = Signal(int)
    
    customerAdded = Signal(int)
    customerUpdated = Signal(int)
    customerDeleted = Signal(int)
    
    cashbookAdded = Signal(int)
    cashbookUpdated = Signal(int)
    cashbookDeleted = Signal(int)
    
    incomingInvoiceAdded = Signal(int)
    incomingInvoiceUpdated = Signal(int)
    incomingInvoiceDeleted = Signal(int)
    
    _instance = None
    
    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = SignalBus()
        return cls._instance
