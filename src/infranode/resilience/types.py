"""Reine Daten- und Enum-Vertraege der Resilienz-Schicht (KEIN I/O).

``SourceConfig`` ist ein gefrorenes Wert-Objekt (Pitfall 2: ``frozen=True``) mit
den per-Source-Parametern (Fresh-/Stale-TTL, Timeout), das ab Phase 4 pro Quelle
gehalten wird. ``CacheStatus`` benennt die vier moeglichen Cache-Ergebnisse
(HIT/MISS/STALE/STALE-ON-ERROR) als ``StrEnum``, damit der Status direkt als
Header-/Log-String nutzbar ist. Beide Typen sind Vertraege fuer Plan 03/04.
"""

from __future__ import annotations

import enum

from pydantic import BaseModel, ConfigDict, Field


class SourceConfig(BaseModel):
    """Gefrorene per-Source-Konfiguration (Name, Fresh-/Stale-TTL, Timeout).

    Alle Zeit-Felder muessen positiv sein (``gt=0``); ``ttl_fresh``/``ttl_stale``
    in Sekunden, ``timeout`` in Sekunden je Request. Frozen gegen versehentliche
    Mutation zur Laufzeit.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    ttl_fresh: int = Field(gt=0)
    ttl_stale: int = Field(gt=0)
    timeout: float = Field(gt=0)


class CacheStatus(enum.StrEnum):
    """Ergebnis eines Cache-Zugriffs (als String direkt log-/header-tauglich)."""

    HIT = "HIT"
    MISS = "MISS"
    STALE = "STALE"
    STALE_ON_ERROR = "STALE-ON-ERROR"
