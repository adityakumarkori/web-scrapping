"""MongoDB foundation for the GRANIT EU data scraper.

Provides a reusable MongoDB connection manager built on PyMongo:
- single shared client (no repeated connections),
- connection testing via ping,
- database and collection access,
- graceful handling of connection failures,
- explicit client cleanup,
- collection initialization with indexes.

The application must continue to run when MongoDB is unavailable;
connection failures are logged and reported as disconnected rather than
crashing the process.
"""

from typing import Optional, Any, Dict, List

from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import ConnectionFailure, PyMongoError

from config import settings
from core.exceptions import DatabaseConnectionError
from core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Collection name constants
# ---------------------------------------------------------------------------

COLLECTION_PRODUCTS = "products"
COLLECTION_DATA_SOURCES = "data_sources"
COLLECTION_SCRAPING_RUNS = "scraping_runs"
COLLECTION_REJECTED_PRODUCTS = "rejected_products"
COLLECTION_DATASET_QUALITY_REPORTS = "dataset_quality_reports"

ALL_COLLECTION_NAMES = (
    COLLECTION_PRODUCTS,
    COLLECTION_DATA_SOURCES,
    COLLECTION_SCRAPING_RUNS,
    COLLECTION_REJECTED_PRODUCTS,
    COLLECTION_DATASET_QUALITY_REPORTS,
)

# ---------------------------------------------------------------------------
# Connection status enum (string values for serialization / UI)
# ---------------------------------------------------------------------------

CONNECTION_STATUS_CHOICES = {
    "connected": "CONNECTED",
    "disconnected": "DISCONNECTED",
    "connection_error": "CONNECTION_ERROR",
}


# ---------------------------------------------------------------------------
# Decimal128 conversion helpers
# ---------------------------------------------------------------------------

def _to_decimal128(value: Any) -> Any:
    """Convert a Python ``Decimal`` to a BSON ``Decimal128`` for MongoDB.

    MongoDB does not natively store Python ``Decimal`` objects; they must be
    converted to ``Decimal128`` for storage and converted back to ``Decimal``
    when reading.
    """
    from decimal import Decimal
    from bson import Decimal128

    if value is None:
        return None
    if isinstance(value, Decimal):
        return Decimal128(value)
    if isinstance(value, Decimal128):
        return value
    return value


