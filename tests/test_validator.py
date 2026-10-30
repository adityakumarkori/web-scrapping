"""Tests for the validation service (services/validator.py)."""

from decimal import Decimal
from core.logging import get_logger

from services.validator import (
    validate_ean_gtin,
    validate_gtin,
    validate_country_code,
    validate_currency_code,
    validate_regional_price,
    validate_url,
    validate_required_fields,
    validate_provenance,
    identify_inconsistencies,
)

# ---------------------------------------------------------------------------
# validate_ean_gtin / validate_gtin
# ---------------------------------------------------------------------------

def test_validate_ean_gtin_ean13_valid():
    is_valid, gtin_type = validate_ean_gtin("5901234567893")
    assert is_valid is True
    assert gtin_type == "EAN-13"


def test_validate_ean_gtin_ean13_invalid_check():
    is_valid, gtin_type = validate_ean_gtin("5901234567890")
    assert is_valid is False


def test_validate_ean_gtin_gtin12():
    # Valid GTIN-12: computed check digit from "01234567891" is 4, so full number is "012345678914"
    is_valid, gtin_type = validate_ean_gtin("012345678914")
    assert is_valid is True
    assert gtin_type == "GTIN-12"


def test_validate_ean_gtin_ean8():
    # Valid EAN-8: "12345678" has check digit 8
    is_valid, gtin_type = validate_ean_gtin("12345678")
    assert is_valid is True
    assert gtin_type == "EAN-8"


def test_validate_ean_gtin_gtin14():
    # GTIN-14 with group prefix 0, inner 13 digits form valid EAN-13
    # EAN-13 "5901234567893" is valid, so GTIN-14 "05901234567893" should be valid
    is_valid, gtin_type = validate_ean_gtin("05901234567893")
    assert is_valid is True
    assert gtin_type == "GTIN-14"


def test_validate_ean_gtin_invalid_length():
    is_valid, gtin_type = validate_ean_gtin("12345")
    assert is_valid is False


def test_validate_ean_gtin_non_string():
    is_valid, gtin_type = validate_ean_gtin(1234567890123)
    assert is_valid is False


# ---------------------------------------------------------------------------
# validate_country_code
# ---------------------------------------------------------------------------

def test_validate_country_code_eu():
    assert validate_country_code("DE") is True
    assert validate_country_code("FR") is True
    assert validate_country_code("ES") is True


def test_validate_country_code_non_eu():
    assert validate_country_code("US") is False
    assert validate_country_code("CN") is False


def test_validate_country_code_lowercase():
    # Validator normalizes to uppercase, so "de" is valid
    assert validate_country_code("de") is True


def test_validate_country_code_invalid():
    assert validate_country_code("ABC") is False


# ---------------------------------------------------------------------------
# validate_currency_code
# ---------------------------------------------------------------------------

def test_validate_currency_code_euro():
    assert validate_currency_code("EUR") is True


def test_validate_currency_code_usd():
    assert validate_currency_code("USD") is True


def test_validate_currency_code_gbp():
    assert validate_currency_code("GBP") is True


def test_validate_currency_code_invalid():
    assert validate_currency_code("EURR") is False
    assert validate_currency_code("XY") is False


def test_validate_currency_code_lowercase():
    # Validator normalizes to uppercase, so "eur" is valid
    assert validate_currency_code("eur") is True


# ---------------------------------------------------------------------------
# validate_regional_price
# ---------------------------------------------------------------------------

def test_validate_regional_price_all_good():
    msg = validate_regional_price(
        Decimal("10.00"),
        Decimal("20"),
        Decimal("12.00"),
        "EUR",
        "DE",
    )
    assert msg is None


def test_validate_regional_price_negative():
    msg = validate_regional_price(
        Decimal("-5.00"),
        None,
        None,
        None,
        None,
    )
    assert "price must be non-negative" in msg


