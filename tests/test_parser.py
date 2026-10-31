"""Tests for the HTML parser (scraper/parser.py).

Uses local HTML fixtures; no network access required.
"""

from pathlib import Path

import pytest

from scraper.parser import (
    extract_canonical_url,
    extract_json_ld,
    extract_meta_description,
    extract_open_graph,
    find_product_json_ld,
    parse_html,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_html():
    soup = parse_html(_read("product_jsonld.html"))
    assert soup.title is not None
    assert soup.title.get_text() == "Product Page"


def test_extract_json_ld_product():
    soup = parse_html(_read("product_jsonld.html"))
    blocks = extract_json_ld(soup)
    assert len(blocks) >= 1
    assert blocks[0]["@type"] == "Product"
    assert blocks[0]["name"] == "Granit Hex Bolt M8"


def test_find_product_json_ld():
    soup = parse_html(_read("product_jsonld.html"))
    products = find_product_json_ld(extract_json_ld(soup))
    assert len(products) == 1
    assert products[0]["name"] == "Granit Hex Bolt M8"


def test_json_ld_in_graph_is_found():
    # Build HTML where Product is nested inside @graph.
    html = """<html><body>
<script type="application/ld+json">
{"@context": "https://schema.org/", "@graph": [
  {"@type": "Organization", "name": "Org"},
  {"@type": "Product", "name": "Graph Product", "sku": "GP-1"}
]}
</script>
</body></html>"""
    soup = parse_html(html)
    products = find_product_json_ld(extract_json_ld(soup))
    assert len(products) == 1
    assert products[0]["name"] == "Graph Product"


def test_invalid_jsonld_skipped():
    soup = parse_html(_read("invalid_jsonld.html"))
    blocks = extract_json_ld(soup)
    # One invalid block skipped, one valid Product block found.
    assert any(b.get("@type") == "Product" for b in blocks)


def test_extract_open_graph():
    soup = parse_html(_read("product_metadata.html"))
    og = extract_open_graph(soup)
    assert og["og:title"] == "Granit Washer M6"
    assert og["og:description"] == "Stainless steel washer M6."
    assert og["og:image"] == "https://example.com/images/washer-m6.jpg"


def test_extract_canonical_url():
    soup = parse_html(_read("product_metadata.html"))
    assert extract_canonical_url(soup) == "https://example.com/products/washer-m6"


def test_extract_meta_description():
    soup = parse_html(_read("product_metadata.html"))
    assert extract_meta_description(soup) == "Standard meta description for washer."


def test_empty_page_no_product():
    soup = parse_html(_read("empty_product.html"))
    assert find_product_json_ld(extract_json_ld(soup)) == []
    assert extract_open_graph(soup) == {}
    assert extract_canonical_url(soup) is None
