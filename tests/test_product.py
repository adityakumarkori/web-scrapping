"""Tests for the final Pydantic product data model (models/product.py).

Covers product master fields, regional data validation, multiple regional
entries, monetary validation, and data provenance. No live server required.
"""

from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from models.product import (
    DATA_ORIGINS,
    Product,
    RegionalDataEntry,
    VERIFICATION_STATUSES,
)


def _base_product() -> dict:
    return {
        "article_number": "GRAN-1001",
        "product_name": "Example Granit Product",
        "data_origin": "manual_entry",
    }


def test_minimal_product_valid():
    product = Product(**_base_product())
    assert product.article_number == "GRAN-1001"
    assert product.product_name == "Example Granit Product"
    assert product.data_origin == "manual_entry"
    assert product.verification_status == "not_verified"
    assert product.is_synthetic is False


def test_all_sections_populated():
    data = _base_product()
    data.update(
        {
            "sku": "SKU-001",
            "ean_gtin": "1234567890123",
            "description": "A desc",
            "short_description": "Short",
            "product_type": "part",
            "product_url": "https://example.com/product/1",
            "image_urls": ["https://example.com/img1.jpg"],
            "manufacturer": "Granit Mfg",
            "brand": "Granit",
            "supplier": "Supplier X",
            "category": "Fasteners",
            "subcategory": "Screws",
            "dimensions": {"length": 10, "width": 5, "unit": "mm"},
            "weight": {"value": 0.2, "unit": "kg"},
            "material": "Steel",
            "technical_specifications": {"thread": "M6"},
            "compatibility": "Model A",
            "ce_marking_status": "compliant",
            "applicable_regulations": ["RoHS", "REACH"],
            "compliance_certificates": ["ISO 9001"],
            "country_of_origin": "DE",
            "inventory_status": "in_stock",
            "inventory_quantity": 50,
            "warehouse": "WH-1",
            "shipping_method": "parcel",
            "delivery_days": 3,
            "data_origin": "authorized_api",
            "verification_status": "verified",
            "is_synthetic": False,
        }
    )
    product = Product(**data)
    assert product.category == "Fasteners"
    assert product.inventory_quantity == 50
    assert product.verification_status == "verified"


def test_optional_fields_nullable():
    product = Product(**_base_product())
    assert product.sku is None
    assert product.ean_gtin is None
    assert product.brand is None
    assert product.regional_data is None
    assert product.source_id is None


def test_missing_mandatory_field_raises():
    data = _base_product()
    del data["article_number"]
    with pytest.raises(ValidationError):
        Product(**data)


def test_regional_data_single_entry():
    data = _base_product()
    data["regional_data"] = [
        {
            "country": "Germany",
            "country_code": "DE",
            "currency": "EUR",
            "net_price": Decimal("100.00"),
            "vat_rate": Decimal("19.00"),
            "gross_price": Decimal("119.00"),
            "price_source": "vendor_pricelist",
            "effective_date": datetime(2026, 1, 1),
        }
    ]
    product = Product(**data)
    assert len(product.regional_data) == 1
    entry = product.regional_data[0]
    assert entry.country_code == "DE"
    assert entry.currency == "EUR"
    assert entry.net_price == Decimal("100.00")
    assert entry.gross_price == Decimal("119.00")


def test_regional_data_multiple_entries():
    data = _base_product()
    data["regional_data"] = [
        {"country": "Germany", "country_code": "DE", "currency": "EUR", "net_price": Decimal("100.00")},
        {"country": "France", "country_code": "FR", "currency": "EUR", "net_price": Decimal("105.00")},
        {"country": "Italy", "country_code": "IT", "currency": "EUR", "net_price": Decimal("110.00")},
    ]
    product = Product(**data)
    assert len(product.regional_data) == 3
    codes = {e.country_code for e in product.regional_data}
    assert codes == {"DE", "FR", "IT"}


def test_country_code_must_be_two_uppercase_letters():
    data = _base_product()
    data["regional_data"] = [
        {"country": "Germany", "country_code": "de", "currency": "EUR"}
    ]
    with pytest.raises(ValidationError):
        Product(**data)

    data["regional_data"] = [
        {"country": "Germany", "country_code": "DEU", "currency": "EUR"}
    ]
    with pytest.raises(ValidationError):
        Product(**data)


def test_currency_must_be_three_uppercase_letters():
    data = _base_product()
    data["regional_data"] = [
        {"country": "Germany", "country_code": "DE", "currency": "eur"}
    ]
    with pytest.raises(ValidationError):
        Product(**data)

    data["regional_data"] = [
        {"country": "Germany", "country_code": "DE", "currency": "EURO"}
    ]
    with pytest.raises(ValidationError):
        Product(**data)


