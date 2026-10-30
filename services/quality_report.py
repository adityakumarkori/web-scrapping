"""Quality report service for the GRANIT EU pipeline.

Produces field completeness scores, valid/invalid record counts, missing mandatory
and optional field identification, duplicate record identification, and dataset-level
and record-level quality summaries.
"""

from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple

from core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Mandatory / optional field definitions (aligned with models/product.py)
# ---------------------------------------------------------------------------

MANDATORY_FIELDS = {
    "article_number",
    "product_name",
}

OPTIONAL_FIELDS = {
    "sku",
    "ean_gtin",
    "description",
    "short_description",
    "product_type",
    "product_url",
    "image_urls",
    "manufacturer",
    "brand",
    "supplier",
    "category",
    "subcategory",
    "dimensions",
    "weight",
    "material",
    "technical_specifications",
    "compatibility",
    "ce_marking_status",
    "applicable_regulations",
    "compliance_certificates",
    "country_of_origin",
    "inventory_status",
    "inventory_quantity",
    "warehouse",
    "shipping_method",
    "delivery_days",
    "price",
    "currency",
    "regional_data",
    "data_origin",
    "source_id",
    "source_url",
    "collected_at",
    "verification_status",
    "is_synthetic",
    "last_updated_at",
}

ALL_FIELDS = MANDATORY_FIELDS | OPTIONAL_FIELDS

# Per-record quality thresholds
COMPLETE_SCORE = 1.0  # all mandatory + present optional fields
PARTIAL_SCORE = 0.5  # mandatory fields present but many optional missing
INCOMPLETE_SCORE = 0.0  # mandatory fields missing


# ---------------------------------------------------------------------------
# Record-level validation helpers
# ---------------------------------------------------------------------------

def _get_product_fields(product: Dict[str, Any]) -> Dict[str, Any]:
    """Return a dict of {field: value} for all known fields, using .get() so
    missing keys map to None."""
    result: Dict[str, Any] = {}
    for field in ALL_FIELDS:
        result[field] = product.get(field)
    return result


def _field_is_present(value: Any) -> bool:
    """Consider a field as 'present' when it is not None and not an empty
    whitespace string."""
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    return True


def _field_is_valid(value: Any, field_name: str) -> bool:
    """Check that a field value is not only present but also valid according
    to the validator rules.  Falls back to ``_field_is_present`` for types
    we don't have specific rules for."""
    if not _field_is_present(value):
        return False
    # Additional type-specific checks could be added here
    return True


# ---------------------------------------------------------------------------
# Record quality score
# -------------------------------------------------------------------------__


def compute_record_quality_score(
    product: Dict[str, Any],
) -> Tuple[float, Dict[str, bool]]:
    """Compute a quality score in [0, 1] for a single product dict.

    Returns ``(score, present_flags)`` where:
    - *score* is:
        - 1.0 if all mandatory fields are present AND at least 75% of optional
          fields are present,
        - 0.5 if all mandatory fields are present but optional coverage is low,
        - 0.0 if any mandatory field is missing.
    - *present_flags* maps each field name to ``True``/``False`` indicating
      whether the field is present (non-None, non-empty).

    The score balances mandatory completeness with optional field coverage.
    """
    fields = _get_product_fields(product)

    # Check mandatory presence
    mandatory_present = {
        f: _field_is_present(fields[f]) for f in MANDATORY_FIELDS
    }
    mandatory_pass = all(mandatory_present.values())

    if not mandatory_pass:
        return INCOMPLETE_SCORE, mandatory_present | {
            f: False for f in OPTIONAL_FIELDS
        }

    # Count present optional fields
    optional_present = {
        f: _field_is_present(fields[f]) for f in OPTIONAL_FIELDS
    }
    optional_count = sum(1 for v in optional_present.values() if v)
    optional_total = len(OPTIONAL_FIELDS)
    optional_ratio = optional_count / optional_total if optional_total > 0 else 1.0

    # Score: 1.0 if optional coverage >= 75%, else 0.5
    if optional_ratio >= 0.75:
        score = COMPLETE_SCORE
    else:
        score = PARTIAL_SCORE

    return score, {**mandatory_present, **optional_present}