def test_validate_regional_price_vat_out_of_range():
    msg = validate_regional_price(
        Decimal("10.00"),
        Decimal("150"),
        None,
        "EUR",
        "DE",
    )
    assert "vat_rate must be between 0 and 100" in msg


def test_validate_regional_price_inconsistency():
    msg = validate_regional_price(
        Decimal("10.00"),
        Decimal("20"),
        Decimal("25.00"),  # 10 * 1.20 = 12.00, not 25.00
        "EUR",
        "DE",
    )
    assert "inconsistent" in msg


# ---------------------------------------------------------------------------
# validate_url
# ---------------------------------------------------------------------------

def test_validate_url_valid():
    ok, msg = validate_url("https://example.com/product")
    assert ok is True
    assert msg is None


def test_validate_url_http():
    ok, msg = validate_url("http://example.com")
    assert ok is True


def test_validate_url_empty():
    ok, msg = validate_url("")
    assert ok is False


def test_validate_url_non_string():
    ok, msg = validate_url(123)
    assert ok is False


# ---------------------------------------------------------------------------
# validate_required_fields
# ---------------------------------------------------------------------------

def test_validate_required_fields_all_present():
    product = {
        "article_number": "ART123",
        "product_name": "Test Product",
    }
    is_valid, missing = validate_required_fields(product)
    assert is_valid is True
    assert missing == []


def test_validate_required_fields_missing():
    product = {
        "article_number": "ART123",
    }
    is_valid, missing = validate_required_fields(product)
    assert is_valid is False
    assert "product_name" in missing


# ---------------------------------------------------------------------------
# validate_provenance
# ---------------------------------------------------------------------------

def test_validate_provenance_ok():
    product = {
        "data_origin": "manual_entry",
        "verification_status": "not_verified",
        "is_synthetic": False,
        "source_url": "https://example.com",
    }
    ok, msg = validate_provenance(product)
    assert ok is True
    assert msg is None


def test_validate_provenance_synthetic_verified():
    product = {
        "data_origin": "synthetic",
        "verification_status": "verified",
        "is_synthetic": True,
    }
    ok, msg = validate_provenance(product)
    assert ok is False
    assert "must not be marked as verified" in msg


def test_validate_provenance_bad_data_origin():
    product = {
        "data_origin": "invalid_origin",
    }
    ok, msg = validate_provenance(product)
    assert ok is False


# ---------------------------------------------------------------------------
# identify_inconsistencies
# ---------------------------------------------------------------------------

def test_identify_inconsistencies_price_vs_regional():
    product = {
        "article_number": "ART1",
        "product_name": "Test",
        "price": Decimal("10.00"),
        "regional_data": [
            {"country_code": "DE", "currency": "EUR", "net_price": Decimal("8.00"), "vat_rate": Decimal("20"), "gross_price": Decimal("9.60")},
        ],
    }
    issues = identify_inconsistencies(product)
    assert len(issues) > 0
    # Should flag that top-level price coexists with regional_data
    issue_topics = [i["field"] for i in issues]
    assert any("price" in t for t in issue_topics)


def test_identify_inconsistencies_ean_conflict():
    product = {
        "article_number": "ART1",
        "product_name": "Test",
        "ean_gtin": "1234567890123",
        "regional_data": [
            {"country_code": "DE", "currency": "EUR", "ean_gtin": "9876543210987"},
            {"country_code": "FR", "currency": "EUR", "ean_gtin": "1234567890123"},
        ],
    }
    issues = identify_inconsistencies(product)
    assert len(issues) > 0
    issue_topics = [i["field"] for i in issues]
    assert any("ean_gtin" in t for t in issue_topics)


def test_identify_inconsistencies_url_conflict():
    product = {
        "article_number": "ART1",
        "product_name": "Test",
        "source_url": "https://example.com/a",
        "product_url": "https://example.com/b",
    }
    issues = identify_inconsistencies(product)
    assert len(issues) > 0
    issue_topics = [i["field"] for i in issues]
    assert any("source_url" in t for t in issue_topics)