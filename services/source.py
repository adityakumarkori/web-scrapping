"""Source management service for the GRANIT EU data scraper.

Manages data sources stored in the ``data_sources`` collection:

- Add, list, get, update, enable/disable and change authorization status.
- Validates source URLs; rejects invalid URL formats.
- Only ``approved`` sources are eligible for automated extraction.
- Pending or rejected sources are never eligible for scraping.

No automated scraping is performed in this phase.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from uuid import uuid4

from core.database import COLLECTION_DATA_SOURCES, mongodb
from core.exceptions import DatabaseConnectionError, DataValidationError

SOURCE_TYPES = {"website", "api", "csv", "manual"}
AUTHORIZATION_STATUSES = {"pending", "approved", "rejected"}


def validate_source_url(url: str) -> str:
    """Validate and normalize a source URL.

    Raises:
        DataValidationError: when the URL is missing a scheme or host.
    """
    if not url or not isinstance(url, str):
        raise DataValidationError("source_url must be a non-empty string")
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        raise DataValidationError(f"Invalid source URL: {url!r}")
    return url.strip()


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SourceService:
    """Reusable source management service backed by MongoDB.

    A collection can be injected for testing; otherwise the shared MongoDB
    connection manager is used.
    """

    def __init__(self, collection: Any = None) -> None:
        self._collection = collection

    @property
    def collection(self):
        if self._collection is None:
            if not mongodb.is_connected():
                raise DatabaseConnectionError("MongoDB is not connected")
            self._collection = mongodb.get_collection(COLLECTION_DATA_SOURCES)
        return self._collection

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------
    def add_source(
        self,
        source_name: str,
        source_url: str,
        source_type: str = "website",
        authorization_status: str = "pending",
        allowed_usage: Optional[str] = None,
        enabled: bool = True,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Add a new data source.

        Default authorization status is ``pending``. Sources are never
        automatically approved.
        """
        source_type = (source_type or "website").lower()
        if source_type not in SOURCE_TYPES:
            raise DataValidationError(
                f"source_type must be one of {sorted(SOURCE_TYPES)}, got {source_type!r}"
            )

        authorization_status = (authorization_status or "pending").lower()
        if authorization_status not in AUTHORIZATION_STATUSES:
            raise DataValidationError(
                f"authorization_status must be one of {sorted(AUTHORIZATION_STATUSES)}, "
                f"got {authorization_status!r}"
            )

        source_url = validate_source_url(source_url)

        now = _now()
        document = {
            "source_id": str(uuid4()),
            "source_name": source_name,
            "source_url": source_url,
            "source_type": source_type,
            "authorization_status": authorization_status,
            "allowed_usage": allowed_usage,
            "enabled": bool(enabled),
            "notes": notes,
            "created_at": now,
            "updated_at": now,
        }
        self.collection.insert_one(document)
        return document

    def update_source(self, source_id: str, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update fields on an existing source by source_id.

        Returns the updated document, or ``None`` when not found.
        """
        if "source_url" in fields:
            fields["source_url"] = validate_source_url(fields["source_url"])
        if "source_type" in fields:
            stype = str(fields["source_type"]).lower()
            if stype not in SOURCE_TYPES:
                raise DataValidationError(
                    f"source_type must be one of {sorted(SOURCE_TYPES)}"
                )
            fields["source_type"] = stype
        if "authorization_status" in fields:
            status = str(fields["authorization_status"]).lower()
            if status not in AUTHORIZATION_STATUSES:
                raise DataValidationError(
                    f"authorization_status must be one of {sorted(AUTHORIZATION_STATUSES)}"
                )
            fields["authorization_status"] = status
        fields["updated_at"] = _now()

        result = self.collection.update_one(
            {"source_id": source_id}, {"$set": fields}
        )
        if result.matched_count == 0:
            return None
        return self.get_source_by_id(source_id)

    def enable_source(self, source_id: str) -> Optional[Dict[str, Any]]:
        """Enable a source. Returns the updated document or None."""
        return self.update_source(source_id, {"enabled": True})

    def disable_source(self, source_id: str) -> Optional[Dict[str, Any]]:
        """Disable a source. Returns the updated document or None."""
        return self.update_source(source_id, {"enabled": False})

    def change_authorization_status(
        self, source_id: str, authorization_status: str
    ) -> Optional[Dict[str, Any]]:
        """Change the authorization status of a source.

        Only ``pending``, ``approved`` and ``rejected`` are accepted.
        """
        return self.update_source(
            source_id, {"authorization_status": authorization_status}
        )

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------
    def list_sources(self) -> List[Dict[str, Any]]:
        """List all data sources."""
        return list(self.collection.find({}, {"_id": 0}).sort("created_at", -1))

    def get_source_by_id(self, source_id: str) -> Optional[Dict[str, Any]]:
        """Get a single source by source_id."""
        return self.collection.find_one({"source_id": source_id}, {"_id": 0})

    # ------------------------------------------------------------------
    # Eligibility
    # ------------------------------------------------------------------
    @staticmethod
    def is_eligible_for_extraction(source: Optional[Dict[str, Any]]) -> bool:
        """Return True only when a source is approved and enabled.

        Pending or rejected sources are never eligible for automated
        extraction, regardless of their enabled flag.
        """
        if not source:
            return False
        return (
            source.get("authorization_status") == "approved"
            and source.get("enabled") is True
        )
