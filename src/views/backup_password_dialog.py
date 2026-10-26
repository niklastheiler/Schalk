from PySide6.QtCore import Qt
from qfluentwidgets import BodyLabel, MessageBoxBase, PasswordLineEdit, SubtitleLabel

MIN_PASSWORD_LENGTH = 8


class BackupPasswordDialog(MessageBoxBase):
    """
    Asks for a backup password, shown as a light Fluent dialog over the main window.
    mode 'unlock': enter the password of an existing backup
    mode 'create': choose a password for a new backup
    """

    def __init__(self, mode: str = "unlock", message: str = "", parent=None):
        super().__init__(parent)
        self.mode = mode
        self.widget.setMinimumWidth(440)

        title = "Backup-Passwort eingeben" if mode == "unlock" else "Backup-Passwort festlegen"
        self.viewLayout.addWidget(SubtitleLabel(title, self.widget))

        if mode == "create":
            info = BodyLabel(
                "Das Backup wird mit diesem Passwort verschlüsselt und kann damit auf jedem Computer "
                "eingespielt werden. Ohne das Passwort ist das Backup wertlos – bitte sicher aufbewahren.", self.widget)
            info.setWordWrap(True)
            self.viewLayout.addWidget(info)

        self.messageLabel = BodyLabel(message, self.widget)
        self.messageLabel.setWordWrap(True)
        self.messageLabel.setStyleSheet("color: #C42B1C;")
        self.messageLabel.setVisible(bool(message))
        self.viewLayout.addWidget(self.messageLabel)

        self.passwordEdit = PasswordLineEdit(self.widget)
        self.passwordEdit.setPlaceholderText("Passwort")
        self.viewLayout.addWidget(self.passwordEdit)

        self.repeatEdit = PasswordLineEdit(self.widget)
        self.repeatEdit.setPlaceholderText("Passwort wiederholen")
        self.repeatEdit.setVisible(mode == "create")
        self.viewLayout.addWidget(self.repeatEdit)

        self.yesButton.setText("OK")
        self.cancelButton.setText("Abbrechen")
        self.passwordEdit.returnPressed.connect(self.yesButton.click)
        self.repeatEdit.returnPressed.connect(self.yesButton.click)
        self.passwordEdit.setFocus(Qt.OtherFocusReason)

    def show_error(self, message: str):
        self.messageLabel.setText(message)
        self.messageLabel.setVisible(True)

    def validate(self) -> bool:
        password = self.passwordEdit.text()
        if not password:
            self.show_error("Bitte ein Passwort eingeben.")
            return False
        if self.mode == "create":
            if len(password) < MIN_PASSWORD_LENGTH:
                self.show_error(f"Das Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen lang sein.")
                return False
            if password != self.repeatEdit.text():
                self.show_error("Die Passwörter stimmen nicht überein.")
                return False
        return True

    def password(self) -> str:
        return self.passwordEdit.text()
