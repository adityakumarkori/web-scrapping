"""Application configuration management for the GRANIT EU data scraper.

Configuration is provided by Pydantic settings and read from environment
variables (via a ``.env`` file when present). Secrets such as database
credentials are never hardcoded; safe defaults are provided where possible
and required settings are validated.
"""

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = Field(default="GRANIT EU Data Manager")
    app_env: str = Field(default="development")
    debug: bool = Field(default=False)

    # MongoDB
    mongodb_uri: str = Field(default="mongodb://localhost:27017")
    mongodb_database: str = Field(default="granit_eu")
    mongodb_server_selection_timeout_ms: int = Field(default=10000, ge=1000)

    # Logging
    log_level: str = Field(default="INFO")

    # Scraping / export limits
    max_product_records: int = Field(default=100, ge=1)
    http_request_timeout: int = Field(default=30, ge=1)

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }

    @field_validator("app_env")
    @classmethod
    def _validate_app_env(cls, value: str) -> str:
        allowed = {"development", "staging", "production"}
        if value.lower() not in allowed:
            raise ValueError(
                f"app_env must be one of {sorted(allowed)}, got {value!r}"
            )
        return value.lower()

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        import logging

        level_name = value.upper()
        if level_name not in {
            "DEBUG",
            "INFO",
            "WARNING",
            "ERROR",
            "CRITICAL",
        }:
            raise ValueError(f"log_level must be a valid logging level, got {value!r}")
        return level_name


settings = Settings()
