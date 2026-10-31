"""Pipeline integration for Phase 4: Data Cleaning & Validation.

Defines the end-to-end pipeline that takes extracted product candidates
through cleaning, schema validation, business validation, duplicate detection,
and quality reporting, with optional MongoDB persistence (Phase 5).

The pipeline does NOT persist to MongoDB by default — call
``run_pipeline_with_persistence`` when MongoDB is connected.  Rejected
records are retained with error details returned alongside valid records.
"""

from typing import Any, Dict, List, Optional, Tuple

from decimal import Decimal

from services.cleaner import clean_product_dict
from services.validator import (
    validate_ean_gtin,
    validate_country_code,
    validate_currency_code,
    validate_regional_price,
    validate_url,
    validate_required_fields,
    validate_provenance,
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
        persistence_status: "persisted", "skipped", or "unavailable".
    """

    def __init__(
        self,
        valid_products: List[Dict[str, Any]],
        rejected_products: List[Dict[str, Any]],
        quality_summary: Dict[str, Any],
        duplicate_groups: List[DuplicateGroup],
        persistence_status: str = "unavailable",
    ) -> None:
        self.valid_products = valid_products
        self.rejected_products = rejected_products
        self.quality_summary = quality_summary
        self.duplicate_groups = duplicate_groups
        self.persistence_status = persistence_status


class PersistenceError(Exception):
    """Raised when MongoDB persistence operations fail."""
    pass


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
    VAT ranges, gross price consistency, inconsistency identification).

    Returns (is_valid, list_of_error_messages).
    """
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
    are returned cleaned and validated.  No MongoDB persistence occurs by default.

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
            persistence_status="unavailable",
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
        persistence_status="unavailable",
    )


def run_pipeline_with_persistence(
    raw_products: List[Dict[str, Any]],
    *,
    detect_duplicates_flag: bool = True,
    product_repo=None,
    rejected_repo=None,
    scraping_repo=None,
) -> PipelineResult:
    """Run the full pipeline AND persist results to MongoDB.

    This is the Phase 5 integration point.  It runs the same pipeline as
    ``run_pipeline``, then persists valid records via *product_repo* and
    rejected records via *rejected_repo*, and saves scraping-run statistics
    via *scraping_repo*.

    If MongoDB is disconnected, the pipeline still runs correctly and
    returns a result with ``persistence_status = "unavailable"``; no records
    are claimed to have been saved.

    Args:
        raw_products: List of raw product dicts (typically from extraction, before cleaning).
        detect_duplicates_flag: When True (default), run duplicate detection.
        product_repo: An optional ``ProductRepository`` instance.  When ``None``
            and MongoDB is connected, one is created automatically.
        rejected_repo: An optional ``RejectedProductRepository`` instance.
        scraping_repo: An optional ``ScrapingRunRepository`` instance.

    Returns:
        A ``PipelineResult`` with ``persistence_status`` set to one of:
        - ``"persisted"`` — all eligible records were saved to MongoDB.
        - ``"partial"`` — some records were saved, some were skipped.
        - ``"unavailable"`` — MongoDB was disconnected; no persistence attempted.
    """
    # Run the standard pipeline first
    result = run_pipeline(
        raw_products,
        detect_duplicates_flag=detect_duplicates_flag,
    )

    # Determine MongoDB connection status
    mongo_connected = mongodb.is_connected()

    # Initialise repositories if not provided
    if product_repo is None and mongo_connected:
        product_repo = ProductRepository()
    if rejected_repo is None and mongo_connected:
        rejected_repo = RejectedProductRepository()
    if scraping_repo is None and mongo_connected:
        scraping_repo = ScrapingRunRepository()

    persistence_status = "unavailable"

    if not mongo_connected:
        # Pipeline ran, but persistence is unavailable
        result.persistence_status = "unavailable"
        return result

    # --- Persist valid products ---
    persisted_counts = {"inserted": 0, "skipped": 0, "failed": 0}
    for product in result.valid_products:
        try:
            # Use the product repository to insert/upsert
            # We use upsert_key = source_id + article_number
            src_id = product.get("source_id", "unknown")
            article = product.get("article_number")

            # Determine if this should be an insert or upsert
            if article:
                # Check if a product with same source_id + article_number exists
                existing = product_repo.get_by_article_number(article, source_id=src_id)
                if existing:
                    # Update existing record
                    upsert_result = product_repo.upsert_product(product)
                    persisted_counts["skipped"] += 1  # treated as update, not new insert
                else:
                    # Insert as new
                    rid = product_repo.insert_product(product)
                    if rid:
                        persisted_counts["inserted"] += 1
                    else:
                        persisted_counts["failed"] += 1
            else:
                # No article number — just insert
                rid = product_repo.insert_product(product)
                if rid:
                    persisted_counts["inserted"] += 1
                else:
                    persisted_counts["failed"] += 1
        except Exception as exc:
            logger.exception("Failed to persist product")
            persisted_counts["failed"] += 1

    # --- Persist rejected products ---
    rejected_persisted = 0
    for item in result.rejected_products:
        try:
            raw = item["product"]
            errors = item["errors"]
            rejection_reason = "; ".join(errors) if errors else "validation failed"

            rid = rejected_repo.record_rejection(
                run_id="pipeline_run",
                source_id=raw.get("source_id", "unknown"),
                source_url=raw.get("source_url", ""),
                raw_extracted=raw,
                validation_errors=errors,
                rejection_reason=rejection_reason,
                article_number=raw.get("article_number"),
            )
            if rid:
                rejected_persisted += 1
        except Exception as exc:
            logger.exception("Failed to persist rejected product")

    # --- Persist scraping run statistics ---
    scraping_summary = None
    if scraping_repo is not None:
        # Compute summary numbers from the pipeline result
        total_valid = len(result.valid_products)
        total_rejected = len(result.rejected_products)

        # Try to create a run record; use a deterministic run_id based on
        # the current timestamp if one isn't provided
        run_id = f"pipeline_{__import__('datetime').datetime.now().strftime('%Y%m%d%H%M%S')}"

        scraping_summary = scraping_repo.create_run(
            run_id=run_id,
            source_id="pipeline",
            status="completed" if total_rejected == 0 else "completed_with_rejections",
            records_found=len(raw_products),
            extracted_count=total_valid + total_rejected,
            inserted_count=persisted_counts["inserted"],
            updated_count=0,  # not tracked in this simple pipeline
            skipped_count=persisted_counts["skipped"],
            rejected_count=total_rejected,
            failed_count=persisted_counts["failed"],
            errors=[e for item in result.rejected_products for e in item["errors"][:3]],
        )

    # Set persistence status
    if persisted_counts["inserted"] > 0 or rejected_persisted > 0 or scraping_summary is not None:
        persistence_status = "persisted"
    elif persisted_counts["failed"] > 0 or rejected_persisted == 0:
        persistence_status = "partial"
    else:
        persistence_status = "unavailable"

    result.persistence_status = persistence_status

    # Add persistence metadata to the result
    result.persisted_counts = persisted_counts
    result.rejected_persisted = rejected_persisted
    result.scraping_summary = scraping_summary

    return result