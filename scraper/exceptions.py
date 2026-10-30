"""Scraping-specific exceptions for the GRANIT EU data scraper.

All exceptions derive from the application base so callers can catch
scraping failures specifically without silently suppressing them.
"""

from core.exceptions import GranitError


class ScrapingError(GranitError):
    """Base exception for all scraping operations."""


class SourceAccessError(ScrapingError):
    """Raised when a source cannot be accessed (authorization, SSRF, redirect)."""


class ParsingError(ScrapingError):
    """Raised when HTML or JSON-LD parsing fails."""


class ExtractionError(ScrapingError):
    """Raised when product extraction fails for a specific record."""
