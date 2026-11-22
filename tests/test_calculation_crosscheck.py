"""
Independent check of the invoice arithmetic: random invoices (fixed seed) are computed a second time with a
straightforward reference implementation and compared with the stored amounts, with the e-invoice XML read
back and with the official EN 16931 rules (BR-CO-10 ff.: sums, BR-CO-17: VAT per rate).
"""
import random
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from src.utils.einvoice_parser import parse_einvoice_xml
from src.utils.einvoice_validation import validate_en16931
from src.utils.zugferd_generator import build_cii_xml

DAY = datetime(2026, 10, 1, tzinfo=timezone.utc)
UNITS = ["Stück", "Stunde", "kg", "m", "Pauschale", "Liter"]


def _cent(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _reference(items: list, credit: Decimal) -> dict:
    """Textbook computation: line = qty x price x (1 - discount), rounded; VAT per rate on the rounded base."""
    lines = [_cent(Decimal(str(i["quantity"])) * Decimal(str(i["unit_price"]))
                   * (1 - Decimal(str(i.get("discount_percent", 0))) / 100)) for i in items]
    net = sum(lines, Decimal(0))
    by_rate = {}
    for item, line in zip(items, lines):
        by_rate[item["tax_percent"]] = by_rate.get(item["tax_percent"], Decimal(0)) + line
    # The credit is split over the rates in proportion to their net amounts, the last rate takes the remainder
    rates, remaining, tax = sorted(by_rate), credit, Decimal(0)
    for index, rate in enumerate(rates):
        share = remaining if index == len(rates) - 1 else _cent(credit * by_rate[rate] / net) if net else Decimal(0)
        remaining -= share
        tax += _cent((by_rate[rate] - share) * Decimal(str(rate)) / 100)
    return {"net": net, "tax": tax, "gross": net - credit + tax}


def _random_items(rng: random.Random) -> list:
    items = []
    for _ in range(rng.randint(1, 8)):
        item = {"title": f"Position {len(items) + 1}", "unit": rng.choice(UNITS),
                "quantity": rng.choice([1, 2, 3, 0.5, 0.25, 1.333, 7.5, 12, 0.001, 1000]),
                "unit_price": rng.choice([0.01, 0.99, 1.0, 9.995, 19.99, 33.333, 100.0, 1234.56, 0.4375, 99999.99]),
                "tax_percent": rng.choice([19.0, 7.0])}
        if rng.random() < 0.3:
            item["discount_percent"] = rng.choice([1, 2.5, 10, 33.33, 50, 99.99])
        items.append(item)
    return items


def test_random_invoices_match_reference_xml_and_rules(controller, seller):
    c = controller
    rng = random.Random(20261122)
    customer_id = c.add_customer(company_name="Kunde AG", address="Weg 2", postal_code="20095", city="Hamburg")
    for _ in range(60):
        items = _random_items(rng)
        reference = _reference(items, Decimal(0))
        credit = _cent(reference["net"] * Decimal(rng.choice([0, 0, 0.01, 0.1, 0.5]))) if reference["net"] > 1 else Decimal(0)
        reference = _reference(items, credit)
        invoice_id = c.create_invoice(customer_id, DAY, DAY, items, credit_amount=float(credit), credit_desc="Nachlass")
        invoice = c.get_invoice(invoice_id)
        stored = (Decimal(str(invoice.net_amount)), Decimal(str(invoice.tax_amount)), Decimal(str(invoice.gross_amount)))
        assert stored == (reference["net"], reference["tax"], reference["gross"]), items

        xml = build_cii_xml(invoice, c, "en16931")
        assert validate_en16931(xml) == [], items
        data = parse_einvoice_xml(xml)
        assert Decimal(str(data.tax_amount)) == reference["tax"]
        assert Decimal(str(data.gross_amount)) == reference["gross"] == Decimal(str(data.payable_amount))
        assert Decimal(str(data.net_amount)) == reference["net"] - credit
        assert sum(Decimal(str(line.line_total)) for line in data.lines) == reference["net"]


def test_cancellation_mirrors_the_invoice_exactly(controller, seller):
    c = controller
    rng = random.Random(7)
    customer_id = c.add_customer(company_name="Kunde AG", address="Weg 2", postal_code="20095", city="Hamburg")
    for _ in range(10):
        invoice_id = c.create_invoice(customer_id, DAY, DAY, _random_items(rng), status="Offen")
        storno = c.get_invoice(c.cancel_invoice(invoice_id))
        original = c.get_invoice(invoice_id)
        assert (storno.net_amount, storno.tax_amount, storno.gross_amount) == \
               (-original.net_amount, -original.tax_amount, -original.gross_amount)
        xml = build_cii_xml(storno, c, "en16931")
        assert validate_en16931(xml) == []
        data = parse_einvoice_xml(xml)
        # Credit note (381) with positive amounts that equal the cancelled invoice
        assert data.type_code == "381" and data.gross_amount == original.gross_amount
