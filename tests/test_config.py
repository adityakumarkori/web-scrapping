"""Tests for configuration management (config.py).

Tests do not require an active MongoDB server.
"""

import importlib

import pytest
from pydantic import ValidationError

import config


def test_default_values():
    assert config.settings.app_name == "GRANIT EU Data Manager"
    assert config.settings.app_env == "development"
    assert config.settings.debug is False
    # URI is loaded from .env if present; verify it starts safely
    assert config.settings.mongodb_uri.startswith(("mongodb://", "mongodb+srv://"))
    assert config.settings.mongodb_database == "granit_eu"
    assert config.settings.log_level == "INFO"
    assert config.settings.max_product_records == 100
    assert config.settings.http_request_timeout == 30


def test_env_values_loaded(monkeypatch):
    monkeypatch.setenv("APP_NAME", "Test App")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("MONGODB_URI", "mongodb://test:27017")
    monkeypatch.setenv("MONGODB_DATABASE", "test_db")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("MAX_PRODUCT_RECORDS", "50")
    monkeypatch.setenv("HTTP_REQUEST_TIMEOUT", "10")

    importlib.reload(config)

    assert config.settings.app_name == "Test App"
    assert config.settings.app_env == "production"
    assert config.settings.debug is True
    assert config.settings.mongodb_uri == "mongodb://test:27017"
    assert config.settings.mongodb_database == "test_db"
    assert config.settings.log_level == "DEBUG"
    assert config.settings.max_product_records == 50
    assert config.settings.http_request_timeout == 10


def test_invalid_app_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "invalid")
    with pytest.raises(ValidationError):
        importlib.reload(config)


def test_invalid_max_product_records(monkeypatch):
    monkeypatch.setenv("MAX_PRODUCT_RECORDS", "0")
    with pytest.raises(ValidationError):
        importlib.reload(config)


def test_invalid_log_level(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "BOGUS")
    with pytest.raises(ValidationError):
        importlib.reload(config)


def test_mongodb_uri_has_safe_default():
    assert config.settings.mongodb_uri.startswith("mongodb://")
