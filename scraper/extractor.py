"""Product extraction from parsed HTML.

Converts parsed page information into normalized product candidates
following the existing Pydantic product data model. Missing mandatory
identifiers cause an ExtractionError so callers can skip rather than
fabricate product data.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from core.logging import get_logger
from models.product import Product, RegionalDataEntry
from scraper.exceptions import ExtractionError
from scraper.parser import (
    extract_canonical_url,
    extract_json_ld,
    extract_meta_description,
    extract_open_graph,
    find_product_json_ld,
    parse_html,
)

logger = get_logger(__name__)


def _clean_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def _first_text(soup: BeautifulSoup, selectors: List[str]) -> Optional[str]:
    for selector in selectors:
        try:
            el = soup.select_one(selector)
        except Exception:
            continue
        if el:
            return _clean_text(el.get_text(" ", strip=True))
    return None


def _safe_decimal(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _resolve_url(value: Optional[str], base_url: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if base_url:
        return urljoin(base_url, value)
    return value


def _resolve_urls(values: Optional[List[str]], base_url: Optional[str]) -> Optional[List[str]]:
    if not values:
        return None
    resolved = [_resolve_url(v, base_url) for v in values if v]
    return resolved or None


def extract_from_json_ld(product_json: dict, base_url: Optional[str] = None) -> dict:
    """Extract product fields from a schema.org Product JSON-LD object."""
    data: dict = {}

    data["product_name"] = _clean_text(product_json.get("name"))
    data["sku"] = _clean_text(product_json.get("sku"))
    data["ean_gtin"] = _clean_text(product_json.get("gtin") or product_json.get("ean"))
    data["description"] = _clean_text(product_json.get("description"))

    brand = product_json.get("brand")
    if isinstance(brand, dict):
        data["brand"] = _clean_text(brand.get("name"))
    elif isinstance(brand, str):
        data["brand"] = _clean_text(brand)

    data["manufacturer"] = _clean_text(product_json.get("manufacturer"))
    data["product_url"] = _resolve_url(
        _clean_text(product_json.get("url")), base_url
    )

    image = product_json.get("image")
    if isinstance(image, str):
        data["image_urls"] = _resolve_urls([image], base_url)
    elif isinstance(image, list):
        data["image_urls"] = _resolve_urls([str(i) for i in image if i], base_url)
    elif isinstance(image, dict):
        data["image_urls"] = _resolve_urls([image.get("url")], base_url) if image.get("url") else None

    offers = product_json.get("offers")
    if isinstance(offers, dict):
        offers = [offers]
    if isinstance(offers, list) and offers:
        offer = offers[0]
        if offer.get("price") is not None:
            data["price"] = _safe_decimal(offer.get("price"))
        if offer.get("priceCurrency"):
            data["currency"] = str(offer.get("priceCurrency")).upper()
        if offer.get("availability"):
            data["inventory_status"] = str(offer.get("availability")).lower()
        if offer.get("priceValidUntil"):
            data["effective_date"] = offer.get("priceValidUntil")

    return data


def extract_from_metadata(soup: BeautifulSoup, base_url: Optional[str] = None) -> dict:
    """Extract product fields from HTML metadata (Open Graph, meta tags)."""
    data: dict = {}
    og = extract_open_graph(soup)
    if og.get("og:title"):
        data["product_name"] = _clean_text(og["og:title"])
    if og.get("og:description"):
        data["description"] = _clean_text(og["og:description"])
    if og.get("og:image"):
        data["image_urls"] = _resolve_urls([og["og:image"]], base_url)
    if og.get("og:url"):
        data["product_url"] = _resolve_url(og["og:url"], base_url)
    canonical = extract_canonical_url(soup)
    if canonical:
        data["product_url"] = _resolve_url(canonical, base_url)
    if not data.get("description"):
        desc = extract_meta_description(soup)
        if desc:
            data["description"] = desc
    return data


def extract_visible_content(
    soup: BeautifulSoup,
    base_url: Optional[str] = None,
    selectors: Optional[Dict[str, List[str]]] = None,
) -> dict:
    """Extract product fields from visible HTML content using configurable selectors.

    No single HTML structure is assumed for every website; selectors are
    configurable and GRANIT-specific selectors are not hardcoded without
    inspecting an approved sample page.
    """
    selectors = selectors or {}
    data: dict = {}

    data["product_name"] = _first_text(
        soup, selectors.get("title", ["h1", "h2.product-title"])
    )
    data["description"] = _first_text(
        soup, selectors.get("description", ["div.product-description", "section.product-description"])
    )
    data["brand"] = _first_text(
        soup, selectors.get("brand", ["span.brand", "div.brand"])
    )
    data["manufacturer"] = _first_text(
        soup, selectors.get("manufacturer", ["span.manufacturer", "div.manufacturer"])
    )
    data["article_number"] = _first_text(
        soup, selectors.get("article_number", ["span.article-number", "div.sku", "span[itemprop='sku']"])
    )
    data["category"] = _first_text(
        soup, selectors.get("category", ["div.category", "a.category", "span[itemprop='category']"])
    )

    # Images
    image_urls: List[str] = []
    for selector in selectors.get(
        "image_urls", ["img.product-image", "img[data-src]", "img[data-lazy-src]"]
    ):
        try:
            imgs = soup.select(selector)
        except Exception:
            continue
        for img in imgs:
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
            if src:
                image_urls.append(src)
    if image_urls:
        data["image_urls"] = _resolve_urls(image_urls, base_url)

    # Technical specifications from specification tables / definition lists.
    specs: Dict[str, Any] = {}
    for table in soup.select(
        "table.product-specs, table.specs, table.technical-specifications, table[class*='spec']"
    ):
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all(["th", "td"])
            if len(cells) >= 2:
                key = _clean_text(cells[0].get_text(" ", strip=True))
                val = _clean_text(cells[1].get_text(" ", strip=True))
                if key and val:
                    specs[key] = val
    if specs:
        data["technical_specifications"] = specs

    return data


def extract_regional_data(prices: Optional[List[dict]]) -> Optional[List[dict]]:
    """Extract regional pricing entries when verified values are available.

    Does not calculate or invent missing commercial values. Only entries
    with both a country code and currency are returned.
    """
    if not prices:
        return None
    entries: List[dict] = []
    for entry in prices:
        country_code = entry.get("country_code")
        currency = entry.get("currency")
        if not country_code or not currency:
            continue
        regional_entry: dict = {
            "country": entry.get("country"),
            "country_code": str(country_code).upper(),
            "currency": str(currency).upper(),
        }
        for field in ("net_price", "vat_rate", "gross_price"):
            if entry.get(field) is not None:
                regional_entry[field] = _safe_decimal(entry.get(field))
        if entry.get("price_source"):
            regional_entry["price_source"] = entry.get("price_source")
        if entry.get("effective_date"):
            regional_entry["effective_date"] = entry.get("effective_date")
        entries.append(regional_entry)
    return entries or None


def build_product(
    extracted: dict,
    source_id: str,
    source_url: str,
    data_origin: str = "approved_public_source",
) -> Product:
    """Build a Pydantic Product from extracted fields with provenance.

    Raises:
        ExtractionError: when mandatory identifiers (article_number or
            product_name) are missing.
    """
    article_number = extracted.get("article_number") or extracted.get("sku")
    product_name = extracted.get("product_name")
    if not article_number or not product_name:
        raise ExtractionError(
            "Missing mandatory product identifiers (article_number or product_name)"
        )

    now = datetime.now(timezone.utc)
    product_data: dict = {
        "article_number": article_number,
        "product_name": product_name,
        "data_origin": data_origin,
        "source_id": source_id,
        "source_url": source_url,
        "collected_at": now,
        "verification_status": "not_verified",
        "is_synthetic": False,
        "last_updated_at": now,
    }

    optional_fields = [
        "sku", "ean_gtin", "description", "short_description", "product_type",
        "product_url", "image_urls", "manufacturer", "brand", "supplier",
        "category", "subcategory", "dimensions", "weight", "material",
        "technical_specifications", "compatibility", "ce_marking_status",
        "applicable_regulations", "compliance_certificates", "country_of_origin",
        "inventory_status", "inventory_quantity", "warehouse", "shipping_method",
        "delivery_days", "regional_data",
    ]
    for field in optional_fields:
        if extracted.get(field) is not None:
            product_data[field] = extracted[field]
    if extracted.get("price") is not None:
        product_data["price"] = extracted["price"]
    if extracted.get("currency"):
        product_data["currency"] = extracted["currency"]

    return Product(**product_data)
