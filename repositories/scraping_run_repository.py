"""Scraping run repository for the GRANIT EU data scraper.

Persists scraping execution information so that the application can maintain
a history of runs, including success/failure counts, records harvested, and
associated errors.

Typical usage:
    repo = ScrapingRunRepository()
    repo.create_run(run_id="run-2024-01-15-01", source_id="src-123",
                    status="completed", records_found=50, extracted_count=45,
                    inserted_count=40, updated_count=3, skipped_count=2,
                    rejected_count=5, failed_count=0, errors=[])
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.database import mongodb
from core.exceptions import DatabaseConnectionError


class ScrapingRunRepository:
    """Repository for scraping execution history."""

    def __init__(self) -> None:
        if not mongodb.is_connected():
            raise DatabaseConnectionError(
                "MongoDB is not connected. Call connect() first."
            )
        self._collection = mongodb.scraping_runs

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def create_run(
        self,
        run_id: str,
        source_id: str,
        status: str = "pending",
        records_found: int = 0,
        extracted_count: int = 0,
        inserted_count: int = 0,
        updated_count: int = 0,
        skipped_count: int = 0,
        rejected_count: int = 0,
        failed_count: int = 0,
        errors: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Create a new scraping run record.

        Returns the inserted document (without _id transformation) or
        ``None`` when MongoDB is not connected.
        """
        if errors is None:
            errors = []

        now = datetime.now(timezone.utc)
        document: Dict[str, Any] = {
            "run_id": run_id,
            "source_id": source_id,
            "status": status,
            "started_at": now,
            "records_found": records_found,
            "extracted_count": extracted_count,
            "inserted_count": inserted_count,
            "updated_count": updated_count,
            "skipped_count": skipped_count,
            "rejected_count": rejected_count,
            "failed_count": failed_count,
            "errors": errors,
        }

        try:
            result = self._collection.insert_one(document)
            document["_id"] = str(result.inserted_id)
            logger.info(
                "Created scraping run run_id=%s source_id=%s status=%s",
                run_id,
                source_id,
                status,
            )
            return document
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to create scraping run")
            return None

    def update_run(
        self,
        run_id: str,
        *,
        status: Optional[str] = None,
        completed_at: Optional[datetime] = None,
        records_found: Optional[int] = None,
        extracted_count: Optional[int] = None,
        inserted_count: Optional[int] = None,
        updated_count: Optional[int] = None,
        skipped_count: Optional[int] = None,
        rejected_count: Optional[int] = None,
        failed_count: Optional[int] = None,
        errors: Optional[List[str]] = None,
    ) -> bool:
        """Update an existing scraping run.

        Returns ``True`` when the update was acknowledged.
        """
        if not mongodb.is_connected():
            raise DatabaseConnectionError("MongoDB is not connected.")

        if completed_at is None:
            now = datetime.now(timezone.utc)
        else:
            now = completed_at

        update_fields: Dict[str, Any] = {}

        if status is not None:
            update_fields["status"] = status
        if completed_at is not None:
            update_fields["completed_at"] = completed_at
        if records_found is not None:
            update_fields["records_found"] = records_found
        if extracted_count is not None:
            update_fields["extracted_count"] = extracted_count
        if inserted_count is not None:
            update_fields["inserted_count"] = inserted_count
        if updated_count is not None:
            update_fields["updated_count"] = updated_count
        if skipped_count is not None:
            update_fields["skipped_count"] = skipped_count
        if rejected_count is not None:
            update_fields["rejected_count"] = rejected_count
        if failed_count is not None:
            update_fields["failed_count"] = failed_count
        if errors is not None:
            update_fields["errors"] = errors

        update_fields["last_updated"] = now

        try:
            result = self._collection.update_one(
                {"run_id": run_id}, {"$set": update_fields}
            )
            return result.acknowledged and result.modified_count > 0
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to update scraping run")
            return False

    def get_run_by_id(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a scraping run by its ``run_id``.

        Returns the document dict (with ``started_at`` / ``completed_at`` as
        ``datetime`` objects) or ``None`` when not found.
        """
        if not mongodb.is_connected():
            raise DatabaseConnectionError("MongoDB is not connected.")

        try:
            raw = self._collection.find_one({"run_id": run_id})
            if raw is None:
                return None
            # Ensure completed_at is a datetime if present
            if raw.get("completed_at") is not None and not isinstance(
                raw["completed_at"], datetime
            ):
                try:
                    raw["completed_at"] = datetime.fromisoformat(
                        str(raw["completed_at"])
                    )
                except Exception:
                    pass
            return raw
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to get scraping run by id")
            return None

    def get_recent_runs(
        self, limit: int = 10, source_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve the most recent scraping runs.

        Returns a list ordered by ``started_at`` descending.
        """
        if not mongodb.is_connected():
            raise DatabaseConnectionError("MongoDB is not connected.")

        filter_criterion: Dict[str, Any] = {}
        if source_id:
            filter_criterion["source_id"] = source_id

        try:
            cursor = (
                self._collection.find(filter_criterion)
                .sort("started_at", -1)
                .limit(limit)
            )
            results: List[Dict[str, Any]] = []
            for doc in cursor:
                # Ensure started_at / completed_at are datetime objects
                for key in ("started_at", "completed_at"):
                    if doc.get(key) is not None and not isinstance(doc[key], datetime):
                        try:
                            doc[key] = datetime.fromisoformat(str(doc[key]))
                        except Exception:
                            pass
                results.append(doc)
            return results
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to get recent scraping runs")
            return []

    def get_runs_by_source(self, source_id: str) -> List[Dict[str, Any]]:
        """Retrieve all scraping runs for a given source, ordered newest first."""
        return self.get_recent_runs(limit=100, source_id=source_id)

    # ------------------------------------------------------------------
    # Counts
    # ------------------------------------------------------------------

    def count_runs(self) -> int:
        """Return the total number of scraping runs recorded."""
        if not mongodb.is_connected():
            raise DatabaseConnectionError("MongoDB is not connected.")
        try:
            return self._collection.count_documents({})
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to count runs")
            return 0

    def count_runs_by_status(self, status: str) -> int:
        """Return the number of runs with a given status."""
        if not mongodb.is_connected():
            raise DatabaseConnectionError("MongoDB is not connected.")
        try:
            return self._collection.count_documents({"status": status})
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to count runs by status")
            return 0