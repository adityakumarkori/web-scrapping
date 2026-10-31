"""Product repository for the GRANIT EU data scraper.

Handles persistence of validated product records to MongoDB, including
Decimal128 conversion for monetary values, regional_data preservation,
and a source-aware upsert strategy that prevents accidental merging of
records from different sources.

Strategy:
  - Products are identified by the composite key
    ``{source_id, article_number}`` together with ``ean_gtin`` where
    available.  This allows the same article number to exist multiple
    times when it comes from different sources or manufacturers.
  - Upsert uses ``source_id`` + ``article_number`` as the match criterion.
  - If ``ean_gtin`` is present it is also used to help match existing
    records, but a mismatch does not force a new record — the caller
    must decide based on business logic.
  - Regional data arrays are preserved: a new entry is appended if it
    does not already exist for the same ``country_code``; otherwise the
    existing entry is updated with the $set operator.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional

from pymongo.errors import DuplicateKeyError

from core.database import mongodb
from core.exceptions import DatabaseConnectionError, DataValidationError
from services.cleaner import clean_product_dict
from services.validator import validate_required_fields, validate_provenance

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _convert_decimal128_to_decimal(document: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively convert stored Decimal128 values back to Python Decimal.

    Applied to records read from MongoDB so that financial values retain
    Decimal precision.
    """
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
    """Recursively convert Python Decimal values to Decimal128 for MongoDB storage.

    Called before inserting or updating a document so that prices, VAT,
    and other monetary fields are stored as Decimal128 instead of being
    lost or coerced to float.
    """

    def _convert(value: Any) -> Any:
        if value is None:
            return None
        from decimal import Decimal
        from bson import Decimal128

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


# ---------------------------------------------------------------------------
# Repository class
# ---------------------------------------------------------------------------

