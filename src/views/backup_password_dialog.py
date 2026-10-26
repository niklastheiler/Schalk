from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout
from qfluentwidgets import BodyLabel, PasswordLineEdit, PrimaryPushButton, PushButton, SubtitleLabel

MIN_PASSWORD_LENGTH = 8


class BackupPasswordDialog(QDialog):
    """
    Asks for a backup password.
    mode 'unlock': enter the password of an existing backup
    mode 'create': choose a password for a new backup
    """

    def __init__(self, mode: str = "unlock", message: str = "", parent=None):
        super().__init__(parent)
        self.mode = mode
        self.setWindowTitle("Schalk")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = "Backup-Passwort eingeben" if mode == "unlock" else "Backup-Passwort festlegen"
        layout.addWidget(SubtitleLabel(title, self))

        if mode == "create":
            info = BodyLabel(
                "Das Backup wird mit diesem Passwort verschlüsselt und kann damit auf jedem Computer "
                "eingespielt werden. Ohne das Passwort ist das Backup wertlos – bitte sicher aufbewahren.", self)
            info.setWordWrap(True)
            layout.addWidget(info)

        self.messageLabel = BodyLabel(message, self)
        self.messageLabel.setWordWrap(True)
        self.messageLabel.setStyleSheet("color: #C42B1C;")
        self.messageLabel.setVisible(bool(message))
        layout.addWidget(self.messageLabel)

        self.passwordEdit = PasswordLineEdit(self)
        self.passwordEdit.setPlaceholderText("Passwort")
        layout.addWidget(self.passwordEdit)

        self.repeatEdit = PasswordLineEdit(self)
        self.repeatEdit.setPlaceholderText("Passwort wiederholen")
        self.repeatEdit.setVisible(mode == "create")
        layout.addWidget(self.repeatEdit)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancelBtn = PushButton("Abbrechen", self)
        self.cancelBtn.clicked.connect(self.reject)
        self.okBtn = PrimaryPushButton("OK", self)
        self.okBtn.setDefault(True)
        self.okBtn.clicked.connect(self._accept)
        buttons.addWidget(self.cancelBtn)
        buttons.addWidget(self.okBtn)
        layout.addLayout(buttons)

        self.passwordEdit.returnPressed.connect(self._accept)
        self.repeatEdit.returnPressed.connect(self._accept)
        self.passwordEdit.setFocus(Qt.OtherFocusReason)

    def show_error(self, message: str):
        self.messageLabel.setText(message)
        self.messageLabel.setVisible(True)

    def _accept(self):
        password = self.passwordEdit.text()
        if not password:
            self.show_error("Bitte ein Passwort eingeben.")
            return
        if self.mode == "create":
            if len(password) < MIN_PASSWORD_LENGTH:
                self.show_error(f"Das Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen lang sein.")
                return
            if password != self.repeatEdit.text():
                self.show_error("Die Passwörter stimmen nicht überein.")
                return
        self.accept()

    def password(self) -> str:
        return self.passwordEdit.text()
