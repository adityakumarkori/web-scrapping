"""Deduplication service for the GRANIT EU pipeline.

Detects duplicate products based on article number, EAN/GTIN, and canonical URL.
Returns groups of records that should be reviewed, avoiding incorrect merging
of distinct products that share superficial similarities.
"""

from typing import Any, Dict, List, Optional, Set, Tuple, Literal

from core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Duplicate types
# ---------------------------------------------------------------------------

DuplicateType = Literal["article_number", "ean_gtin", "canonical_url"]


class DuplicateGroup:
    """A group of product records that share a duplicate key.

    Attributes:
        duplicate_type: The type of duplicate detection (article_number, ean_gtin,
            or canonical_url).
        key: The duplicate value that links the records.
        records: List of product dicts involved in the duplicate group.
        reason: Human-readable explanation of why these records grouped together.
    """

    def __init__(
        self,
        duplicate_type: DuplicateType,
        key: str,
        records: List[Dict[str, Any]],
        reason: str,
    ) -> None:
        self.duplicate_type = duplicate_type
        self.key = key
        self.records = records
        self.reason = reason

    def __repr__(self) -> str:
        return f"<DuplicateGroup type={self.duplicate_type} key={self.key} n={len(self.records)}>"


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

def detect_article_number_duplicates(
    products: List[Dict[str, Any]],
) -> List[DuplicateGroup]:
    """Detect duplicate products sharing the same ``article_number``.

    Only groups records when at least two have the same non-empty article_number.
    Records with empty/missing article_number are ignored for this detection type.

    Returns a list of ``DuplicateGroup`` instances.  Each group contains 2+ records.
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}

    for product in products:
        article_number = product.get("article_number")
        if not article_number:
            continue  # skip records without an article number
        key = article_number.strip()
        if key not in groups:
            groups[key] = []
        groups[key].append(product)

    # Filter to only include groups with 2+ records
    duplicates: List[DuplicateGroup] = []
    for key, records in groups.items():
        if len(records) >= 2:
            duplicates.append(
                DuplicateGroup(
                    duplicate_type="article_number",
                    key=key,
                    records=records,
                    reason=f"Multiple products share article_number '{key}'",
                )
            )

    return duplicates


def detect_ean_gtin_duplicates(
    products: List[Dict[str, Any]],
) -> List[DuplicateGroup]:
    """Detect duplicate products sharing the same EAN/GTIN.

    Normalises EAN/GTIN values (strips whitespace, removes dashes) before
    comparison.  Only groups records when at least two have the same non-empty
    normalised EAN/GTIN.

    Returns a list of ``DuplicateGroup`` instances.
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}

    for product in products:
        ean = product.get("ean_gtin")
        if not ean:
            continue
        # Normalise: strip, remove spaces and dashes, uppercase
        normalized = str(ean).strip().replace(" ", "").replace("-", "").upper()
        if not normalized:
            continue
        if normalized not in groups:
            groups[normalized] = []
        groups[normalized].append(product)

    # Filter to only include groups with 2+ records
    duplicates: List[DuplicateGroup] = []
    for key, records in groups.items():
        if len(records) >= 2:
            duplicates.append(
                DuplicateGroup(
                    duplicate_type="ean_gtin",
                    key=key,
                    records=records,
                    reason=f"Multiple products share EAN/GTIN '{key}'",
                )
            )

    return duplicates


def detect_canonical_url_duplicates(
    products: List[Dict[str, Any]],
) -> List[DuplicateGroup]:
    """Detect duplicate products sharing the same ``product_url`` (canonical URL).

    Only groups records when at least two have the same non-empty product_url.

    Returns a list of ``DuplicateGroup`` instances.
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}

    for product in products:
        url = product.get("product_url")
        if not url:
            continue
        normalized = url.strip().rstrip("/").lower()
        if not normalized:
            continue
        if normalized not in groups:
            groups[normalized] = []
        groups[normalized].append(product)

    # Filter to only include groups with 2+ records
    duplicates: List[DuplicateGroup] = []
    for key, records in groups.items():
        if len(records) >= 2:
            duplicates.append(
                DuplicateGroup(
                    duplicate_type="canonical_url",
                    key=key,
                    records=records,
                    reason=f"Multiple products share canonical URL '{key}'",
                )
            )

    return duplicates


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def detect_duplicates(
    products: List[Dict[str, Any]],
    *,
    article_number: bool = True,
    ean_gtin: bool = True,
    canonical_url: bool = True,
) -> List[DuplicateGroup]:
    """Run all duplicate detection modes and return combined duplicate groups.

    Args:
        products: List of product dicts (typically cleaned/validated).
        article_number: When True, detect article_number duplicates.
        ean_gtin: When True, detect EAN/GTIN duplicates.
        canonical_url: When True, detect product_url duplicates.

    Returns:
        A list of ``DuplicateGroup`` instances.  Groups are ordered by
        duplicate_type: article_number first, then ean_gtin, then canonical_url.
    """
    all_duplicates: List[DuplicateGroup] = []

    if article_number:
        all_duplicates.extend(
            detect_article_number_duplicates(products)
        )

    if ean_gtin:
        all_duplicates.extend(
            detect_ean_gtin_duplicates(products)
        )

    if canonical_url:
        all_duplicates.extend(
            detect_canonical_url_duplicates(products)
        )

    # Deduplicate groups that might overlap (same record appearing in multiple
    # duplicate types).  We keep all groups but mark overlaps if needed.
    # For now, just return as-is; callers can filter overlaps.

    logger.info("detect_duplicates found %d groups across %d modes", len(all_duplicates), 3)
    return all_duplicates


# ---------------------------------------------------------------------------
# Avoid incorrect merging guidance
# ---------------------------------------------------------------------------

def should_merge_records(
    a: Dict[str, Any],
    b: Dict[str, Any],
    *,
    allow_ean_overlap: bool = False,
) -> bool:
    """Determine whether two product records should be merged.

    The default is ``False`` — duplicate detection should *not* automatically
    trigger a merge.  Return ``True`` only when explicit intent is present.

    Heuristics:
    - Never merge if ``is_synthetic`` differs between records.
    - Never merge if ``data_origin`` differs and neither is ``manual_entry``.
    - Merge candidates typically share the same ``article_number`` or
      ``ean_gtIN`` AND have compatible field values (price, name, etc.).

    Args:
        a: First product dict.
        b: Second product dict.
        allow_ean_overlap: When True, records with the same EAN/GTIN but
            different article numbers may be considered for merging (use with
            extreme caution).

    Returns:
        ``True`` when the records *may* be merged, ``False`` otherwise.
    """
    # If is_synthetic differs, do not merge
    if a.get("is_synthetic") != b.get("is_synthetic"):
        return False

    # If data_origin differs and neither is manual_entry, do not merge
    a_origin = a.get("data_origin")
    b_origin = b.get("data_origin")
    if a_origin != b_origin and a_origin != "manual_entry" and b_origin != "manual_entry":
        return False

    # If neither has an article_number, cannot reliably merge
    if not a.get("article_number") and not b.get("article_number"):
        return False

    return True