class ProductRepository:
    """Repository for product record persistence."""

    def __init__(self) -> None:
        if not mongodb.is_connected():
            raise DatabaseConnectionError(
                "MongoDB is not connected. Call connect() first."
            )
        self._collection = mongodb.products

    # ------------------------------------------------------------------
    # Insert helpers
    # ------------------------------------------------------------------

    def _prepare_document(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Clean, validate, and prepare a product dict for MongoDB storage.

        Steps:
        1. Run the Phase 4 cleaning pipeline on the raw dict.
        2. Validate required fields and provenance.
        3. Apply Decimal128 conversion for monetary values.
        4. Ensure provenance fields are present.
        """
        # Step 1: Clean
        cleaned = clean_product_dict(raw)

        # Step 2: Schema / provenance validation
        # Required fields check
        is_valid, missing = validate_required_fields(cleaned)
        if not is_valid:
            raise DataValidationError(
                f"Product missing mandatory fields: {', '.join(missing)}"
            )

        # Provenance validation
        provenance_ok, provenance_msg = validate_provenance(cleaned)
        if not provenance_ok:
            raise DataValidationError(f"Product provenance error: {provenance_msg}")

        # Step 3: Apply Decimal128 for write
        prepared = _apply_decimal128_for_write(cleaned)

        # Ensure data_origin has a default if missing
        if prepared.get("data_origin") is None:
            prepared["data_origin"] = "manual_entry"

        # Ensure verification_status has a default
        if prepared.get("verification_status") is None:
            prepared["verification_status"] = "not_verified"

        # Ensure is_synthetic has a default
        if prepared.get("is_synthetic") is None:
            prepared["is_synthetic"] = False

        return prepared

    # ------------------------------------------------------------------
    # Core CRUD operations
    # ------------------------------------------------------------------

    def insert_product(self, raw: Dict[str, Any]) -> Optional[str]:
        """Insert a single product record.

        Returns the MongoDB ``inserted_id`` on success, or ``None`` when
        the record is considered a duplicate of an existing product
        (same ``source_id`` + ``article_number``) and was intentionally
        skipped.

        Raises:
            DataValidationError: when the product fails schema validation.
            DatabaseConnectionError: when MongoDB is not connected.
        """
        prepared = self._prepare_document(raw)

        # Use source_id + article_number as the match criterion for upsert
        article_number = prepared.get("article_number")
        source_id = prepared.get("source_id", "unknown")

        filter_criterion: Dict[str, Any] = {
            "source_id": source_id,
            "article_number": article_number,
        }

        # Also include ean_gtin in the filter if present
        ean = prepared.get("ean_gtin")
        if ean:
            filter_criterion["ean_gtin"] = ean

        try:
            result = self._collection.insert_one(prepared)
            logger.info(
                "Inserted product article_number=%s source_id=%s id=%s",
                article_number,
                source_id,
                result.inserted_id,
            )
            return str(result.inserted_id)
        except DuplicateKeyError:
            # Another product with the same {source_id, article_number} already exists
            logger.warning(
                "Duplicate product skipped: article_number=%s source_id=%s",
                article_number,
                source_id,
            )
            return None

    def insert_many(self, records: List[Dict[str, Any]]) -> Dict[str, int]:
        """Insert multiple product records.

        Returns a dict with counts: ``inserted``, ``skipped`` (duplicates),
        ``failed`` (validation/exception errors).
        """
        if not records:
            return {"inserted": 0, "skipped": 0, "failed": 0}

        prepared: List[Dict[str, Any]] = []
        skip_keys: set = set()
        errors: List[str] = []

        for raw in records:
            try:
                prepared.append(self._prepare_document(raw))
            except DataValidationError as exc:
                errors.append(str(exc))

        if not prepared:
            return {"inserted": 0, "skipped": 0, "failed": len(records)}

        # Batch insert with ordered=False so one failure does not stop the rest
        from pymongo import WriteConcern

        # Deduplicate within the batch by {source_id, article_number}
        seen_keys: set = set()
        batch_to_insert: List[Dict[str, Any]] = []
        for doc in prepared:
            key = (doc.get("source_id", "unknown"), doc.get("article_number"))
            if key in seen_keys:
                # Duplicate within same batch — skip
                continue
            seen_keys.add(key)
            batch_to_insert.append(doc)

        if not batch_to_insert:
            return {
                "inserted": 0,
                "skipped": len(prepared),
                "failed": len(errors),
            }

        try:
            self._collection.insert_many(batch_to_insert, ordered=False)
            inserted_count = len(batch_to_insert)
            skipped_count = len(prepared) - inserted_count
            return {
                "inserted": inserted_count,
                "skipped": skipped_count,
                "failed": len(errors),
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("Bulk insert failed")
            # Count how many were actually inserted before the error
            # (pymongo ordered=False may partially succeed)
            actual_inserted = self._collection.count_documents(
                {"_id": {"$in": [doc.get("_id") for doc in batch_to_insert if doc.get("_id")]}}
            )
            return {
                "inserted": actual_inserted,
                "skipped": len(batch_to_insert) - actual_inserted,
                "failed": len(errors) + (len(batch_to_insert) - actual_inserted),
            }

    # ------------------------------------------------------------------
    # Retrieval operations
    # ------------------------------------------------------------------

    def get_by_id(self, product_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single product by its MongoDB ``_id``.

        The returned document has Decimal128 values converted back to
        Python ``Decimal`` for monetary fields.
        """
        if not mongodb.is_connected():
            raise DatabaseConnectionError("MongoDB is not connected.")
        try:
            raw = self._collection.find_one({"_id": product_id})
            if raw is None:
                return None
            return _convert_decimal128_to_decimal(raw)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to get product by id")
            return None

    def get_by_article_number(
        self, article_number: str, source_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve products by article number, optionally filtered by source.

        Returns a list because the same article number can appear across
        different sources/manufacturers.
        """
        if not mongodb.is_connected():
            raise DatabaseConnectionError("MongoDB is not connected.")

        filter_criterion: Dict[str, Any] = {"article_number": article_number}
        if source_id:
            filter_criterion["source_id"] = source_id

        try:
            cursor = self._collection.find(filter_criterion)
            results: List[Dict[str, Any]] = []
            for doc in cursor:
                results.append(_convert_decimal128_to_decimal(doc))
            return results
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to get products by article_number")
            return []

    def get_by_gtin(self, ean_gtin: str) -> List[Dict[str, Any]]:
        """Retrieve products by EAN/GTIN barcode.

        Returns all products that have this GTIN, regardless of source.
        """
        if not mongodb.is_connected():
            raise DatabaseConnectionError("MongoDB is not connected.")

        filter_criterion: Dict[str, Any] = {"ean_gtin": ean_gtin}
        try:
            cursor = self._collection.find(filter_criterion)
            results: List[Dict[str, Any]] = []
            for doc in cursor:
                results.append(_convert_decimal128_to_decimal(doc))
            return results
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to get products by GTIN")
            return []

    def get_by_source(self, source_id: str) -> List[Dict[str, Any]]:
        """Retrieve all products from a given source.

        Returns a list of product records associated with *source_id*.
        """
        if not mongodb.is_connected():
            raise DatabaseConnectionError("MongoDB is not connected.")

        filter_criterion: Dict[str, Any] = {"source_id": source_id}
        try:
            cursor = self._collection.find(filter_criterion)
            results: List[Dict[str, Any]] = []
            for doc in cursor:
                results.append(_convert_decimal128_to_decimal(doc))
            return results
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to get products by source")
            return []

    def get_all(self) -> List[Dict[str, Any]]:
        """Retrieve all product records.

        Returns a list of all products in the collection.
        """
        if not mongodb.is_connected():
            raise DatabaseConnectionError("MongoDB is not connected.")

        try:
            cursor = self._collection.find({})
            results: List[Dict[str, Any]] = []
            for doc in cursor:
                results.append(_convert_decimal128_to_decimal(doc))
            return results
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to get all products")
            return []

    # ------------------------------------------------------------------
    # Update / Upsert operations
    # ------------------------------------------------------------------

    def upsert_product(self, raw: Dict[str, Any]) -> Dict[str, int]:
        """Upsert a single product record.

        Strategy:
        - Prepare the document (clean, validate, Decimal128 conversion).
        - Match on ``{source_id, article_number}`` (and ``ean_gtin`` if present).
        - If a match is found, $set the fields (updates regional_data, price,
          provenance, etc.) without overwriting the whole record.
        - If no match is found, insert as a new record.

        Returns a dict with counts: ``matched``, ``modified``, ``inserted``.
        """
        prepared = self._prepare_document(raw)
        article_number = prepared.get("article_number")
        source_id = prepared.get("source_id", "unknown")

        filter_criterion: Dict[str, Any] = {
            "source_id": source_id,
            "article_number": article_number,
        }
        ean = prepared.get("ean_gtin")
        if ean:
            filter_criterion["ean_gtin"] = ean

        # $set update — only overwrite the fields present in the prepared doc
        update_operation = {"$set": prepared}

        try:
            result = self._collection.update_one(
                filter_criterion, update_operation, upsert=True
            )
            return {
                "matched": result.matched_count,
                "modified": result.modified_count,
                "upserted_id": (
                    str(result.upserted_id) if result.upserted_id else None
                ),
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("Upsert failed")
            return {"matched": 0, "modified": 0, "upserted_id": None, "error": str(exc)}

    def update_product(
        self, product_id: str, fields: Dict[str, Any]
    ) -> bool:
        """Update specific fields of a product by its MongoDB _id.

        Returns ``True`` when the update was acknowledged.
        """
        if not mongodb.is_connected():
            raise DatabaseConnectionError("MongoDB is not connected.")

        # Convert any Decimal values to Decimal128 for MongoDB
        from services.cleaner import _apply_decimal128_for_write

        prepared = _apply_decimal128_for_write(fields)

        try:
            result = self._collection.update_one(
                {"_id": product_id}, {"$set": prepared}
            )
            return result.acknowledged and result.modified_count > 0
        except Exception as exc:  # noqa: BLE001
            logger.exception("Product update failed")
            return False

    # ------------------------------------------------------------------
    # Deletion
    # ------------------------------------------------------------------

    def delete_product(self, product_id: str) -> bool:
        """Delete a product by its MongoDB _id.

        Returns ``True`` when a document was actually deleted.
        """
        if not mongodb.is_connected():
            raise DatabaseConnectionError("MongoDB is not connected.")

        try:
            result = self._collection.delete_one({"_id": product_id})
            return result.deleted_count > 0
        except Exception as exc:  # noqa: BLE001
            logger.exception("Product delete failed")
            return False

    # ------------------------------------------------------------------
    # Counts / statistics
    # ------------------------------------------------------------------

    def count_products(self) -> int:
        """Return the total number of product records in the collection."""
        if not mongodb.is_connected():
            raise DatabaseConnectionError("MongoDB is not connected.")
        try:
            return self._collection.count_documents({})
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to count products")
            return 0

    def get_statistics(self) -> Dict[str, Any]:
        """Return aggregate statistics about the product collection.

        Includes counts by data_origin, verification_status, and a breakdown
        of how many records have regional_data entries.
        """
        if not mongodb.is_connected():
            raise DatabaseConnectionError("MongoDB is not connected.")

        try:
            total = self.count_products()

            # Distribution by data_origin
            pipeline = [
                {"$group": {
                    "_id": "$data_origin",
                    "count": {"$sum": 1},
                }}
            ]
            origin_dist = list(self._collection.aggregate(pipeline))
            origin_map: Dict[str, int] = {}
            for entry in origin_dist:
                origin_map[entry["_id"]] = entry["count"]

            # Distribution by verification_status
            pipeline2 = [
                {"$group": {
                    "_id": "$verification_status",
                    "count": {"$sum": 1},
                }}
            ]
            status_dist = list(self._collection.aggregate(pipeline2))
            status_map: Dict[str, int] = {}
            for entry in status_dist:
                status_map[entry["_id"]] = entry["count"]

                # Count records with regional_data
            regional_count = self._collection.count_documents(
                {"regional_data": {"$exists": True, "$ne": []}}
            )

            return {
                "total_products": total,
                "by_data_origin": origin_map,
                "by_verification_status": status_map,
                "with_regional_data": regional_count,
                "without_regional_data": total - regional_count,
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to get product statistics")
            return {
                "total_products": 0,
                "by_data_origin": {},
                "by_verification_status": {},
                "with_regional_data": 0,
                "without_regional_data": 0,
            }