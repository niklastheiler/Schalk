"""German number, money and payment term texts shared by the PDFs, the e-invoice and the user interface."""


def _german(text: str) -> str:
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_money(value: float) -> str:
    # German format: 1.234,56 €; "+ 0.0" turns -0.0 (e.g. the 0 % VAT of a cancellation) into 0,00
    return _german(f"{round(value, 2) + 0.0:,.2f} €")


def fmt_number(value: float, decimals: int = 4) -> str:
    """Quantities and percentages with up to four decimals, without trailing zeros: 2 / 2,5 / 2,375"""
    text = _german(f"{round(value, decimals) + 0.0:,.{decimals}f}")
    return text.rstrip("0").rstrip(",")


def fmt_price(value: float) -> str:
    """Unit price with two decimals, more only if the price has them (0,4375 €)."""
    return fmt_money(value) if round(value, 2) == round(value, 4) else f"{fmt_number(value)} €"


def payment_terms_text(days: int) -> str:
    """'innerhalb von 14 Tagen', 'innerhalb von 1 Tag' or 'sofort'"""
    if days <= 0:
        return "sofort"
    return "innerhalb von 1 Tag" if days == 1 else f"innerhalb von {days} Tagen"