def _from_decimal128(value: Any) -> Any:
    """Convert a BSON ``Decimal128`` back to a Python ``Decimal``.

    Called when reading records from MongoDB so that financial values
    (prices, VAT, etc.) retain ``Decimal`` precision instead of becoming
    ``float``.
    """
    from decimal import Decimal
    from bson import Decimal128

    if value is None:
        return None
    if isinstance(value, Decimal128):
        return value.to_decimal()
    if isinstance(value, Decimal):
        return value
    # Recursively process dicts and lists
    if isinstance(value, dict):
        return {k: _from_decimal128(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_decimal128(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Safe index creation helpers
# ---------------------------------------------------------------------------

def _create_indexes(database: Any) -> None:
    """Create all required collection indexes.

    These are non-unique indexes; article numbers are not made globally unique
    because the same article number can be used by different manufacturers/sources.
    The identity strategy uses ``{source_id: <id>, article_number: <number>}``
    together with ``ean_gtin`` where available.
    """

    # --- products ---
    database[COLLECTION_PRODUCTS].create_index(
        [("article_number", ASCENDING), ("source_id", ASCENDING)]
    )
    database[COLLECTION_PRODUCTS].create_index(
        [("ean_gtin", ASCENDING), ("source_id", ASCENDING)]
    )
    database[COLLECTION_PRODUCTS].create_index(
        [("product_url", ASCENDING), ("source_id", ASCENDING)], unique=False
    )
    database[COLLECTION_PRODUCTS].create_index(
        [("verification_status", ASCENDING), ("source_id", ASCENDING)]
    )
    database[COLLECTION_PRODUCTS].create_index(
        [("data_origin", ASCENDING), ("source_id", ASCENDING)]
    )

    # --- data_sources ---
    database[COLLECTION_DATA_SOURCES].create_index("source_id", unique=True)
    database[COLLECTION_DATA_SOURCES].create_index("source_name")
    database[COLLECTION_DATA_SOURCES].create_index("source_url")

    # --- scraping_runs ---
    database[COLLECTION_SCRAPING_RUNS].create_index("run_id", unique=True)
    database[COLLECTION_SCRAPING_RUNS].create_index("source_id")
    database[COLLECTION_SCRAPING_RUNS].create_index("status")

    # --- rejected_products ---
    database[COLLECTION_REJECTED_PRODUCTS].create_index(
        [("source_id", ASCENDING), ("article_number", ASCENDING)]
    )
    database[COLLECTION_REJECTED_PRODUCTS].create_index(
        [("rejected_at", DESCENDING)]
    )

    # --- dataset_quality_reports ---
    database[COLLECTION_DATASET_QUALITY_REPORTS].create_index(
        [("generated_at", DESCENDING)]
    )
    database[COLLECTION_DATASET_QUALITY_REPORTS].create_index("run_id")


# ---------------------------------------------------------------------------
# MongoDB Connection Manager
# ---------------------------------------------------------------------------

class MongoDBManager:
    """Reusable MongoDB connection manager.

    Holds a single PyMongo client for the lifetime of the application and
    exposes database/collection accessors. Connection failures are handled
    gracefully: :meth:`connect` returns ``True``/``False`` instead of raising,
    while accessors raise :class:`DatabaseConnectionError` when not connected.

    Connection status: CONNECTED, DISCONNECTED, CONNECTION_ERROR.
    """

    # ------------------------------------------------------------------
    # Connection status
    # ------------------------------------------------------------------

    class Status:
        DISCONNECTED = "DISCONNECTED"
        CONNECTED = "CONNECTED"
        CONNECTION_ERROR = "CONNECTION_ERROR"

    def __init__(self) -> None:
        self._client: Optional[Any] = None
        self._database: Optional[Any] = None
        self._status: str = self.Status.DISCONNECTED
        self._collection_cache: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        """Establish (or reuse) the MongoDB connection.

        Returns ``True`` when connected, ``False`` when the connection
        attempt failed. Failures are logged but not raised so the
        application can keep running in offline mode.

        On success the database is selected, indexes are ensured, and
        the status is set to ``CONNECTED``.
        """
        if self._status == self.Status.CONNECTED:
            return True

        try:
            self._client = MongoClient(
                settings.mongodb_uri,
                serverSelectionTimeoutMS=settings.mongodb_server_selection_timeout_ms,
                connectTimeoutMS=settings.mongodb_server_selection_timeout_ms,
                socketTimeoutMS=settings.mongodb_server_selection_timeout_ms,
                maxPoolSize=10,
                minPoolSize=1,
            )

            # Force a connection check immediately.
            self._client.admin.command("ping")

            self._database = self._client[settings.mongodb_database]

            # Initialize collections and indexes
            _create_indexes(self._database)

            self._status = self.Status.CONNECTED
            logger.info(
                "Connected to MongoDB database: %s", settings.mongodb_database
            )
            return True

        except (ConnectionFailure, PyMongoError) as exc:
            self._client = None
            self._database = None
            self._status = self.Status.CONNECTION_ERROR
            logger.warning("MongoDB connection failed: %s", exc)
            return False

    def close(self) -> None:
        """Close the MongoDB client and release resources.

        Alias for :meth:`disconnect` for compatibility with existing test suites.
        """
        self.disconnect()

    def disconnect(self) -> None:
        """Close the MongoDB client and release resources."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                pass
            self._client = None
            self._database = None
            self._status = self.Status.DISCONNECTED
            logger.info("MongoDB connection closed")

    def is_connected(self) -> bool:
        """Return ``True`` if a live connection is held (status is CONNECTED)."""
        return self._status == self.Status.CONNECTED

    def status_string(self) -> str:
        """Return the human-readable connection status."""
        return self._status

    # ------------------------------------------------------------------
    # Database accessors
    # ------------------------------------------------------------------

    def get_database(self) -> Any:
        """Return the configured database handle.

        Raises:
            DatabaseConnectionError: when not connected to MongoDB.
        """
        if not self.is_connected() or self._database is None:
            raise DatabaseConnectionError(
                "MongoDB is not connected. Call connect() first."
            )
        return self._database

    def get_collection(self, name: str) -> Any:
        """Return a collection handle by name.

        Raises:
            DatabaseConnectionError: when not connected to MongoDB.
        """
        if not self.is_connected():
            raise DatabaseConnectionError(
                "MongoDB is not connected. Call connect() first."
            )
        if name in self._collection_cache:
            return self._collection_cache[name]
        db = self.get_database()
        coll = db[name]
        self._collection_cache[name] = coll
        return coll

    # ------------------------------------------------------------------
    # Pipeline (Decimal128) conversion — applied recursively
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_decimal128_recursive(document: Any) -> Any:
        """Recursively convert Decimal values to Decimal128 for MongoDB storage.

        Needed because PyMongo does not persist Python ``Decimal`` objects
        natively; they must be encoded as ``Decimal128``.
        """
        from decimal import Decimal
        from bson import Decimal128

        if document is None:
            return None
        if isinstance(document, Decimal):
            return Decimal128(document)
        if isinstance(document, Decimal128):
            return document
        if isinstance(document, dict):
            return {
                k: MongoDBManager._apply_decimal128_recursive(v)
                for k, v in document.items()
            }
        if isinstance(document, list):
            return [
                MongoDBManager._apply_decimal128_recursive(v) for v in document
            ]
        return document

    @staticmethod
    def _apply_from_decimal128_recursive(document: Any) -> Any:
        """Recursively convert stored Decimal128 values back to Python ``Decimal``.

        Called after a read from MongoDB so that financial values retain
        ``Decimal`` precision instead of becoming ``float``.
        """
        from decimal import Decimal
        from bson import Decimal128

        if document is None:
            return None
        if isinstance(document, Decimal128):
            return document.to_decimal()
        if isinstance(document, dict):
            return {
                k: MongoDBManager._apply_from_decimal128_recursive(v)
                for k, v in document.items()
            }
        if isinstance(document, list):
            return [
                MongoDBManager._apply_from_decimal128_recursive(v) for v in document
            ]
        return document

    # ------------------------------------------------------------------
    # Collection initialization
    # ------------------------------------------------------------------

    def initialize_collections(self) -> None:
        """Create all required collections and non-unique indexes.

        This is called automatically after a successful ``connect()``.
        """
        if not self.is_connected() or self._database is None:
            raise DatabaseConnectionError(
                "MongoDB is not connected. Call connect() first."
            )
        _create_indexes(self._database)
        logger.info("Collections and indexes initialized")

    # ------------------------------------------------------------------
    # Collection property accessors (convenience)
    # ------------------------------------------------------------------

    @property
    def products(self) -> Any:
        return self.get_collection(COLLECTION_PRODUCTS)

    @property
    def data_sources(self) -> Any:
        return self.get_collection(COLLECTION_DATA_SOURCES)

    @property
    def scraping_runs(self) -> Any:
        return self.get_collection(COLLECTION_SCRAPING_RUNS)

    @property
    def rejected_products(self) -> Any:
        return self.get_collection(COLLECTION_REJECTED_PRODUCTS)

    @property
    def dataset_quality_reports(self) -> Any:
        return self.get_collection(COLLECTION_DATASET_QUALITY_REPORTS)

    # ------------------------------------------------------------------
    # --- Repr / debugging ---
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return f"<MongoDBManager status={self._status} db={settings.mongodb_database}>"


# ---------------------------------------------------------------------------
# Module-level singleton shared across the application.
# ---------------------------------------------------------------------------

mongodb = MongoDBManager()


# ---------------------------------------------------------------------------
# Module-level initialize_collections (required by existing tests)
# ---------------------------------------------------------------------------

def initialize_collections(database: Any) -> None:
    """Initialize all collections with non-unique indexes.

    Creates the products, data_sources and scraping_runs collections and
    adds indexes appropriate to each. No uniqueness constraints that would
    prevent multiple source records or regional prices are created.

    Indexes:
        products: article_number, ean_gtin, category
        data_sources: source_name, source_url
        scraping_runs: run_id, source_id, status
    """
    database[COLLECTION_PRODUCTS].create_index("article_number")
    database[COLLECTION_PRODUCTS].create_index("ean_gtin")
    database[COLLECTION_PRODUCTS].create_index("category")

    database[COLLECTION_DATA_SOURCES].create_index("source_name")
    database[COLLECTION_DATA_SOURCES].create_index("source_url")

    database[COLLECTION_SCRAPING_RUNS].create_index("run_id")
    database[COLLECTION_SCRAPING_RUNS].create_index("source_id")
    database[COLLECTION_SCRAPING_RUNS].create_index("status")