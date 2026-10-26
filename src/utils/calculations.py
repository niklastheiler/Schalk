from decimal import Decimal, ROUND_HALF_UP

CENT = Decimal("0.01")


def round_money(value) -> float:
    """Commercial rounding to whole cents (0.005 -> 0.01)."""
    return float(Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP))


def item_total(quantity: float, unit_price: float, discount_percent: float = 0.0) -> float:
    total = Decimal(str(quantity)) * Decimal(str(unit_price))
    if discount_percent:
        total *= (Decimal(100) - Decimal(str(discount_percent))) / Decimal(100)
    return round_money(total)


def tax_breakdown(items: list, credit_amount: float = 0.0) -> dict:
    """
    Returns {tax_percent: (net_after_credit, tax)} per tax rate.
    A credit (Gutschrift) is a net reduction; it is distributed over the tax rates in proportion
    to their net share, so the tax is reduced with the correct rate(s).
    `items` are dicts or objects with total_price and tax_percent.
    """
    nets = {}
    for item in items:
        total = item['total_price'] if isinstance(item, dict) else item.total_price
        rate = item['tax_percent'] if isinstance(item, dict) else item.tax_percent
        rate = float(rate or 0.0)
        nets[rate] = nets.get(rate, Decimal(0)) + Decimal(str(total))

    net_sum = sum(nets.values(), Decimal(0))
    credit = Decimal(str(credit_amount or 0.0))

    result = {}
    remaining_credit = credit
    rates = sorted(nets.keys())
    for idx, rate in enumerate(rates):
        net = nets[rate]
        if credit and net_sum:
            if idx == len(rates) - 1:
                share = remaining_credit # last rate takes the rounding remainder
            else:
                share = (credit * net / net_sum).quantize(CENT, rounding=ROUND_HALF_UP)
                remaining_credit -= share
            net -= share
        tax = (net * Decimal(str(rate)) / Decimal(100)).quantize(CENT, rounding=ROUND_HALF_UP)
        result[rate] = (float(net.quantize(CENT, rounding=ROUND_HALF_UP)), float(tax))
    return result


def calculate_totals(items: list, credit_amount: float = 0.0) -> dict:
    """
    Returns net_amount (before credit), credit_amount, tax_amount and gross_amount.
    gross = net - credit + tax
    """
    net = sum((Decimal(str(i['total_price'] if isinstance(i, dict) else i.total_price)) for i in items), Decimal(0))
    credit = Decimal(str(credit_amount or 0.0))
    breakdown = tax_breakdown(items, credit_amount)
    tax = sum((Decimal(str(t)) for _, t in breakdown.values()), Decimal(0))
    gross = net - credit + tax
    return {
        "net_amount": round_money(net),
        "credit_amount": round_money(credit),
        "tax_amount": round_money(tax),
        "gross_amount": round_money(gross),
    }
