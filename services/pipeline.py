"""Pipeline integration for Phase 4: Data Cleaning & Validation.

Defines the end-to-end pipeline that takes extracted product candidates
through cleaning, schema validation, business validation, duplicate detection,
and quality reporting.

The pipeline does NOT persist to MongoDB (that's Phase 5).  Rejected records
are retained with error details returned alongside valid records.
"""

from typing import Any, Dict, List, Optional, Tuple

from decimal import Decimal

from services.cleaner import clean_product_dict
from services.validator import (
    validate_ean_gtin,
    validate_country_code,
    validate_currency_code,
    validate_provenance,
    validate_regional_price,
    validate_url,
    validate_required_fields,
    identify_inconsistencies,
)
from services.deduplicator import detect_duplicates, DuplicateGroup, should_merge_records
from services.quality_report import compute_dataset_quality_summary, compute_record_quality_score

# Allowed data_origin values (from models.product.py)
DATA_ORIGINS = {"approved_public_source", "authorized_api", "manual_entry", "synthetic"}

# Allowed verification_status values (from models.product.py)
VERIFICATION_STATUSES = {"verified", "partially_verified", "not_verified", "pending"}


class ValidationError(Exception):
    """Raised when a product fails schema or business validation."""
    def __init__(self, message: str, product: Optional[Dict[str, Any]] = None) -> None:
        self.message = message
        self.product = product
        super().__init__(message)


class PipelineResult:
    """Container for pipeline output.

    Attributes:
        valid_products: List of product dicts that passed all validation stages.
        rejected_products: List of dicts with {"product": raw_product, "errors": [msg, ...]}.
        quality_summary: Dataset-level quality summary (from quality_report).
        duplicate_groups: List of DuplicateGroup instances from deduplicator.
    """

    def __init__(
        self,
        valid_products: List[Dict[str, Any]],
        rejected_products: List[Dict[str, Any]],
        quality_summary: Dict[str, Any],
        duplicate_groups: List[DuplicateGroup],
    ) -> None:
        self.valid_products = valid_products
        self.rejected_products = rejected_products
        self.quality_summary = quality_summary
        self.duplicate_groups = duplicate_groups


