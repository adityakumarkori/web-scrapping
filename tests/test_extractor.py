"""Tests for the product extractor (scraper/extractor.py).

Uses local HTML fixtures; no network access required.
"""

from decimal import Decimal

import pytest

from scraper.extractor import (
    build_product,
    extract_from_json_ld,
    extract_from_metadata,
    extract_regional_data,
    extract_visible_content,
)
from scraper.exceptions import ExtractionError


def test_extract_from_json_ld():
    product_json = {
        "@type": "Product",
        "name": "Granit Hex Bolt M8",
        "sku": "HB-M8-100",
        "gtin": "4012345678901",
        "brand": {"@type": "Brand", "name": "Granit"},
        "manufacturer": "Granit Manufacturing GmbH",
        "description": "High-strength hex bolt.",
        "url": "https://example.com/products/bolt",
        "image": "https://example.com/images/bolt.jpg",
        "offers": {
            "price": "12.50",
            "priceCurrency": "EUR",
            "availability": "https://schema.org/InStock",
        },
    }
    data = extract_from_json_ld(product_json, base_url="https://example.com")
    assert data["product_name"] == "Granit Hex Bolt M8"
    assert data["sku"] == "HB-M8-100"
    assert data["ean_gtin"] == "4012345678901"
    assert data["brand"] == "Granit"
    assert data["manufacturer"] == "Granit Manufacturing GmbH"
    assert data["price"] == Decimal("12.50")
    assert data["currency"] == "EUR"
    assert data["image_urls"] == ["https://example.com/images/bolt.jpg"]


def test_extract_from_metadata():
    html = """<html><head>
<meta property="og:title" content="Granit Washer M6" />
<meta property="og:image" content="https://example.com/images/w.jpg" />
<meta property="og:url" content="https://example.com/products/w" />
<meta name="description" content="A washer." />
</head><body></body></html>"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    data = extract_from_metadata(soup, base_url="https://example.com")
    assert data["product_name"] == "Granit Washer M6"
    assert data["description"] == "A washer."
    assert data["product_url"] == "https://example.com/products/w"


def test_extract_visible_content():
    html = """<html><body>
<h1>Granit Nut M10</h1>
<span itemprop="sku">NT-M10-50</span>
<div class="product-description">Hex nut M10.</div>
<span class="brand">Granit</span>
<span class="manufacturer">Granit Mfg</span>
<div class="category">Fasteners</div>
<img class="product-image" src="/images/nut.jpg" />
<table class="product-specs">
<tr><th>Material</th><td>Steel</td></tr>
</table>
</body></html>"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    data = extract_visible_content(soup, base_url="https://example.com")
    assert data["product_name"] == "Granit Nut M10"
    assert data["article_number"] == "NT-M10-50"
    assert data["brand"] == "Granit"
    assert data["manufacturer"] == "Granit Mfg"
    assert data["category"] == "Fasteners"
    assert data["image_urls"] == ["https://example.com/images/nut.jpg"]
    assert data["technical_specifications"] == {"Material": "Steel"}


def test_extract_regional_data():
    prices = [
        {"country": "Germany", "country_code": "de", "currency": "eur", "net_price": "10.00", "vat_rate": "19", "gross_price": "11.90"},
        {"country": "France", "country_code": "FR", "currency": "EUR", "net_price": "10.50"},
        {"country_code": "IT", "currency": "EUR"},  # missing country name OK
        {"country": "NoCode", "currency": "EUR"},  # missing country_code -> skipped
    ]
    entries = extract_regional_data(prices)
    assert len(entries) == 3
    assert entries[0]["country_code"] == "DE"
    assert entries[0]["currency"] == "EUR"
    assert entries[0]["net_price"] == Decimal("10.00")
    assert entries[0]["vat_rate"] == Decimal("19")
    assert entries[0]["gross_price"] == Decimal("11.90")
    assert entries[1]["net_price"] == Decimal("10.50")
    assert entries[1].get("gross_price") is None


def test_extract_regional_data_none():
    assert extract_regional_data(None) is None
    assert extract_regional_data([]) is None


def test_build_product_valid():
    data = {
        "article_number": "HB-M8-100",
        "product_name": "Granit Hex Bolt M8",
        "sku": "HB-M8-100",
        "ean_gtin": "4012345678901",
        "brand": "Granit",
        "price": Decimal("12.50"),
        "currency": "EUR",
        "image_urls": ["https://example.com/images/bolt.jpg"],
    }
    product = build_product(data, "src-1", "https://example.com/products/bolt")
    assert product.article_number == "HB-M8-100"
    assert product.product_name == "Granit Hex Bolt M8"
    assert product.data_origin == "approved_public_source"
    assert product.source_id == "src-1"
    assert product.source_url == "https://example.com/products/bolt"
    assert product.verification_status == "not_verified"
    assert product.is_synthetic is False
    assert product.price == Decimal("12.50")
    assert product.currency == "EUR"


def test_build_product_missing_identifiers():
    data = {"sku": "X", "description": "No name or article number"}
    with pytest.raises(ExtractionError, match="mandatory product identifiers"):
        build_product(data, "src-1", "https://example.com")

    data = {"article_number": "X"}
    with pytest.raises(ExtractionError):
        build_product(data, "src-1", "https://example.com")


def test_build_product_authorized_api_origin():
    data = {
        "article_number": "API-1",
        "product_name": "API Product",
    }
    product = build_product(data, "src-1", "https://api.example.com", data_origin="authorized_api")
    assert product.data_origin == "authorized_api"
