"""Tests for the data cleaning service (services/cleaner.py)."""

from decimal import Decimal
from core.logging import get_logger

from services.cleaner import (
    clean_nullable_string,
    clean_nullable_list,
    normalize_currency_code,
    normalize_decimal_value,
    normalize_date_value,
    normalize_dimension_value,
    clean_source_url,
    clean_product_dict,
)

# ---------------------------------------------------------------------------
# clean_nullable_string
# ---------------------------------------------------------------------------

def test_clean_nullable_string_none():
    assert clean_nullable_string(None) is None


def test_clean_nullable_string_empty():
    assert clean_nullable_string("") is None


def test_clean_nullable_string_whitespace():
    assert clean_nullable_string("   ") is None


def test_clean_nullable_string_valid():
    assert clean_nullable_string("  hello world  ") == "hello world"


def test_clean_nullable_string_non_string():
    assert clean_nullable_string(123) is None


# ---------------------------------------------------------------------------
# clean_nullable_list
# ---------------------------------------------------------------------------

def test_clean_nullable_list_none():
    assert clean_nullable_list(None) is None


def test_clean_nullable_list_empty():
    assert clean_nullable_list([]) is None


def test_clean_nullable_list_with_valid_items():
    assert clean_nullable_list(["  a  ", "  b  "]) == ["a", "b"]


def test_clean_nullable_list_all_empty():
    assert clean_nullable_list(["", "  "]) is None


# ---------------------------------------------------------------------------
# normalize_currency_code
# ---------------------------------------------------------------------------

def test_normalize_currency_code_euro():
    assert normalize_currency_code("eur") == "EUR"


def test_normalize_currency_code_usd():
    assert normalize_currency_code("  USD  ") == "USD"


def test_normalize_currency_code_invalid():
    assert normalize_currency_code("USDollar") is None


def test_normalize_currency_code_none():
    assert normalize_currency_code(None) is None


# ---------------------------------------------------------------------------
# normalize_decimal_value
# ---------------------------------------------------------------------------

def test_normalize_decimal_value_int():
    assert normalize_decimal_value(42) == Decimal("42")


def test_normalize_decimal_value_float():
    assert normalize_decimal_value(3.14) == Decimal("3.14")


def test_normalize_decimal_value_string():
    assert normalize_decimal_value("12.50") == Decimal("12.50")


def test_normalize_decimal_value_string_with_commas():
    assert normalize_decimal_value("1,234.56") == Decimal("1234.56")


def test_normalize_decimal_value_none():
    assert normalize_decimal_value(None) is None


def test_normalize_decimal_value_bool():
    assert normalize_decimal_value(True) is None


# ---------------------------------------------------------------------------
# normalize_date_value
# ---------------------------------------------------------------------------

def test_normalize_date_value_datetime():
    from datetime import datetime
    dt = datetime(2024, 3, 15)
    result = normalize_date_value(dt)
    assert result == "2024-03-15"


def test_normalize_date_value_string_iso():
    assert normalize_date_value("2024-03-15") == "2024-03-15"


def test_normalize_date_value_string_us():
    assert normalize_date_value("03/15/2024") == "2024-03-15"


def test_normalize_date_value_none():
    assert normalize_date_value(None) is None


# ---------------------------------------------------------------------------
# normalize_dimension_value
# ---------------------------------------------------------------------------

def test_normalize_dimension_value_dict():
    result = normalize_dimension_value({"value": Decimal("10"), "unit": "cm"})
    assert result == {"value": Decimal("10"), "unit": "cm"}


def test_normalize_dimension_value_str_with_x():
    # Test triple-dimension pattern "10 x 20 x 5 cm"
    result = normalize_dimension_value("10 x 20 x 5 cm")
    assert result is not None
    assert "value" in result and "unit" in result


def test_normalize_dimension_value_str_single():
    result = normalize_dimension_value("500ml")
    assert result is not None


def test_normalize_dimension_value_none():
    assert normalize_dimension_value(None) is None


# ---------------------------------------------------------------------------
# clean_source_url
# ---------------------------------------------------------------------------

def test_clean_source_url_valid():
    result = clean_source_url("https://example.com/product/123")
    assert result == "https://example.com/product/123"


def test_clean_source_url_missing_scheme():
    result = clean_source_url("example.com/product/123")
    # Scheme gets added as https://
    assert result.startswith("https://")


def test_clean_source_url_empty():
    assert clean_source_url("") is None


def test_clean_source_url_none():
    assert clean_source_url(None) is None


# ---------------------------------------------------------------------------
# clean_product_dict
# ---------------------------------------------------------------------------

def test_clean_product_dict_basic():
    raw = {
        "product_name": "  Test Product  ",
        "price": "  19.99  ",
        "currency": " usd ",
        "ean_gtin": "  ",
        "description": None,
    }
    result = clean_product_dict(raw)
    assert result["product_name"] == "Test Product"
    assert result["price"] == Decimal("19.99")
    assert result["currency"] == "USD"
    assert result["ean_gtin"] is None
    assert result["description"] is None


def test_clean_product_dict_preserves_provenance():
    raw = {
        "product_name": "Test",
        "data_origin": "authorized_api",
        "source_id": "src-001",
        "source_url": "https://example.com",
        "collected_at": "2024-01-15",
        "verification_status": "verified",
        "is_synthetic": False,
    }
    result = clean_product_dict(raw)
    assert result["data_origin"] == "authorized_api"
    assert result["source_id"] == "src-001"
    assert result["source_url"] == "https://example.com"
    assert result["collected_at"] == "2024-01-15"
    assert result["verification_status"] == "verified"
    assert result["is_synthetic"] is False