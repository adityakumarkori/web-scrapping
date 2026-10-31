"""Tests for the quality report service (services/quality_report.py)."""

from decimal import Decimal
from services.quality_report import (
    compute_record_quality_score,
    compute_dataset_quality_summary,
)


# ---------------------------------------------------------------------------
# compute_record_quality_score
# ---------------------------------------------------------------------------

def test_record_quality_score_missing_mandatory():
    product = {
        "article_number": "ART1",
        # product_name missing
    }
    score, flags = compute_record_quality_score(product)
    assert score == 0.0


def test_record_quality_score_all_present():
    product = {
        "article_number": "ART1",
        "product_name": "Test Product",
        "sku": "SKU1",
        "ean_gtin": "1234567890123",
        "description": "A test product",
        "short_description": "Test",
        "product_type": "type",
        "product_url": "https://example.com",
        "image_urls": ["https://example.com/img.jpg"],
        "manufacturer": "Manufacturer",
        "brand": "Brand",
        "supplier": "Supplier",
        "category": "Category",
        "subcategory": "Subcat",
        "dimensions": {"value": Decimal("10"), "unit": "cm"},
        "weight": {"value": Decimal("0.5"), "unit": "kg"},
        "material": "Plastic",
        "technical_specifications": {"key": "val"},
        "compatibility": "Works with X",
        "ce_marking_status": "CE",
        "applicable_regulations": ["Reg 1"],
        "compliance_certificates": ["Cert 1"],
        "country_of_origin": "DE",
        "inventory_status": "in_stock",
        "inventory_quantity": 10,
        "warehouse": "WH1",
        "shipping_method": "Standard",
        "delivery_days": 2,
        "price": Decimal("19.99"),
        "currency": "EUR",
        "regional_data": [
            {"country_code": "DE", "currency": "EUR", "net_price": Decimal("15.00"), "vat_rate": Decimal("20"), "gross_price": Decimal("18.00")},
        ],
        "data_origin": "authorized_api",
        "source_id": "src-001",
        "source_url": "https://example.com/source",
        "collected_at": "2024-01-15",
        "verification_status": "verified",
        "is_synthetic": False,
        "last_updated_at": None,
    }
    score, flags = compute_record_quality_score(product)
    # All mandatory present + many optional present => complete
    assert score == 1.0


def test_record_quality_score_missing_some_optional():
    product = {
        "article_number": "ART1",
        "product_name": "Test Product",
        # Many optional fields missing
    }
    score, flags = compute_record_quality_score(product)
    # Mandatory present but optional coverage low => partial
    assert score == 0.5


# ---------------------------------------------------------------------------
# compute_dataset_quality_summary
# ---------------------------------------------------------------------------

def test_dataset_quality_summary_empty():
    summary = compute_dataset_quality_summary([])
    assert summary["total_records"] == 0
    assert summary["valid_records"] == 0
    assert summary["invalid_records"] == 0
    assert summary["quality_distribution"] == {"complete": 0, "partial": 0, "incomplete": 0}
    assert summary["missing_mandatory_by_field"] == {}
    assert summary["missing_optional_by_field"] == {}
    assert summary["record_scores"] == []
    assert summary["duplicate_groups"] == []
    assert summary["overall_quality_percentage"] == 0.0


def test_dataset_quality_summary_with_products():
    products = [
        {
            "article_number": "ART1",
            "product_name": "Product A",
            "sku": "SKU1",
            "ean_gtin": "1234567890123",
            "description": "Product A",
            "short_description": "Short A",
            "product_type": "typeA",
            "product_url": "https://example.com/a",
            "image_urls": ["https://example.com/img1.jpg"],
            "manufacturer": "Man A",
            "brand": "Brand A",
            "supplier": "Supp A",
            "category": "Cat A",
            "subcategory": "Sub A",
            "dimensions": {"value": Decimal("10"), "unit": "cm"},
            "weight": {"value": Decimal("0.5"), "unit": "kg"},
            "material": "Plastic",
            "technical_specifications": {"key": "val"},
            "compatibility": "Works with X",
            "ce_marking_status": "CE",
            "applicable_regulations": ["Reg 1"],
            "compliance_certificates": ["Cert 1"],
            "country_of_origin": "DE",
            "inventory_status": "in_stock",
            "inventory_quantity": 10,
            "warehouse": "WH1",
            "shipping_method": "Standard",
            "delivery_days": 2,
            "price": Decimal("19.99"),
            "currency": "EUR",
            "regional_data": [
                {"country_code": "DE", "currency": "EUR", "net_price": Decimal("15.00"), "vat_rate": Decimal("20"), "gross_price": Decimal("18.00")},
            ],
            "data_origin": "authorized_api",
            "source_id": "src-001",
            "source_url": "https://example.com/source",
            "collected_at": "2024-01-15",
            "verification_status": "verified",
            "is_synthetic": False,
            "last_updated_at": None,
        },
        {
            "article_number": "ART2",
            "product_name": "Product B",
            # Missing many optional fields
            "price": Decimal("29.99"),
            "currency": "USD",
        },
    ]
    summary = compute_dataset_quality_summary(products)
    assert summary["total_records"] == 2
    # Record 1 is complete (score 1.0), Record 2 is partial (score 0.5) => both valid
    assert summary["valid_records"] == 2
    assert summary["invalid_records"] == 0
    assert summary["overall_quality_percentage"] == 100.0
    assert summary["quality_distribution"]["complete"] == 1
    assert summary["quality_distribution"]["partial"] == 1
    assert summary["quality_distribution"]["incomplete"] == 0