import logging
import threading
from PySide6.QtCore import QObject, Signal
from qfluentwidgets import InfoBar, InfoBarPosition, MessageBox
from src.utils import updater

logger = logging.getLogger(__name__)

RELEASES_URL = f"https://github.com/{updater.REPOSITORY}/releases/latest"


class UpdateNotifier(QObject):
    """
    Checks for a new release in the background on start, downloads it and offers a restart to install it.
    If the user postpones, the update is installed when Schalk is closed.
    """

    found = Signal(object) # Release
    ready = Signal(str) # version
    failed = Signal(str)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.pending_version = None # downloaded, installed on exit
        self.restart = False
        self.found.connect(self._on_found)
        self.ready.connect(self._on_ready)
        self.failed.connect(self._on_failed)

    def start(self):
        if not updater.is_installed_build():
            return
        staged = updater.staged_version()
        if staged:
            self.ready.emit(staged)
            return
        threading.Thread(target=self._check_and_download, name="schalk-update", daemon=True).start()

    def _check_and_download(self):
        try:
            release = updater.find_update()
            if release is None:
                return
            if not updater.can_write_install_dir():
                self.failed.emit(f"Version {release.version} ist verfügbar, kann aber nicht automatisch installiert werden, "
                                 f"weil der Programmordner schreibgeschützt ist. Download: {RELEASES_URL}")
                return
            self.found.emit(release)
            updater.download(release)
            self.ready.emit(release.version)
        except Exception:
            # No network, GitHub not reachable, ...: try again on the next start
            logger.exception("Update-Prüfung fehlgeschlagen")

    def _on_found(self, release):
        InfoBar.info(title=f"Update auf Version {release.version}",
                     content="Wird im Hintergrund heruntergeladen. Du kannst normal weiterarbeiten.",
                     isClosable=True, position=InfoBarPosition.BOTTOM_RIGHT, duration=8000, parent=self.window)

    def _on_failed(self, message: str):
        InfoBar.warning(title="Update verfügbar", content=message, isClosable=True,
                        position=InfoBarPosition.BOTTOM_RIGHT, duration=-1, parent=self.window)

    def _on_ready(self, version: str):
        self.pending_version = version
        box = MessageBox(f"Update auf Version {version} bereit",
                         "Das Update ist heruntergeladen. Für die Installation startet Schalk neu, das dauert nur einen Moment. "
                         "Deine Daten bleiben unverändert.\n\nBei „Später“ wird das Update beim nächsten Schließen installiert.",
                         self.window)
        box.yesButton.setText("Jetzt neu starten")
        box.cancelButton.setText("Später")
        if box.exec():
            self.restart = True
            self.window.close()

    def install_on_exit(self):
        """Called after the database is closed: hands over to the installer script."""
        if not self.pending_version:
            return
        try:
            updater.apply_on_exit(self.pending_version, self.restart)
        except Exception:
            logger.exception("Update konnte nicht gestartet werden")
