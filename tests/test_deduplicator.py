"""Tests for the deduplication service (services/deduplicator.py)."""

from services.deduplicator import (
    detect_duplicates,
    detect_article_number_duplicates,
    detect_ean_gtin_duplicates,
    detect_canonical_url_duplicates,
    DuplicateGroup,
    should_merge_records,
)


# ---------------------------------------------------------------------------
# detect_article_number_duplicates
# ---------------------------------------------------------------------------

def test_detect_article_number_duplicates_no_dups():
    products = [
        {"article_number": "ART1", "product_name": "Product A"},
        {"article_number": "ART2", "product_name": "Product B"},
    ]
    groups = detect_article_number_duplicates(products)
    assert len(groups) == 0


def test_detect_article_number_duplicates_with_dups():
    products = [
        {"article_number": "ART1", "product_name": "Product A"},
        {"article_number": "ART1", "product_name": "Product A copy"},
        {"article_number": "ART2", "product_name": "Product B"},
    ]
    groups = detect_article_number_duplicates(products)
    assert len(groups) == 1
    assert groups[0].duplicate_type == "article_number"
    assert len(groups[0].records) == 2


def test_detect_article_number_duplicates_ignores_empty():
    products = [
        {"article_number": "", "product_name": "Product A"},
        {"article_number": "ART2", "product_name": "Product B"},
    ]
    groups = detect_article_number_duplicates(products)
    assert len(groups) == 0


# ---------------------------------------------------------------------------
# detect_ean_gtin_duplicates
# ---------------------------------------------------------------------------

def test_detect_ean_gtin_duplicates_no_dups():
    products = [
        {"ean_gtin": "1234567890123", "product_name": "Product A"},
        {"ean_gtin": "9876543210987", "product_name": "Product B"},
    ]
    groups = detect_ean_gtin_duplicates(products)
    assert len(groups) == 0


def test_detect_ean_gtin_duplicates_with_dups():
    products = [
        {"ean_gtin": "1234567890123", "product_name": "Product A"},
        {"ean_gtin": "1234567890123", "product_name": "Product A copy"},
        {"ean_gtin": "9876543210987", "product_name": "Product B"},
    ]
    groups = detect_ean_gtin_duplicates(products)
    assert len(groups) == 1
    assert groups[0].duplicate_type == "ean_gtin"
    assert len(groups[0].records) == 2


# ---------------------------------------------------------------------------
# detect_canonical_url_duplicates
# ---------------------------------------------------------------------------

def test_detect_canonical_url_duplicates_no_dups():
    products = [
        {"product_url": "https://example.com/a", "product_name": "Product A"},
        {"product_url": "https://example.com/b", "product_name": "Product B"},
    ]
    groups = detect_canonical_url_duplicates(products)
    assert len(groups) == 0


def test_detect_canonical_url_duplicates_with_dups():
    products = [
        {"product_url": "https://example.com/a", "product_name": "Product A"},
        {"product_url": "https://example.com/a", "product_name": "Product A copy"},
        {"product_url": "https://example.com/b", "product_name": "Product B"},
    ]
    groups = detect_canonical_url_duplicates(products)
    assert len(groups) == 1
    assert groups[0].duplicate_type == "canonical_url"
    assert len(groups[0].records) == 2


# ---------------------------------------------------------------------------
# detect_duplicates (combined)
# ---------------------------------------------------------------------------

def test_detect_duplicates_combined():
    products = [
        {"article_number": "ART1", "ean_gtin": "1234567890123", "product_url": "https://example.com/a", "product_name": "Product A"},
        {"article_number": "ART1", "ean_gtin": "9876543210987", "product_url": "https://example.com/b", "product_name": "Product A copy"},
        {"article_number": "ART2", "ean_gtin": "1234567890123", "product_url": "https://example.com/a", "product_name": "Product B"},
    ]
    groups = detect_duplicates(products)
    # Should find article_number duplicates and ean_gtin duplicates
    types_found = {g.duplicate_type for g in groups}
    assert "article_number" in types_found


# ---------------------------------------------------------------------------
# should_merge_records
# ---------------------------------------------------------------------------

def test_should_merge_records_same_origin():
    a = {"article_number": "ART1", "is_synthetic": False, "data_origin": "manual_entry"}
    b = {"article_number": "ART1", "is_synthetic": False, "data_origin": "manual_entry"}
    result = should_merge_records(a, b)
    assert result is True


def test_should_merge_records_different_synthetic():
    a = {"article_number": "ART1", "is_synthetic": True, "data_origin": "manual_entry"}
    b = {"article_number": "ART1", "is_synthetic": False, "data_origin": "manual_entry"}
    result = should_merge_records(a, b)
    assert result is False


def test_should_merge_records_different_origin():
    # One is manual_entry, so merge is allowed per heuristic
    a = {"article_number": "ART1", "is_synthetic": False, "data_origin": "authorized_api"}
    b = {"article_number": "ART1", "is_synthetic": False, "data_origin": "manual_entry"}
    result = should_merge_records(a, b)
    assert result is True