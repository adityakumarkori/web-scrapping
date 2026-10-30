"""Reusable application exceptions for the GRANIT EU data scraper.

All exceptions derive from a common base so callers can catch
application-level errors specifically without silently suppressing them.
"""


class GranitError(Exception):
    """Base exception for all GRANIT application errors."""


class ConfigurationError(GranitError):
    """Raised when configuration is missing, invalid, or unreadable."""


class DatabaseConnectionError(GranitError):
    """Raised when a MongoDB connection cannot be established or used."""


class DataValidationError(GranitError):
    """Raised when product or source data fails validation."""


class ApplicationError(GranitError):
    """Raised for unexpected application-level failures."""
