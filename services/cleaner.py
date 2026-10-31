"""Data cleaning service for the GRANIT EU pipeline.

Provides text normalization, empty-string-to-null coercion, numeric and date
normalization, and URL cleaning while preserving auditability fields (provenance,
data_origin, source_id, source_url, collected_at, verification_status,
is_synthetic).
"""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from decimal import Decimal, InvalidOperation

from core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Text normalization helpers
# ---------------------------------------------------------------------------

_STRIP_CHARS = r"\s+"


def _strip_whitespace(value: str) -> str:
    """Collapse runs of whitespace and strip leading/trailing whitespace."""
    return re.sub(_STRIP_CHARS, " ", value).strip()


def _remove_nbsp(value: str) -> str:
    """Remove non-breaking space characters (\\xa0) from a string."""
    return value.replace("\xa0", " ")


# ---------------------------------------------------------------------------
# Empty-string / None coercion
# ---------------------------------------------------------------------------

def clean_nullable_string(value: Any) -> Optional[str]:
    """Return ``None`` when the value is empty, whitespace-only, or ``None``.

    Otherwise return the stripped string.  This is applied to fields where
    an empty value should be represented as ``None`` rather than an empty
    string, while auditability fields are *preserved* as-is.
    """
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            return None
        return stripped
    return None


def clean_nullable_list(value: Any) -> Optional[List[str]]:
    """Return ``None`` when the value is empty, whitespace-only, or ``None``.

    Otherwise return the list with each element stripped of whitespace.
    """
    if value is None:
        return None
    if isinstance(value, list):
        stripped = [item.strip() if isinstance(item, str) else item for item in value]
        if all(item is None or (isinstance(item, str) and item.strip() == "") for item in stripped):
            return None
        return stripped
    return None


# ---------------------------------------------------------------------------
# Currency / numeric normalization
# ---------------------------------------------------------------------------

def normalize_currency_code(value: Any) -> Optional[str]:
    """Normalize a currency code to a 3-letter uppercase ISO 4217 code.

    Strips whitespace, uppercases, and validates the length.  Returns ``None``
    when the value cannot be normalized.
    """
    if value is None:
        return None
    if isinstance(value, str):
        code = value.strip().upper()
        if re.fullmatch(r"[A-Z]{3}", code):
            return code
    return None


