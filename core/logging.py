"""Centralized logging configuration for the GRANIT EU data scraper.

Provides configurable log levels, console output with useful timestamps,
and a logger factory. Secrets and credentials are never logged.
"""

import logging
import sys

from config import settings


def setup_logging() -> None:
    """Configure the root logger once for the application."""
    level_name = str(settings.log_level).upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )


def get_logger(name: str) -> logging.Logger:
    """Return a logger for the given module name."""
    return logging.getLogger(name)
