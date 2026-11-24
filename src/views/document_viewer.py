"""In-app view of an archived PDF (received invoices): no PDF program is needed to look at a receipt."""
import logging
import os
import shutil
from PySide6.QtCore import Qt
from PySide6.QtPdf import QPdfDocument
from PySide6.QtPdfWidgets import QPdfView
from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QVBoxLayout
from qfluentwidgets import BodyLabel, PrimaryPushButton, PushButton
from src.utils import paths
from src.views.common import notify_error, notify_success, open_document

logger = logging.getLogger(__name__)


class PdfViewer(QDialog):
    """Shows all pages of a PDF, scaled to the window width. The archived file itself is never handed out for editing."""

    def __init__(self, path: str, title: str, save_name: str, parent=None):
        super().__init__(parent)
        self.path = path
        self.save_name = save_name
        self.setWindowTitle(title)
        self.resize(900, 1000)
        if parent is not None:
            # Not larger than the screen with 125 % scaling
            available = parent.screen().availableGeometry()
            self.resize(min(900, available.width() - 80), min(1000, available.height() - 80))
        layout = QVBoxLayout(self)
        self.document = QPdfDocument(self)
        error = self.document.load(path)
        self.view = QPdfView(self)
        self.view.setPageMode(QPdfView.PageMode.MultiPage)
        self.view.setZoomMode(QPdfView.ZoomMode.FitToWidth)
        self.view.setDocument(self.document)
        if error != QPdfDocument.Error.None_:
            logger.warning("PDF %s konnte nicht angezeigt werden: %s", path, error)
            message = BodyLabel("Die Vorschau dieser PDF ist nicht möglich. Bitte mit dem PDF-Programm öffnen.", self)
            message.setAlignment(Qt.AlignCenter)
            layout.addWidget(message, 1)
            self.view.hide()
        else:
            layout.addWidget(self.view, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save = PushButton("Speichern unter …", self)
        save.clicked.connect(self.save_copy)
        external = PushButton("Mit PDF-Programm öffnen", self)
        external.clicked.connect(lambda: open_document(self, self.path))
        close = PrimaryPushButton("Schließen", self)
        close.clicked.connect(self.accept)
        for button in (save, external, close):
            buttons.addWidget(button)
        layout.addLayout(buttons)

    def page_count(self) -> int:
        return self.document.pageCount()

    def save_copy(self):
        """A copy for passing on; the archived original stays where it is."""
        target, _ = QFileDialog.getSaveFileName(self, "Beleg speichern unter", paths.desktop_path(self.save_name),
                                                "PDF (*.pdf)")
        if not target:
            return
        try:
            shutil.copyfile(self.path, target)
        except OSError as e:
            notify_error(self, "Nicht gespeichert", str(e))
            return
        notify_success(self, "Gespeichert", os.path.basename(target))
