"""Tests for MongoDB connection handling (core/database.py).

Connections are mocked so no active MongoDB server is required.
"""

from unittest.mock import MagicMock, patch

import pytest
from pymongo.errors import ConnectionFailure, PyMongoError

from core.database import MongoDBManager, COLLECTION_PRODUCTS
from core.exceptions import DatabaseConnectionError


def test_connect_success(monkeypatch):
    mock_client = MagicMock()
    mock_client.admin.command.return_value = {"ok": 1}
    with patch("core.database.MongoClient", return_value=mock_client):
        mgr = MongoDBManager()
        assert mgr.connect() is True
        assert mgr.is_connected() is True
        mock_client.admin.command.assert_called_once_with("ping")


def test_connect_failure_reported_as_disconnected(monkeypatch):
    mock_client = MagicMock()
    mock_client.admin.command.side_effect = ConnectionFailure("server down")
    with patch("core.database.MongoClient", return_value=mock_client):
        mgr = MongoDBManager()
        assert mgr.connect() is False
        assert mgr.is_connected() is False


def test_connect_pymongo_error_reported_as_disconnected(monkeypatch):
    mock_client = MagicMock()
    mock_client.admin.command.side_effect = PyMongoError("unexpected")
    with patch("core.database.MongoClient", return_value=mock_client):
        mgr = MongoDBManager()
        assert mgr.connect() is False
        assert mgr.is_connected() is False


def test_get_collection_when_disconnected_raises():
    mgr = MongoDBManager()
    with pytest.raises(DatabaseConnectionError):
        mgr.get_collection(COLLECTION_PRODUCTS)


def test_get_database_when_disconnected_raises():
    mgr = MongoDBManager()
    with pytest.raises(DatabaseConnectionError):
        mgr.get_database()


def test_get_collection_when_connected(monkeypatch):
    mock_client = MagicMock()
    mock_client.admin.command.return_value = {"ok": 1}
    mock_db = MagicMock()
    mock_client.__getitem__.return_value = mock_db
    with patch("core.database.MongoClient", return_value=mock_client):
        mgr = MongoDBManager()
        mgr.connect()

        collection = mgr.get_collection(COLLECTION_PRODUCTS)
        assert collection is mock_db.__getitem__.return_value


def test_close_releases_client(monkeypatch):
    mock_client = MagicMock()
    mock_client.admin.command.return_value = {"ok": 1}
    with patch("core.database.MongoClient", return_value=mock_client):
        mgr = MongoDBManager()
        mgr.connect()
        assert mgr.is_connected() is True

        mgr.close()
        mock_client.close.assert_called_once()
        assert mgr.is_connected() is False
