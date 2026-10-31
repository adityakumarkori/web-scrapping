"""Tests for the source management service (services/source.py).

Uses injected mock collections so no live MongoDB server is required.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from services.source import (
    AUTHORIZATION_STATUSES,
    SOURCE_TYPES,
    SourceService,
    validate_source_url,
)
from core.exceptions import DataValidationError


def _mock_collection():
    return MagicMock()


def _make_source(**overrides):
    base = {
        "source_id": "src-001",
        "source_name": "Test Source",
        "source_url": "https://example.com",
        "source_type": "website",
        "authorization_status": "pending",
        "allowed_usage": None,
        "enabled": True,
        "notes": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    base.update(overrides)
    return base


def test_validate_source_url_valid():
    assert validate_source_url("https://example.com") == "https://example.com"
    assert validate_source_url("http://example.com/path") == "http://example.com/path"


def test_validate_source_url_invalid():
    with pytest.raises(DataValidationError):
        validate_source_url("")
    with pytest.raises(DataValidationError):
        validate_source_url("not-a-url")
    with pytest.raises(DataValidationError):
        validate_source_url("https://")


def test_add_source_defaults_pending():
    coll = _mock_collection()
    coll.insert_one.return_value = None
    service = SourceService(collection=coll)

    result = service.add_source(source_name="My Source", source_url="https://example.com")

    assert result["source_name"] == "My Source"
    assert result["source_url"] == "https://example.com"
    assert result["authorization_status"] == "pending"
    assert result["enabled"] is True
    assert "source_id" in result
    assert "created_at" in result
    assert "updated_at" in result
    coll.insert_one.assert_called_once()


def test_add_source_rejects_invalid_url():
    coll = _mock_collection()
    service = SourceService(collection=coll)

    with pytest.raises(DataValidationError):
        service.add_source(source_name="X", source_url="not-a-url")
    coll.insert_one.assert_not_called()


def test_add_source_rejects_invalid_type():
    coll = _mock_collection()
    service = SourceService(collection=coll)

    with pytest.raises(DataValidationError):
        service.add_source(
            source_name="X", source_url="https://example.com", source_type="blob"
        )
    coll.insert_one.assert_not_called()


def test_add_source_rejects_invalid_authorization():
    coll = _mock_collection()
    service = SourceService(collection=coll)

    with pytest.raises(DataValidationError):
        service.add_source(
            source_name="X",
            source_url="https://example.com",
            authorization_status="blessed",
        )
    coll.insert_one.assert_not_called()


def test_list_sources():
    coll = _mock_collection()
    coll.find.return_value.sort.return_value = [_make_source(), _make_source(source_id="src-002")]
    service = SourceService(collection=coll)

    sources = service.list_sources()
    assert len(sources) == 2
    coll.find.assert_called_once_with({}, {"_id": 0})


def test_get_source_by_id_found():
    coll = _mock_collection()
    doc = _make_source()
    coll.find_one.return_value = doc
    service = SourceService(collection=coll)

    result = service.get_source_by_id("src-001")
    assert result == doc
    coll.find_one.assert_called_once_with({"source_id": "src-001"}, {"_id": 0})


def test_get_source_by_id_not_found():
    coll = _mock_collection()
    coll.find_one.return_value = None
    service = SourceService(collection=coll)

    assert service.get_source_by_id("missing") is None


def test_update_source():
    coll = _mock_collection()
    coll.update_one.return_value.matched_count = 1
    coll.find_one.return_value = _make_source(source_name="Updated")
    service = SourceService(collection=coll)

    result = service.update_source("src-001", {"source_name": "Updated"})
    assert result["source_name"] == "Updated"
    coll.update_one.assert_called_once()
    assert "updated_at" in coll.update_one.call_args[0][1]["$set"]


def test_update_source_not_found():
    coll = _mock_collection()
    coll.update_one.return_value.matched_count = 0
    service = SourceService(collection=coll)

    assert service.update_source("missing", {"source_name": "X"}) is None


def test_enable_disable_source():
    coll = _mock_collection()
    coll.update_one.return_value.matched_count = 1
    coll.find_one.return_value = _make_source(enabled=True)
    service = SourceService(collection=coll)

    service.enable_source("src-001")
    assert coll.update_one.call_args[0][1]["$set"]["enabled"] is True

    service.disable_source("src-001")
    assert coll.update_one.call_args[0][1]["$set"]["enabled"] is False


def test_change_authorization_status():
    coll = _mock_collection()
    coll.update_one.return_value.matched_count = 1
    coll.find_one.return_value = _make_source(authorization_status="approved")
    service = SourceService(collection=coll)

    service.change_authorization_status("src-001", "approved")
    assert coll.update_one.call_args[0][1]["$set"]["authorization_status"] == "approved"

    with pytest.raises(DataValidationError):
        service.change_authorization_status("src-001", "blessed")


def test_is_eligible_for_extraction():
    approved_enabled = _make_source(authorization_status="approved", enabled=True)
    assert SourceService.is_eligible_for_extraction(approved_enabled) is True

    approved_disabled = _make_source(authorization_status="approved", enabled=False)
    assert SourceService.is_eligible_for_extraction(approved_disabled) is False

    pending_enabled = _make_source(authorization_status="pending", enabled=True)
    assert SourceService.is_eligible_for_extraction(pending_enabled) is False

    rejected_enabled = _make_source(authorization_status="rejected", enabled=True)
    assert SourceService.is_eligible_for_extraction(rejected_enabled) is False

    assert SourceService.is_eligible_for_extraction(None) is False


def test_source_types_and_authorization_statuses():
    assert SOURCE_TYPES == {"website", "api", "csv", "manual"}
    assert AUTHORIZATION_STATUSES == {"pending", "approved", "rejected"}
