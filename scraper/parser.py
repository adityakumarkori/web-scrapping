"""HTML parsing utilities for the GRANIT EU scraper.

Uses BeautifulSoup to parse HTML, extract JSON-LD structured data,
Open Graph metadata, and canonical URLs.
"""

import json
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from core.logging import get_logger
from scraper.exceptions import ParsingError

logger = get_logger(__name__)


def parse_html(html: str) -> BeautifulSoup:
    """Parse HTML into a BeautifulSoup object."""
    try:
        return BeautifulSoup(html, "html.parser")
    except Exception as exc:  # noqa: BLE001
        raise ParsingError(f"Failed to parse HTML: {exc}") from exc


def extract_json_ld(soup: BeautifulSoup) -> List[dict]:
    """Extract all JSON-LD script blocks from a page.

    Invalid JSON-LD blocks are skipped with a warning rather than failing
    the whole page.
    """
    results: List[dict] = []
    for script in soup.find_all("script", type="application/ld+json"):
        raw = script.string or script.get_text() or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Invalid JSON-LD block skipped")
            continue
        if isinstance(data, list):
            results.extend(data)
        elif isinstance(data, dict):
            results.append(data)
    return results


def find_product_json_ld(json_ld: List[dict]) -> List[dict]:
    """Filter JSON-LD objects that are schema.org Product entries.

    Handles Product objects, Product arrays and @graph structures.
    """
    products: List[dict] = []

    def _is_product(obj: Any) -> bool:
        if not isinstance(obj, dict):
            return False
        types = obj.get("@type")
        type_list = [types] if isinstance(types, str) else (types or [])
        return "Product" in type_list

    for obj in json_ld:
        if _is_product(obj):
            products.append(obj)
        graph = obj.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                if _is_product(item):
                    products.append(item)
    return products


def extract_open_graph(soup: BeautifulSoup) -> Dict[str, str]:
    """Extract Open Graph metadata from a page."""
    data: Dict[str, str] = {}
    for prop in ("og:title", "og:description", "og:image", "og:url", "og:site_name"):
        tag = soup.find("meta", attrs={"property": prop})
        if tag and tag.get("content"):
            data[prop] = tag["content"]
    return data


def extract_canonical_url(soup: BeautifulSoup) -> Optional[str]:
    """Extract the canonical URL from a page."""
    tag = soup.find("link", attrs={"rel": "canonical"})
    if tag and tag.get("href"):
        return tag["href"]
    return None


def extract_meta_description(soup: BeautifulSoup) -> Optional[str]:
    """Extract the standard meta description from a page."""
    tag = soup.find("meta", attrs={"name": "description"})
    if tag and tag.get("content"):
        return tag["content"]
    return None
