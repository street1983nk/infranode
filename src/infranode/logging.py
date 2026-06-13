"""Strukturiertes JSON-Logging mit Correlation-ID (FND-03).

``add_correlation`` zieht die per-Request gesetzte Correlation-ID
(asgi-correlation-id ContextVar) als Feld ``request_id`` in jede Log-Zeile.
Der Processor muss als ERSTER laufen, ``JSONRenderer`` als letzter.
"""

from __future__ import annotations

import logging
from typing import Any

import structlog
from asgi_correlation_id import correlation_id


def add_correlation(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """Bindet die aktuelle Correlation-ID als ``request_id`` an das Event."""
    if request_id := correlation_id.get():
        event_dict["request_id"] = request_id
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Konfiguriert structlog fuer JSON-Logs auf stdout (Docker-erfassbar)."""
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
            add_correlation,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        # Caching deaktiviert: erlaubt deterministische Reconfiguration in Tests
        # (Capture-Pipeline) und kostet bei stdlib-LoggerFactory praktisch nichts.
        cache_logger_on_first_use=False,
    )
