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
