"""Rejected product repository for the GRANIT EU data scraper.

Stores product records that failed validation during the pipeline, along
with their validation errors and rejection metadata.  Rejected records are
never silently discarded — they are persisted separately so that the user
can inspect, review, and potentially retry them after correction.

Each rejected record retains the original extracted data, the source ID and
URL, article number (if available), validation errors, rejection reason,
rejection timestamp, and a reference to the associated scraping run ID.

Design notes:
- Synthetic or previously-verified records are never marked as verified
  when persisted here.
- The ``source_id`` + ``article_number`` composite is used for basic
  deduplication, but the same article number from different sources is
  allowed.
- Regional data arrays are preserved as-is.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional

from core.database import mongodb
from core.exceptions import DatabaseConnectionError
from services.cleaner import clean_product_dict
from services.validator import validate_required_fields, validate_provenance, identify_inconsistencies


def _convert_decimal128_to_decimal(document: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively convert stored Decimal128 values back to Python Decimal."""
    from bson import Decimal128

    def _convert(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, Decimal128):
            return value.to_decimal()
        if isinstance(value, dict):
            return {k: _convert(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_convert(v) for v in value]
        return value

    return _convert(document)


def _apply_decimal128_for_write(document: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively convert Python Decimal to Decimal128 for MongoDB storage."""
    from decimal import Decimal
    from bson import Decimal128

    def _convert(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, Decimal):
            return Decimal128(value)
        if isinstance(value, Decimal128):
            return value
        if isinstance(value, dict):
            return {k: _convert(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_convert(v) for v in value]
        return value

    return _convert(document)


class RejectedProductRepository:
    """Repository for rejected product records."""

    def __init__(self) -> None:
        if not mongodb.is_connected():
            raise DatabaseConnectionError(
                "MongoDB is not connected. Call connect() first."
            )
        self._collection = mongodb.rejected_products

    # ------------------------------------------------------------------
    # Persistence operations
    # ------------------------------------------------------------------

    def record_rejection(
        self,
        run_id: str,
        source_id: str,
        source_url: str,
        raw_extracted: Dict[str, Any],
        validation_errors: List[str],
        rejection_reason: str,
        article_number: Optional[str] = None,
    ) -> Optional[str]:
        """Persist a rejected product record.

        Returns the MongoDB ``inserted_id`` as a string, or ``None`` when
        MongoDB is not connected.
        """
        if not mongodb.is_connected():
            raise DatabaseConnectionError("MongoDB is not connected.")

        # Clean and prepare the raw extracted data
        cleaned = clean_product_dict(raw_extracted)

        # Convert Decimal128 for write
        prepared = _apply_decimal128_for_write(cleaned)

        # Set provenance / rejection metadata
        prepared["source_id"] = source_id
        prepared["source_url"] = source_url
        prepared["rejection_reason"] = rejection_reason
        prepared["rejected_at"] = datetime.now(timezone.utc)
        prepared["associated_run_id"] = run_id
        # Ensure verification_status is not "verified"
        if prepared.get("verification_status") == "verified":
            prepared["verification_status"] = "not_verified"
        # Ensure data_origin default
        if prepared.get("data_origin") is None:
            prepared["data_origin"] = "manual_entry"

        # Try deduplication: if we already have a rejected record with the
        # same {source_id, article_number}, we update it instead of creating
        # a duplicate.
        article = article_number or prepared.get("article_number")
        filter_criterion: Dict[str, Any] = {
            "source_id": source_id,
        }
        if article:
            filter_criterion["article_number"] = article

        try:
            # upsert: if a record with same source_id + article_number exists,
            # $set the new data; otherwise insert fresh.
            result = self._collection.update_one(
                filter_criterion,
                {"$set": prepared},
                upsert=True,
            )
            inserted_id = (
                str(result.upserted_id) if result.upserted_id else None
            )
            # Also update the rejection_reason and rejected_at even on match
            if result.matched_count > 0:
                # Refresh the rejection metadata on match
                self._collection.update_one(
                    filter_criterion,
                    {"$set": {
                        "rejection_reason": rejection_reason,
                        "rejected_at": prepared["rejected_at"],
                        "associated_run_id": run_id,
                    }},
                )
            logger.info(
                "Recorded rejection article_number=%s source_id=%s run_id=%s",
                article,
                source_id,
                run_id,
            )
            return inserted_id
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to record rejection")
            return None

    def get_by_source(self, source_id: str) -> List[Dict[str, Any]]:
        """Retrieve all rejected records for a given source.

        Returns a list with Decimal128 values converted back to Python
        ``Decimal`` for monetary fields.
        """
        if not mongodb.is_connected():
            raise DatabaseConnectionError("MongoDB is not connected.")

        try:
            cursor = self._collection.find({"source_id": source_id})
            results: List[Dict[str, Any]] = []
            for doc in cursor:
                results.append(_convert_decimal128_to_decimal(doc))
            # Sort by rejected_at descending
            results.sort(key=lambda d: d.get("rejected_at", datetime.min), reverse=True)
            return results
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to get rejected records by source")
            return []

    def get_recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Retrieve the most recently rejected records across all sources.

        Returns a list ordered by ``rejected_at`` descending.
        """
        if not mongodb.is_connected():
            raise DatabaseConnectionError("MongoDB is not connected.")

        try:
            cursor = self._collection.find().sort("rejected_at", -1).limit(limit)
            results: List[Dict[str, Any]] = []
            for doc in cursor:
                results.append(_convert_decimal128_to_decimal(doc))
            return results
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to get recent rejected records")
            return []

    def count_by_source(self, source_id: str) -> int:
        """Return the number of rejected records for a given source."""
        if not mongodb.is_connected():
            raise DatabaseConnectionError("MongoDB is not connected.")
        try:
            return self._collection.count_documents({"source_id": source_id})
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to count rejected by source")
            return 0

    def count_total(self) -> int:
        """Return the total number of rejected records in the collection."""
        if not mongodb.is_connected():
            raise DatabaseConnectionError("MongoDB is not connected.")
        try:
            return self._collection.count_documents({})
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to count total rejected")
            return 0

    def get_by_run_id(self, run_id: str) -> List[Dict[str, Any]]:
        """Retrieve all rejected records associated with a given scraping run."""
        if not mongodb.is_connected():
            raise DatabaseConnectionError("MongoDB is not connected.")

        try:
            cursor = self._collection.find({"associated_run_id": run_id})
            results: List[Dict[str, Any]] = []
            for doc in cursor:
                results.append(_convert_decimal128_to_decimal(doc))
            # Sort by rejected_at descending
            results.sort(key=lambda d: d.get("rejected_at", datetime.min), reverse=True)
            return results
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to get rejected records by run_id")
            return []