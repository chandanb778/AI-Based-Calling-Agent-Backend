"""
Structured logging configuration.

Provides a centralized logger factory with JSON-formatted output
for production observability.  Import `get_logger` anywhere.
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

from app.config import settings

# ── Formatter that includes timestamp, level, module ──
_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)-24s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def _configure_root() -> None:
    """One-time root logger setup (idempotent)."""
    global _configured
    if _configured:
        return

    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT))

    root = logging.getLogger()
    root.setLevel(level)
    # Avoid duplicate handlers if called multiple times
    if not root.handlers:
        root.addHandler(handler)

    # Quiet noisy third-party loggers
    for noisy in ("httpx", "httpcore", "urllib3", "websockets", "grpc"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Return a logger with the given name.

    Usage:
        from app.utils.logger import get_logger
        logger = get_logger(__name__)
        logger.info("Hello from %s", __name__)
    """
    _configure_root()
    return logging.getLogger(name or "horizon-realty")