def test_prices_non_negative():
    data = _base_product()
    data["regional_data"] = [
        {"country": "Germany", "country_code": "DE", "currency": "EUR", "net_price": Decimal("-10.00")}
    ]
    with pytest.raises(ValidationError):
        Product(**data)

    data["regional_data"] = [
        {"country": "Germany", "country_code": "DE", "currency": "EUR", "gross_price": Decimal("-5.00")}
    ]
    with pytest.raises(ValidationError):
        Product(**data)


def test_vat_rate_range_0_to_100():
    data = _base_product()
    data["regional_data"] = [
        {"country": "Germany", "country_code": "DE", "currency": "EUR", "vat_rate": Decimal("150.00")}
    ]
    with pytest.raises(ValidationError):
        Product(**data)

    data["regional_data"] = [
        {"country": "Germany", "country_code": "DE", "currency": "EUR", "vat_rate": Decimal("-5.00")}
    ]
    with pytest.raises(ValidationError):
        Product(**data)


def test_gross_price_consistency():
    # net 100, vat 19 -> gross should be 119 (within tolerance)
    data = _base_product()
    data["regional_data"] = [
        {
            "country": "Germany",
            "country_code": "DE",
            "currency": "EUR",
            "net_price": Decimal("100.00"),
            "vat_rate": Decimal("19.00"),
            "gross_price": Decimal("119.00"),
        }
    ]
    product = Product(**data)
    assert product.regional_data[0].gross_price == Decimal("119.00")

    # inconsistent gross price should fail
    data["regional_data"] = [
        {
            "country": "Germany",
            "country_code": "DE",
            "currency": "EUR",
            "net_price": Decimal("100.00"),
            "vat_rate": Decimal("19.00"),
            "gross_price": Decimal("200.00"),
        }
    ]
    with pytest.raises(ValidationError):
        Product(**data)


def test_gross_price_consistency_skipped_when_incomplete():
    # Only net and vat present, no gross -> no consistency check needed
    data = _base_product()
    data["regional_data"] = [
        {
            "country": "Germany",
            "country_code": "DE",
            "currency": "EUR",
            "net_price": Decimal("100.00"),
            "vat_rate": Decimal("19.00"),
        }
    ]
    product = Product(**data)
    assert product.regional_data[0].gross_price is None


def test_decimal_coercion_from_string():
    data = _base_product()
    data["regional_data"] = [
        {
            "country": "Germany",
            "country_code": "DE",
            "currency": "EUR",
            "net_price": "100.00",
            "vat_rate": "19",
            "gross_price": "119.00",
        }
    ]
    product = Product(**data)
    assert product.regional_data[0].net_price == Decimal("100.00")
    assert product.regional_data[0].vat_rate == Decimal("19")
    assert product.regional_data[0].gross_price == Decimal("119.00")


def test_data_origin_validation():
    for origin in DATA_ORIGINS:
        data = _base_product()
        data["data_origin"] = origin
        product = Product(**data)
        assert product.data_origin == origin

    data = _base_product()
    data["data_origin"] = "black_market"
    with pytest.raises(ValidationError):
        Product(**data)


def test_verification_status_validation():
    for status in VERIFICATION_STATUSES:
        data = _base_product()
        data["verification_status"] = status
        product = Product(**data)
        assert product.verification_status == status

    data = _base_product()
    data["verification_status"] = "unknown"
    with pytest.raises(ValidationError):
        Product(**data)


def test_synthetic_cannot_be_verified():
    data = _base_product()
    data["is_synthetic"] = True
    data["verification_status"] = "verified"
    with pytest.raises(ValidationError):
        Product(**data)

    # Synthetic but not verified is allowed
    data["verification_status"] = "not_verified"
    product = Product(**data)
    assert product.is_synthetic is True
    assert product.verification_status == "not_verified"


def test_provenance_fields_defaults():
    product = Product(**_base_product())
    assert product.data_origin == "manual_entry"
    assert product.source_id is None
    assert product.source_url is None
    assert product.collected_at is None
    assert product.verification_status == "not_verified"
    assert product.is_synthetic is False
    assert product.last_updated_at is None


def test_image_urls_validation():
    data = _base_product()
    data["image_urls"] = ["https://example.com/a.jpg", "https://example.com/b.jpg"]
    product = Product(**data)
    assert len(product.image_urls) == 2

    data["image_urls"] = ["", "https://example.com/b.jpg"]
    with pytest.raises(ValidationError):
        Product(**data)