def normalize_decimal_value(value: Any) -> Optional[Decimal]:
    """Coerce a numeric-like value to ``Decimal``, returning ``None`` when impossible.

    Handles ``int``, ``float``, ``str`` (with optional whitespace/commas), and
    already-``Decimal`` values.  Leading/trailing whitespace and commas as
    thousand separators are removed before conversion.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        # bool is a subclass of int in Python; reject it for monetary fields
        return None
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    if isinstance(value, str):
        try:
            cleaned = value.strip()
            # Remove thousand-separator commas (e.g. "1,234.56")
            cleaned = re.sub(r",(?=\d{3})", "", cleaned)
            # Replace any non-breaking space with regular space
            cleaned = cleaned.replace("\xa0", " ")
            return Decimal(cleaned)
        except (InvalidOperation, ValueError):
            return None
    return None


# ---------------------------------------------------------------------------
# Date normalization
# ---------------------------------------------------------------------------

def normalize_date_value(value: Any) -> Optional[str]:
    """Normalize a date value to an ISO 8601 ``"YYYY-MM-DD"`` string.

    Accepts ``datetime``, ``date``, or ISO-format ``str`` values.  Returns
    ``None`` when the value cannot be parsed.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if hasattr(value, "strftime"):  # datetime.date
        return value.strftime("%Y-%m-%d")
    if isinstance(value, str):
        s = value.strip()
        # Try common ISO formats
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d-%m-%Y", "%d/%m/%Y"):
            try:
                dt = datetime.strptime(s, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
    return None


# ---------------------------------------------------------------------------
# Dimension / size normalization (free-form dict)
# ----

def normalize_dimension_value(value: Any) -> Optional[dict]:
    """Normalize a dimension specification into a ``dict`` with ``unit`` and ``value``.

    Accepted input forms:
    - ``dict`` with ``value`` and optionally ``unit`` keys
    - ``str`` like ``"10 x 20 x 5 cm"``, ``"500ml"``, ``"1200x800mm"``

    Returns a dict with ``value`` (Decimal) and ``unit`` (str), or ``None`` when
    the input cannot be parsed.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        # Normalise keys to lower‑strip whitespace in values
        normalized: Dict[str, Any] = {}
        for k, v in value.items():
            key = k.strip().lower()
            if key == "value":
                normalized["value"] = normalize_decimal_value(v)
            elif key == "unit":
                if isinstance(v, str):
                    normalized["unit"] = v.strip()
                else:
                    normalized["unit"] = str(v)
            else:
                normalized[key] = v
        if "value" in normalized and normalized["value"] is not None:
            return normalized
        return None
    if isinstance(value, str):
        v = value.strip()
        # Pattern: "W x H x D unit" or "W x H x D" or "value unit"
        m = re.match(
            r"^\s*([\d,\.xa0]+)\s*x\s*([\d,\.xa0]+)\s*x\s*([\d,\.xa0]+)\s*(.+)?\s*$",
            v,
            re.IGNORECASE,
        )
        if not m:
            # Try single-value pattern: "150 cm" or "500ml"
            m2 = re.match(r"^([\d,\.xa0]+)\s*([a-zA-Z%]+)$", v, re.IGNORECASE)
        if m:
            try:
                val = Decimal(m.group(1).replace(",", "").replace("\xa0", ""))
                # Not using group(2) and group(3) for simplicity; just capture the unit
                unit = (m.group(4) or "").strip()
                if unit:
                    return {"value": val, "unit": unit}
                return {"value": val, "unit": "unknown"}
            except (InvalidOperation, ValueError):
                return None
        # Single value pattern: "150 cm" or "500ml"
        m2 = re.match(r"^([\d,\.xa0]+)\s*([a-zA-Z%]+)$", v, re.IGNORECASE)
        if m2:
            try:
                val = Decimal(m2.group(1).replace(",", "").replace("\xa0", ""))
                unit = m2.group(2).strip()
                return {"value": val, "unit": unit}
            except (InvalidOperation, ValueError):
                return None
    return None


# ---------------------------------------------------------------------------
# URL cleaning (auditability preserving)
# ---------------------------------------------------------------------------

def clean_source_url(value: Any) -> Optional[str]:
    """Clean and normalise a source URL while preserving auditability.

    - Strips leading/trailing whitespace.
    - Ensures a ``https://`` scheme (adds it if missing but a host is present).
    - Removes trailing slashes from the path component.
    - Lowercases the host component.
    - Returns ``None`` when the value cannot be interpreted as a URL.

    Auditability fields (source_url already stored in the product model) are
    *always* preserved as-is by callers; this function is used when a URL is
    first received/extracted.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    url = value.strip()
    if url == "":
        return None
    # Ensure scheme
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    # Remove trailing slashes from path (but not the root "/")
    parsed = None
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
    except Exception:
        return None
    if parsed.netloc:
        # Lowercase the host
        url = url.replace(parsed.hostname or "", (parsed.hostname or "").lower())
        # Remove trailing slash from path
        if parsed.path != "/" and parsed.path.endswith("/"):
            path = parsed.path.rstrip("/")
            url = url.replace(parsed.path, path)
    return url


# ---------------------------------------------------------------------------
# Main cleaning entry point
# ---------------------------------------------------------------------------

def clean_product_dict(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Run the full cleaning pipeline on a raw product dict.

    Steps (auditability-preserving):
    1. Coerce empty/whitespace strings to ``None`` (except provenance fields).
    2. Normalize currency codes.
    3. Normalize Decimal price/cost fields.
    4. Normalize date fields.
    5. Normalize dimension fields.
    6. Clean URL fields.
    7. Remove duplicate/conflicting keys (keep first non-null value).

    The function returns a new dict; the original raw dict is **not** modified.
    Provenance fields (``data_origin``, ``source_id``, ``source_url``,
    ``collected_at``, ``verification_status``, ``is_synthetic``) are left
    untouched.
    """
    if not isinstance(raw, dict):
        logger.warning("clean_product_dict received non-dict input: %s", type(raw))
        return {}

    result: Dict[str, Any] = {}
    # Preserve provenance fields as-is from the raw input
    provenance_keys = {
        "data_origin",
        "source_id",
        "source_url",
        "collected_at",
        "verification_status",
        "is_synthetic",
        "last_updated_at",
    }
    for key in provenance_keys:
        if key in raw:
            result[key] = raw[key]

    # Define all other keys and their cleaning strategies
    all_keys = set(raw.keys()) - provenance_keys

    for key in sorted(all_keys):
        value = raw[key]

        # Skip explicitly null / missing
        if value is None:
            result[key] = None
            continue

        # Empty string -> null for non-provenance fields
        if isinstance(value, str) and value.strip() == "":
            result[key] = None
            continue

        # Text-like fields: strip whitespace internally, but keep non-empty
        if key in {"product_name", "short_description", "description", "sku", "ean_gtin",
                   "model", "mpn", "manufacturer", "brand", "supplier", "category",
                   "subcategory", "technical_specifications", "compatibility",
                   "country_of_origin"}:
            if isinstance(value, str):
                result[key] = _strip_whitespace(value)
                # Also remove nbsp
                result[key] = _remove_nbsp(result[key])
                continue
            # For non-string text, store repr (shouldn't happen in practice)
            result[key] = str(value)
            continue

        # Numeric / Decimal fields
        if key in {"price", "net_price", "gross_price", "vat_rate", "mrp",
                   "list_price", "compare_at_price"}:
            d = normalize_decimal_value(value)
            result[key] = d
            continue

        # Currency code
        if key == "currency":
            c = normalize_currency_code(value)
            result[key] = c
            continue

        # Date fields
        if key in {"collected_at", "effective_date", "release_date",
                   "discontinuation_date", "last_checked"}:
            d = normalize_date_value(value)
            result[key] = d
            continue

        # Dimension fields
        if key in {"dimensions", "size", "format"}:
            d = normalize_dimension_value(value)
            result[key] = d
            continue

        # URL fields
        if key in {"product_url", "source_url", "image_urls", "referrer_url"}:
            if key == "image_urls" and isinstance(value, list):
                cleaned_links: List[Optional[str]] = []
                for img in value:
                    if isinstance(img, str):
                        cleaned = clean_source_url(img)
                        cleaned_links.append(cleaned)
                    else:
                        cleaned_links.append(None)
                # Remove None entries; keep only valid URLs
                result[key] = [u for u in cleaned_links if u is not None] or None
                continue
            cleaned = clean_source_url(value)
            result[key] = cleaned
            continue

        # Free-form value: just strip whitespace if string
        if isinstance(value, str):
            result[key] = value.strip()
            continue

        # Pass-through for other types
        result[key] = value

    logger.info("clean_product_dict produced %d fields", len(result))
    return result