def _validate_product_schema(product: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Run schema-level validation (required fields, provenance, URL, EAN/GTIN).

    Returns (is_valid, list_of_error_messages).
    """
    errors: List[str] = []

    # Required field check
    is_valid, missing = validate_required_fields(product)
    if not is_valid:
        errors.append(f"Missing mandatory fields: {', '.join(missing)}")

    # Provenance validation
    provenance_ok, provenance_msg = validate_provenance(product)
    if not provenance_ok:
        errors.append(provenance_msg or "Provenance validation failed")

    # URL validation on source_url and product_url
    for url_field in ("source_url", "product_url"):
        url_val = product.get(url_field)
        if url_val is not None:
            url_ok, url_msg = validate_url(str(url_val))
            if not url_ok:
                errors.append(f"{url_field}: {url_msg}")

    # EAN/GTIN check-digit validation
    ean = product.get("ean_gtin")
    if ean is not None:
        is_valid, gtin_type = validate_ean_gtin(str(ean))
        if not is_valid:
            errors.append(f"ean_gtin: invalid check digit (not {gtin_type})")

    return len(errors) == 0, errors


def _validate_product_business(product: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Run business-logic validation (regional pricing, country/currency,
    gross price consistency, VAT ranges)."""

    errors: List[str] = []

    # Regional data validation
    regional_data = product.get("regional_data")
    if regional_data is not None and isinstance(regional_data, list):
        for i, entry in enumerate(regional_data):
            if not isinstance(entry, dict):
                errors.append(f"regional_data[{i}]: not a dict")
                continue

            price = entry.get("price")
            vat_rate = entry.get("vat_rate")
            gross_price = entry.get("gross_price")
            country_code = entry.get("country_code")
            currency = entry.get("currency")

            # Country code validation
            if country_code is not None:
                if not validate_country_str(country_code):
                    errors.append(f"regional_data[{i}].country_code: invalid ISO country code '{country_code}'")

            # Currency code validation
            if currency is not None:
                if not validate_currency_str(currency):
                    errors.append(f"regional_data[{i}].currency: invalid ISO currency code '{currency}'")

            # Regional price consistency
            if price is not None or vat_rate is not None or gross_price is not None:
                price_dec = Decimal(str(price)) if price is not None else None
                vat_dec = Decimal(str(vat_rate)) if vat_rate is not None else None
                gross_dec = Decimal(str(gross_price)) if gross_price is not None else None

                consistency_msg = validate_regional_price(
                    price_dec, vat_dec, gross_dec, currency, country_code
                )
                if consistency_msg:
                    errors.append(f"regional_data[{i}]: {consistency_msg}")

    # Top-level price/currency consistency with regional data
    top_price = product.get("price")
    top_currency = product.get("currency")
    # Note: we preserve both top-level and regional prices without overwriting;
    # inconsistencies are flagged but not resolved here.

    # Identify additional inconsistencies
    inconsistencies = identify_inconsistencies(product)
    for inc in inconsistencies:
        errors.append(f"inconsistency: {inc['field']} - {inc['issue']}")

    return len(errors) == 0, errors


def validate_country_str(country_code: str) -> bool:
    """Helper to validate a country code string using the validator module."""
    from services.validator import validate_country_code
    return validate_country_code(country_code)


def validate_currency_str(currency_code: str) -> bool:
    """Helper to validate a currency code string using the validator module."""
    from services.validator import validate_currency_code
    return validate_currency_code(currency_code)


def run_pipeline(
    raw_products: List[Dict[str, Any]],
    *,
    detect_duplicates_flag: bool = True,
) -> PipelineResult:
    """Run the full Phase 4 pipeline on a list of raw product dicts.

    Pipeline stages (in order):
    1. **Cleaning**         - text normalization, empty→null, currency/date/dim normalization, URL cleaning.
       Provenance fields (data_origin, source_id, source_url, collected_at,
       verification_status, is_synthetic) are preserved as-is.
    2. **Schema Validation** - required fields, provenance, URL format, EAN/GTIN check digits.
    3. **Business Validation** - regional pricing, country/currency codes, VAT ranges,
       gross price consistency, inconsistency identification.
    4. **Duplicate Detection** - article_number, EAN/GTIN, canonical URL duplicates.
    5. **Quality Report** - field completeness scores, valid/invalid counts, missing fields,
       duplicate group summaries, overall quality percentage.

    Rejected records are retained with detailed error messages; valid records
    are returned cleaned and validated.  No MongoDB persistence occurs.

    Args:
        raw_products: List of raw product dicts (typically from extraction, before cleaning).
        detect_duplicates_flag: When True (default), run duplicate detection.

    Returns:
        A ``PipelineResult`` containing valid products, rejected products with errors,
        a dataset quality summary, and any duplicate groups found.
    """
    if not raw_products:
        from services.quality_report import compute_dataset_quality_summary
        quality_summary = compute_dataset_quality_summary([])
        return PipelineResult(
            valid_products=[],
            rejected_products=[],
            quality_summary=quality_summary,
            duplicate_groups=[],
        )

    # Stage 1: Cleaning
    cleaned_products: List[Dict[str, Any]] = []
    for raw in raw_products:
        cleaned = clean_product_dict(raw)
        # Preserve provenance from raw; clean_product_dict already keeps them
        cleaned_products.append(cleaned)

    # Stage 2: Schema Validation
    validated_products: List[Dict[str, Any]] = []
    rejected_with_errors: List[Dict[str, Any]] = []

    for product in cleaned_products:
        schema_ok, schema_errors = _validate_product_schema(product)
        if schema_ok:
            validated_products.append(product)
        else:
            rejected_with_errors.append({
                "product": product,
                "errors": schema_errors,
                "stage": "schema_validation",
            })

    # Stage 3: Business Validation
    business_valid: List[Dict[str, Any]] = []
    business_rejected: List[Dict[str, Any]] = []

    for product in validated_products:
        business_ok, business_errors = _validate_product_business(product)
        if business_ok:
            business_valid.append(product)
        else:
            business_rejected.append({
                "product": product,
                "errors": business_errors,
                "stage": "business_validation",
            })

    # Stage 4: Duplicate Detection
    if detect_duplicates_flag:
        dup_groups = detect_duplicates(business_valid)
    else:
        dup_groups = []

    # Stage 5: Quality Report
    quality_summary = compute_dataset_quality_summary(business_valid)

    # Combine: rejected products include both schema and business validation rejections
    all_rejected = rejected_with_errors + business_rejected

    return PipelineResult(
        valid_products=business_valid,
        rejected_products=all_rejected,
        quality_summary=quality_summary,
        duplicate_groups=dup_groups,
    )