# ---------------------------------------------------------------------------
# Dataset quality summary
# -------------------------------------------------------------------------__


def compute_dataset_quality_summary(
    products: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Produce a dataset-level quality summary for a list of product dicts.

    Returns a dict with the following keys:
    - "total_records": total number of records examined
    - "valid_records": count of records with a quality score >= 0.5 (all mandatory
      present, reasonable optional coverage)
    - "invalid_records": count of records that are invalid (missing mandatory fields
      or extremely sparse optional coverage, score < 0.5)
    - "quality_distribution": {"complete": n, "partial": n, "incomplete": n}
    - "missing_mandatory_by_field": {field_name: count_of_records_missing_it}
    - "missing_optional_by_field": {field_name: count_of_records_missing_it}
    - "record_scores": list of per-record quality scores
    - "duplicate_groups": list of duplicate group summaries (from deduplicator)
    - "overall_quality_percentage": percentage of valid records (0-100)
    """
    total = len(products)
    if total == 0:
        return {
            "total_records": 0,
            "valid_records": 0,
            "invalid_records": 0,
            "quality_distribution": {"complete": 0, "partial": 0, "incomplete": 0},
            "missing_mandatory_by_field": {},
            "missing_optional_by_field": {},
            "record_scores": [],
            "duplicate_groups": [],
            "overall_quality_percentage": 0.0,
        }

    # Compute per-record scores and presence flags
    scores: List[float] = []
    missing_mandatory_counter: Counter = Counter()
    missing_optional_counter: Counter = Counter()
    present_optional_counter: Counter = Counter()  # how many records HAVE the field

    for product in products:
        score, present_flags = compute_record_quality_score(product)
        scores.append(score)

        # Track missing mandatory fields
        for field in MANDATORY_FIELDS:
            if not present_flags.get(field, False):
                missing_mandatory_counter[field] += 1

        # Track missing optional fields
        for field in OPTIONAL_FIELDS:
            if not present_flags.get(field, False):
                missing_optional_counter[field] += 1
            else:
                present_optional_counter[field] += 1

    # Classify records
    valid_count = sum(1 for s in scores if s >= 0.5)
    invalid_count = total - valid_count

    # Quality distribution
    complete = sum(1 for s in scores if s >= 1.0)
    partial = sum(1 for s in scores if 0.5 <= s < 1.0)
    incomplete = sum(1 for s in scores if s < 0.5)

    # Missing mandatory/optional per-field summaries
    missing_mandatory_by_field = {
        field: missing_mandatory_counter[field] for field in MANDATORY_FIELDS
    }
    missing_optional_by_field = {
        field: missing_optional_counter[field] for field in OPTIONAL_FIELDS
    }

    # Detect duplicate groups using the deduplicator
    from services.deduplicator import detect_duplicates
    dup_groups = detect_duplicates(products)
    dup_summary = [
        {
            "type": g.duplicate_type,
            "key": g.key,
            "record_count": len(g.records),
            "reason": g.reason,
        }
        for g in dup_groups
    ]

    overall_percentage = (valid_count / total * 100) if total > 0 else 0.0

    return {
        "total_records": total,
        "valid_records": valid_count,
        "invalid_records": invalid_count,
        "quality_distribution": {
            "complete": complete,
            "partial": partial,
            "incomplete": incomplete,
        },
        "missing_mandatory_by_field": missing_mandatory_by_field,
        "missing_optional_by_field": missing_optional_by_field,
        "record_scores": scores,
        "duplicate_groups": dup_summary,
        "overall_quality_percentage": round(overall_percentage, 2),
    }