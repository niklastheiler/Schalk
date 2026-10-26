import logging
import threading
from PySide6.QtCore import QObject, Signal
from qfluentwidgets import InfoBar, InfoBarPosition, MessageBox
from src.utils import updater
from src.version import APP_VERSION

logger = logging.getLogger(__name__)


class UpdateNotifier(QObject):
    """
    Checks for a new release in the background on start, downloads it and offers a restart to install it.
    If the user postpones, the update is installed when Schalk is closed.
    """

    found = Signal(object) # Release
    ready = Signal(str) # version
    finished = Signal(str) # message for a manual check without a new version ("" = nothing to say)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.pending_version = None # downloaded, installed on exit
        self.restart = False
        self.checking = False
        self.found.connect(self._on_found)
        self.ready.connect(self._on_ready)
        self.finished.connect(self._on_finished)

    def start(self):
        if not updater.is_installed():
            return
        try:
            updater.remove_installed_updates()
        except OSError:
            logger.exception("Alte Updates konnten nicht gelöscht werden")
        staged = updater.staged_version()
        if staged:
            self.ready.emit(staged)
            return
        self._start_check(manual=False)

    def check_now(self):
        """"Nach Update suchen" in the settings: like the check on start, but always reports the result."""
        if not updater.is_installed():
            self._info("Updates gibt es nur für die installierte Version",
                       "Beim Start aus dem Quellcode wird nichts aktualisiert.")
        elif self.pending_version:
            self._on_ready(self.pending_version)
        elif self.checking:
            self._info("Update-Suche läuft bereits", "")
        else:
            self._start_check(manual=True)

    def _start_check(self, manual: bool):
        self.checking = True
        threading.Thread(target=self._check_and_download, args=(manual,), name="schalk-update", daemon=True).start()

    def _check_and_download(self, manual: bool = False):
        message = ""
        try:
            release = updater.find_update()
            if release is None:
                message = f"Schalk {APP_VERSION} ist aktuell." if manual else ""
                return
            self.found.emit(release)
            updater.download(release)
            self.ready.emit(release.version)
        except Exception as e:
            # No network, GitHub not reachable, ...: try again on the next start
            logger.exception("Update-Prüfung fehlgeschlagen")
            message = f"Update-Prüfung fehlgeschlagen: {e}" if manual else ""
        finally:
            self.finished.emit(message)

    def _info(self, title: str, content: str):
        InfoBar.info(title=title, content=content, isClosable=True, position=InfoBarPosition.BOTTOM_RIGHT,
                     duration=6000, parent=self.window)

    def _on_finished(self, message: str):
        self.checking = False
        if message:
            self._info("Nach Update suchen", message)

    def _on_found(self, release):
        InfoBar.info(title=f"Update auf Version {release.version}",
                     content="Wird im Hintergrund heruntergeladen. Du kannst normal weiterarbeiten.",
                     isClosable=True, position=InfoBarPosition.BOTTOM_RIGHT, duration=8000, parent=self.window)

    def _on_ready(self, version: str):
        self.pending_version = version
        box = MessageBox(f"Update auf Version {version} bereit",
                         "Das Update ist heruntergeladen. Für die Installation startet Schalk neu, Windows fragt dabei einmal "
                         "nach der Berechtigung. Vorher wird die Datenbank gesichert, deine Daten bleiben unverändert.\n\nBei „Später“ wird das Update beim nächsten Schließen installiert.",
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
