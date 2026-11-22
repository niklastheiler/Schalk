import pytest
from src.utils.validation import (contact_problems, is_valid_email, is_valid_phone, is_valid_postal_code,
                                  is_valid_tax_number)


@pytest.mark.parametrize("value,ok", [
    ("info@firma.de", True), ("max.muster@sub.firma-x.com", True), ("a@b.co", True),
    ("info@firma", False), ("info.firma.de", False), ("in fo@firma.de", False), ("a@@b.de", False), ("@firma.de", False),
    ("info@firma.d", False),
])
def test_email(value, ok):
    assert is_valid_email(value) is ok


@pytest.mark.parametrize("value,ok", [
    ("030 123456", True), ("+49 (0)30 / 123-456", True), ("0171 2345678", True),
    ("12345", False), ("030 abc 123", False), ("03+0 123456", False), ("+49 1234 5678 9012 3456", False),
])
def test_phone(value, ok):
    assert is_valid_phone(value) is ok


@pytest.mark.parametrize("value,country,ok", [
    ("10115", "DE", True), ("1011", "DE", False), ("101155", "DE", False), ("1O115", "DE", False),
    ("1010", "AT", True), ("90-001", "PL", True), ("SW1A 1AA", "GB", True), ("---", "FR", False),
])
def test_postal_code(value, country, ok):
    assert is_valid_postal_code(value, country) is ok


def test_tax_number():
    assert is_valid_tax_number("12/345/67890")
    assert not is_valid_tax_number("12345")


def test_contact_problems_name_the_field():
    problems = contact_problems({"postal_code": "123", "phone": "abc", "email": "x"}, "des Kunden")
    assert len(problems) == 3 and all("des Kunden" in p for p in problems)
    assert contact_problems({"postal_code": "", "phone": "", "email": ""}, "des Kunden") == []


@pytest.mark.parametrize("typed,shown", [
    ("1", "1"), ("12", "12/"), ("12/", "12/"), ("123", "12/3"), ("12//3", "12/3"), ("12345", "12/345/"),
    ("1234567890", "12/345/67890"), ("12345678901", "123/456/78901"), ("1234567890123", "1234567890123"),
    ("12345678901234", "1234567890123"),
])
def test_tax_number_format(typed, shown):
    from src.utils.validation import format_tax_number
    assert format_tax_number(typed) == shown
