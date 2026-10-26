TAX_RATE_OPTIONS = [19.0, 7.0, 0.0]

# Common reasons for invoices without VAT (shown as presets, free text is possible as well)
EXEMPTION_REASON_PRESETS = [
    "Kein Ausweis von Umsatzsteuer, da Kleinunternehmer gemäß § 19 UStG",
    "Steuerfreie innergemeinschaftliche Lieferung gemäß § 4 Nr. 1b UStG",
    "Steuerschuldnerschaft des Leistungsempfängers gemäß § 13b UStG (Reverse Charge)",
    "Steuerfreie Ausfuhrlieferung gemäß § 4 Nr. 1a UStG",
    "Steuerfreie Leistung gemäß § 4 UStG",
]

EXEMPTION_REQUIRED_MESSAGE = "Für Positionen mit 0 % MwSt. muss ein Befreiungsgrund angegeben werden."


def format_rate(rate: float) -> str:
    return f"{rate:g} %".replace(".", ",")


def has_zero_rate(items) -> bool:
    return any(float((i['tax_percent'] if isinstance(i, dict) else i.tax_percent) or 0.0) == 0.0 for i in items)


def vat_category(rate: float, exemption_reason: str = "") -> str:
    """UNCL5305 VAT category code for ZUGFeRD/XRechnung."""
    if rate > 0:
        return "S"
    reason = (exemption_reason or "").lower()
    if "13b" in reason or "reverse charge" in reason:
        return "AE"
    if "innergemeinschaftlich" in reason:
        return "K"
    if "ausfuhr" in reason:
        return "G"
    return "E"
