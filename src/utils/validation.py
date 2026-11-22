"""Checks of typed-in contact data (postal code, phone number, e-mail address, tax number)."""
import re
from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QRegularExpressionValidator
from stdnum.de import stnr

# Name@domain.tld: exactly one @, no spaces, a dot in the domain and a top-level domain of at least two letters
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
_PHONE_CHARS = r"[0-9 +()/\-]*"
_POSTAL_CODE_CHARS = r"[0-9A-Za-z \-]{0,10}"


def is_valid_email(value: str) -> bool:
    return bool(_EMAIL.fullmatch(value.strip()))


def is_valid_phone(value: str) -> bool:
    """Digits with the usual separators, + only at the start; 6 to 15 digits (international maximum)."""
    value = value.strip()
    if not re.fullmatch(_PHONE_CHARS, value) or "+" in value[1:]:
        return False
    return 6 <= sum(ch.isdigit() for ch in value) <= 15


def is_valid_postal_code(value: str, country: str = "DE") -> bool:
    value = value.strip()
    if (country or "DE").upper() == "DE":
        return bool(re.fullmatch(r"\d{5}", value))
    return bool(re.fullmatch(_POSTAL_CODE_CHARS, value)) and any(ch.isalnum() for ch in value)


def is_valid_tax_number(value: str) -> bool:
    """German Steuernummer in the format of the tax office (e.g. 12/345/67890) or the 13-digit federal format."""
    return stnr.is_valid(value.strip())


def contact_problems(values: dict, who: str, country: str = "DE") -> list:
    """Problems with postal code, phone and e-mail in values; who names the owner, e.g. 'des Kunden'."""
    problems = []
    if values.get("postal_code") and not is_valid_postal_code(values["postal_code"], country):
        problems.append(f"Die PLZ {who} ist ungültig" + (" (5 Ziffern)." if (country or "DE").upper() == "DE" else "."))
    if values.get("phone") and not is_valid_phone(values["phone"]):
        problems.append(f"Die Telefonnummer {who} ist ungültig (6 bis 15 Ziffern, erlaubt sind + ( ) / - und Leerzeichen).")
    if values.get("email") and not is_valid_email(values["email"]):
        problems.append(f"Die E-Mail-Adresse {who} ist ungültig (Beispiel: name@firma.de).")
    return problems


def _validator(pattern: str, parent=None) -> QRegularExpressionValidator:
    return QRegularExpressionValidator(QRegularExpression(pattern), parent)


def german_postal_code_validator(parent=None):
    """Typing restriction for German postal codes: at most 5 digits."""
    return _validator(r"\d{0,5}", parent)


def postal_code_validator(parent=None):
    """Typing restriction for postal codes of any country: letters, digits, space and hyphen."""
    return _validator(_POSTAL_CODE_CHARS, parent)


def phone_validator(parent=None):
    return _validator(r"\+?[0-9 ()/\-]{0,24}", parent)


def format_tax_number(text: str) -> str:
    """
    Steuernummer as the tax office writes it, from the digits typed so far. Separators typed by the user are
    ignored. Up to 10 digits: 12/345/67890 (a slash already appears after the 2nd and 5th digit); 11 digits:
    123/456/78901; 12 or 13 digits: the federal format without separators.
    """
    digits = "".join(ch for ch in text if ch.isdigit())[:13]
    if len(digits) <= 10:
        groups = (2, 3)
    elif len(digits) == 11:
        groups = (3, 3)
    else:
        return digits
    parts, rest = [], digits
    for size in groups:
        if len(rest) < size:
            break
        parts.append(rest[:size])
        rest = rest[size:]
    # Typed digits fill a group completely: the slash appears right away
    return "/".join(parts) + "/" + rest if parts else rest


def attach_tax_number_format(edit):
    """Formats a Steuernummer field while typing; the cursor stays behind the same digit."""
    # textChanged comes before textEdited: "previous" is the text before the current edit
    state = {"text": edit.text(), "previous": edit.text()}

    def on_changed(text: str):
        state["previous"], state["text"] = state["text"], text

    def on_edited(text: str):
        old = state["previous"]
        digits_before_cursor = sum(ch.isdigit() for ch in text[:edit.cursorPosition()])
        # Backspace on a slash the program inserted: removes the digit in front of it instead
        if len(text) < len(old) and sum(ch.isdigit() for ch in text) == sum(ch.isdigit() for ch in old):
            position = edit.cursorPosition()
            before = text[:position]
            index = max((i for i, ch in enumerate(before) if ch.isdigit()), default=None)
            if index is not None:
                text = text[:index] + text[index + 1:]
                digits_before_cursor -= 1
        formatted = format_tax_number(text)
        if formatted != edit.text():
            edit.setText(formatted)
        # Cursor behind the same digit as before (and behind a slash that follows it)
        position, seen = 0, 0
        while position < len(formatted) and seen < digits_before_cursor:
            seen += formatted[position].isdigit()
            position += 1
        while position < len(formatted) and formatted[position] == "/" and position == len(formatted) - 1:
            position += 1
        edit.setCursorPosition(position)

    edit.textEdited.connect(on_edited)
    edit.textChanged.connect(on_changed)
    edit.setValidator(_validator(r"[0-9/ ]{0,20}", edit))
