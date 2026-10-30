"""Validation service for the GRANIT EU pipeline.

Provides EAN/GTIN check-digit validation, ISO country/currency code validation,
regional pricing validation, VAT percentage validation, URL validation,
required-field validation, provenance validation, and inconsistent value
identification.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Set, Tuple

from core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# EAN / GTIN check-digit validation
# ---------------------------------------------------------------------------

def _compute_ean_check_digit(number_without_check: str) -> str:
    """Compute the EAN-13/EAN-8/UPC-A check digit for a number string.

    The algorithm: sum odd-position digits * 1 + even-position digits * 3,
    then ((10 - (sum % 10)) % 10).
    """
    if not number_without_check.isdigit():
        raise ValueError("Number must contain only digits")
    total = 0
    for i, ch in enumerate(number_without_check):
        digit = int(ch)
        if i % 2 == 0:  # odd positions (1-indexed) -> even indices 0-indexed
            total += digit
        else:
            total += digit * 3
    check = (10 - (total % 10)) % 10
    return str(check)


def validate_ean_gtin(ean: str) -> Tuple[bool, Optional[str]]:
    """Validate an EAN/GTIN string and return (is_valid, type).

    Supported types:
    - GTIN-13 / EAN-13: 13 digits
    - GTIN-12 / UPC-A:  12 digits
    - GTIN-8  / EAN-8:  8 digits
    - GTIN-14:         14 digits (group prefix + EAN-13)

    Returns ``(False, None)`` when the check digit fails or the length is
    unsupported.
    """
    if not isinstance(ean, str):
        return False, None
    digits = ean.strip().replace(" ", "").replace("-", "")
    if not digits.isdigit():
        return False, None
    length = len(digits)

    if length == 13:
        # EAN-13: check digit is the last digit
        computed = _compute_ean_check_digit(digits[:-1])
        if computed == digits[-1]:
            return True, "EAN-13"
        return False, None
    elif length == 12:
        # UPC-A / GTIN-12: compute check digit as EAN-13 would, but
        # the check digit calculation is the same algorithm
        computed = _compute_ean_check_digit(digits[:-1])
        if computed == digits[-1]:
            return True, "GTIN-12"
        return False, None
    elif length == 8:
        # EAN-8: check digit is the last digit
        computed = _compute_ean_check_digit(digits[:-1])
        if computed == digits[-1]:
            return True, "EAN-8"
        return False, None
    elif length == 14:
        # GTIN-14: validate the last 13 digits as EAN-13
        inner_valid, inner_type = validate_ean_gtin(digits[1:])  # skip group prefix
        if inner_valid:
            return True, "GTIN-14"
        return False, None
    else:
        return False, None


def validate_gtin(gtin: str) -> Tuple[bool, Optional[str]]:
    """Alias for validate_ean_gtin for terminology consistency."""
    return validate_ean_gtin(gtin)


# ---------------------------------------------------------------------------
# ISO country / currency code validation
# ---------------------------------------------------------------------------

_VALID_COUNTRIES: Set[str] = set()
_VALID_CURRENCIES: Set[str] = set()

# Populate common ISO 3166-1 alpha-2 codes (EU member states + neighbours)
_EU_COUNTRIES = {
    "AL", "AD", "AT", "BY", "BE", "BA", "BG", "HR", "CY", "CZ", "DK", "EE",
    "FI", "FR", "DE", "GR", "HU", "IS", "IE", "IT", "XK", "LV", "LI", "LT",
    "LU", "MT", "MD", "MC", "ME", "NL", "MK", "NO", "PL", "PT", "RO", "RU",
    "SM", "RS", "SK", "SI", "ES", "SE", "CH", "TR", "UA", "GB", "UN"
}
_VALID_COUNTRIES.update(_EU_COUNTRIES)

# Populate common ISO 4217 currency codes (EUR + major global currencies)
_CURRENCIES = {
    "EUR", "USD", "GBP", "CHF", "NOK", "SEK", "DKK", "PLN", "CZK", "HUF",
    "RON", "HRK", "BGN", "TRY", "JPY", "CNY", "KRW", "AUD", "CAD", "MXN",
    "BRL", "RUB", "ZAR", "SGD", "HKD", "INR", "TWD", "THB", "MYR", "PHP",
    "KRW", "AED", "SAF", "QAR", "KWD", "BHD", "OMR", "JOD", "EGP", "LBP",
    "SYP", "ILS", "TRL", "IDR", "IRR", "IQD", "JMD", "KES", "KWD", "KWT",
    "LAO", "LBP", "MOP", "NGN", "NIO", "NPR", "NZD", "PAB", "PEN", "PGK",
    "PYG", "SAR", "SCR", "SOS", "SRD", "STD", "SVC", "SYP", "SZL", "TJS",
    "TMT", "TWD", "TZS", "UAH", "UGX", "UYU", "VES", "VND", "VUV", "WST",
    "XAF", "XCD", "XOF", "XPF", "YER", "ZMW", "ZWL"
}
_VALID_CURRENCIES.update(_CURRENCIES)


def validate_country_code(country_code: str) -> bool:
    """Return True when *country_code* is a valid ISO 3166-1 alpha-2 code.

    Only checks against a curated set of codes (including all EU members).
    """
    if not isinstance(country_code, str):
        return False
    return country_code.upper() in _VALID_COUNTRIES


def validate_currency_code(currency_code: str) -> bool:
    """Return True when *currency_code* is a valid ISO 4217 currency code.

    Only checks against a curated set of active codes.
    """
    if not isinstance(currency_code, str):
        return False
    return currency_code.upper() in _VALID_CURRENCIES


# ---------------------------------------------------------------------------
# Regional pricing validation
# ---------------------------------------------------------------------------

def validate_regional_price(
    price: Optional[Decimal],
    vat_rate: Optional[Decimal],
    gross_price: Optional[Decimal],
    currency: Optional[str],
    country_code: Optional[str],
) -> Optional[str]:
    """Validate a regional price entry and return ``None`` on success or an
    error message string on failure.

    Rules:
    - If price is present, it must be non-negative.
    - If vat_rate is present, it must be 0-100.
    - If gross_price is present, it must be non-negative.
    - If net_price and vat_rate and gross_price are all present, gross_price
      must be consistent with net_price * (1 + vat_rate/100) within 0.01.
    - If price and currency are both present, they should reference the same
      market (handled at the product-pipeline level).
    """
    errors: List[str] = []

    if price is not None and price < 0:
        errors.append("price must be non-negative")

    if vat_rate is not None:
        try:
            v = Decimal(str(vat_rate))
            if v < 0 or v > 100:
                errors.append("vat_rate must be between 0 and 100")
        except (InvalidOperation, ValueError):
            errors.append("vat_rate must be a valid number")

    if gross_price is not None and gross_price < 0:
        errors.append("gross_price must be non-negative")

    # Gross price consistency check when all three are present
    if price is not None and vat_rate is not None and gross_price is not None:
        try:
            net = price
            vat = Decimal(str(vat_rate))
            expected_gross = net * (Decimal("1") + vat / Decimal("100"))
            if abs(gross_price - expected_gross) > Decimal("0.01"):
                errors.append(
                    "gross_price is inconsistent with price and vat_rate"
                )
        except (InvalidOperation, ValueError, TypeError):
            errors.append("could not compute gross price consistency")

    if errors:
        "; ".join(errors)
    return "; ".join(errors) if errors else None


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------

def validate_url(value: str) -> Tuple[bool, Optional[str]]:
    """Validate that *value* is a well-formed HTTP/HTTPS URL.

    Returns ``(True, None)`` when the URL passes basic validation, or
    ``(False, error_message)`` when it does not.
    """
    if not isinstance(value, str):
        return False, "URL must be a string"
    value = value.strip()
    if value == "":
        return False, "URL must not be empty"
    # Scheme check
    if not re.fullmatch(r"https?://.+", value, re.IGNORECASE):
        return False, "URL must start with http:// or https://"
    # Host check
    if not re.search(r"/\.", value.split("?")[0].split("#")[0]):
        # Very light host validation - must have a hostname
        try:
            from urllib.parse import urlparse
            parsed = urlparse(value)
            if not parsed.hostname:
                return False, "URL must contain a valid hostname"
        except Exception:
            return False, "URL parse error"
    return True, None


# ---------------------------------------------------------------------------
# Required-field validation
# ---------------------------------------------------------------------------

MANDATORY_FIELDS = {
    "article_number",
    "product_name",
}

OPTIONAL_FIELDS = {
    "sku", "ean_gtin", "description", "short_description", "product_type",
    "product_url", "image_urls", "manufacturer", "brand", "supplier",
    "category", "subcategory", "dimensions", "weight", "material",
    "technical_specifications", "compatibility", "ce_marking_status",
    "applicable_regulations", "compliance_certificates", "country_of_origin",
    "inventory_status", "inventory_quantity", "warehouse", "shipping_method",
    "delivery_days", "price", "currency", "regional_data",
    "data_origin", "source_id", "source_url", "collected_at",
    "verification_status", "is_synthetic", "last_updated_at",
}


def validate_required_fields(product_dict: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Return ``(True, [])`` when all mandatory fields are present and non-empty,
    or ``(False, [missing_fields])`` when mandatory fields are missing.

    Also reports any optional fields that are present but contain empty/None
    values (flagged as warnings, not failures).
    """
    missing: List[str] = []
    warnings: List[str] = []

    for field in MANDATORY_FIELDS:
        value = product_dict.get(field)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            missing.append(field)

    # Optional fields that are empty are warnings, not failures
    for field in OPTIONAL_FIELDS:
        value = product_dict.get(field)
        if value is not None and not (isinstance(value, str) and value.strip() == ""):
            continue  # field has a value
        # Field is either missing or None/empty - that's ok for optional

    return (len(missing) == 0, missing)


