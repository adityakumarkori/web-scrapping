"""MongoDB foundation for the GRANIT EU data scraper.

Provides a reusable MongoDB connection manager built on PyMongo:
- single shared client (no repeated connections),
- connection testing via ping,
- database and collection access,
- graceful handling of connection failures,
- explicit client cleanup.

The application must continue to run when MongoDB is unavailable;
connection failures are logged and reported as disconnected rather than
crashing the process.
"""

from typing import Optional

from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, PyMongoError

from config import settings
from core.exceptions import DatabaseConnectionError
from core.logging import get_logger

logger = get_logger(__name__)

COLLECTION_PRODUCTS = "products"
COLLECTION_DATA_SOURCES = "data_sources"
COLLECTION_SCRAPING_RUNS = "scraping_runs"

ALL_COLLECTIONS = (
    COLLECTION_PRODUCTS,
    COLLECTION_DATA_SOURCES,
    COLLECTION_SCRAPING_RUNS,
)


class MongoDBManager:
    """Reusable MongoDB connection manager.

    Holds a single PyMongo client for the lifetime of the application and
    exposes database/collection accessors. Connection failures are handled
    gracefully: :meth:`connect` returns ``False`` instead of raising, while
    accessors raise :class:`DatabaseConnectionError` when not connected.
    """

    def __init__(self) -> None:
        self._client: Optional[MongoClient] = None
        self._database = None
        self._connected = False

    def connect(self) -> bool:
        """Establish (or reuse) the MongoDB connection.

        Returns ``True`` when connected, ``False`` when the connection
        attempt failed. Failures are logged but not raised so the
        application can keep running in offline mode.
        """
        if self._client is not None:
            return self._connected

        try:
            self._client = MongoClient(
                settings.mongodb_uri,
                serverSelectionTimeoutMS=2000,
                connectTimeoutMS=2000,
            )
            # Force a connection check immediately.
            self._client.admin.command("ping")
            self._database = self._client[settings.mongodb_database]
            self._ensure_indexes()
            self._connected = True
            logger.info("Connected to MongoDB database: %s", settings.mongodb_database)
        except (ConnectionFailure, PyMongoError) as exc:
            self._client = None
            self._database = None
            self._connected = False
            logger.warning("MongoDB connection failed: %s", exc)
        return self._connected

    def _ensure_indexes(self) -> None:
        """Create basic, non-unique indexes for the initial collections.

        No product-specific uniqueness rules are enforced here, since the
        product schema is not yet finalized.
        """
        if self._database is None:
            return
        initialize_collections(self._database)

    def is_connected(self) -> bool:
        """Return ``True`` if a live connection is held."""
        return self._connected

    def get_database(self):
        """Return the configured database handle.

        Raises:
            DatabaseConnectionError: when not connected to MongoDB.
        """
        if not self._connected or self._database is None:
            raise DatabaseConnectionError(
                "MongoDB is not connected. Call connect() first."
            )
        return self._database

    def get_collection(self, name: str):
        """Return a collection handle by name.

        Raises:
            DatabaseConnectionError: when not connected to MongoDB.
        """
        return self.get_database()[name]

    def close(self) -> None:
        """Close the MongoDB client and release resources."""
        if self._client is not None:
            self._client.close()
            self._client = None
            self._database = None
            self._connected = False
            logger.info("MongoDB connection closed")


def initialize_collections(database) -> None:
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


# Module-level singleton shared across the application.
mongodb = MongoDBManager()
