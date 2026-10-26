from PySide6.QtCore import QObject, Signal

class SignalBus(QObject):
    """
    Global Signal Bus to broadcast data changes across the application.
    Views refresh their (virtual) table models when the matching signal fires.
    """
    settingsChanged = Signal()
    invoicesChanged = Signal()
    quotesChanged = Signal()
    customersChanged = Signal()
    cashbookChanged = Signal()
    incomingInvoicesChanged = Signal()
    saveFailed = Signal(str)

    _instance = None

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = SignalBus()
        return cls._instance