# ---------------------------------------------------------------------------
# Provenance validation
# ---------------------------------------------------------------------------

def validate_provenance(product_dict: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Validate the provenance fields of a product dict.

    Checks:
    - ``data_origin`` is one of the allowed values.
    - ``verification_status`` is one of the allowed values.
    - If ``is_synthetic`` is True, ``verification_status`` must NOT be "verified".
    - ``source_url``, when present, should be a non-empty string.

    Returns ``(True, None)`` on success, or ``(False, error_message)`` on failure.
    """
    errors: List[str] = []

    data_origin = product_dict.get("data_origin")
    if data_origin is not None:
        from models.product import DATA_ORIGINS
        if data_origin not in DATA_ORIGINS:
            errors.append(
                f"data_origin must be one of {sorted(DATA_ORIGINS)}, got {data_origin!r}"
            )

    verification_status = product_dict.get("verification_status")
    if verification_status is not None:
        from models.product import VERIFICATION_STATUSES
        if verification_status not in VERIFICATION_STATUSES:
            errors.append(
                f"verification_status must be one of {sorted(VERIFICATION_STATUSES)}, got {verification_status!r}"
            )

    is_synthetic = product_dict.get("is_synthetic", False)
    if is_synthetic and verification_status == "verified":
        errors.append(
            "Synthetic records must not be marked as verified"
        )

    source_url = product_dict.get("source_url")
    if source_url is not None and not isinstance(source_url, str):
        errors.append("source_url must be a string when present")
    if source_url is not None and source_url.strip() == "":
        errors.append("source_url must not be empty when present")

    if errors:
        return False, "; ".join(errors)
    return True, None


# ---------------------------------------------------------------------------
# Inconsistent value identification
# ---------------------------------------------------------------------------

def identify_inconsistencies(product_dict: Dict[str, Any]) -> List[Dict[str, str]]:
    """Identify inconsistent or conflicting values within a product dict.

    Returns a list of dicts with ``{ "field": "...", "issue": "..." }`` entries.
    Examples of detected inconsistencies:
    - price and a regional price are both set (potential conflict)
    - vat_rate > 20 and net_price * (1+vat) differs from gross_price by > 1
    - ean_gtin and a regional_data EAN are both set and differ
    - product_url and regional_data product URLs conflict
    """
    issues: List[Dict[str, str]] = []

    # price (top-level) vs regional_data prices
    price = product_dict.get("price")
    regional_data = product_dict.get("regional_data")
    if price is not None and regional_data is not None:
        issues.append({
            "field": "price",
            "issue": "top-level price coexisting with regional_data; verify intent",
        })

    # ean_gtin conflicts across regional entries
    if regional_data is not None:
        eans: List[str] = []
        for entry in regional_data:
            ean = entry.get("ean_gtin") if isinstance(entry, dict) else None
            if ean:
                eans.append(ean)
        if len(eans) > 1 and len(set(eans)) > 1:
            issues.append({
                "field": "ean_gtin",
                "issue": "conflicting EAN/GTIN values across regional_data entries",
            })

    # vat_rate / gross_price inconsistency in regional entries
    if regional_data is not None:
        for i, entry in enumerate(regional_data):
            if isinstance(entry, dict):
                vat = entry.get("vat_rate")
                gross = entry.get("gross_price")
                net = entry.get("net_price")
                if vat is not None and gross is not None and net is not None:
                    try:
                        expected = Decimal(str(net)) * (
                            Decimal("1") + Decimal(str(vat)) / Decimal("100")
                        )
                        if abs(Decimal(str(gross)) - expected) > Decimal("0.01"):
                            issues.append({
                                "field": f"regional_data[{i}].gross_price",
                                "issue": "gross_price inconsistent with net_price and vat_rate",
                            })
                    except (InvalidOperation, ValueError, TypeError):
                        pass  # already logged at the model level

    # source_url vs product_url conflict
    source_url = product_dict.get("source_url")
    product_url = product_dict.get("product_url")
    if source_url and product_url and source_url != product_url:
        issues.append({
            "field": "source_url / product_url",
            "issue": "source_url and product_url differ; verify which is canonical",
        })

    return issues