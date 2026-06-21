"""Strukturierte Output-Typen der InfraNode-MCP-Tools (DX-05).

Jedes Tool gibt zur Laufzeit weiterhin den rohen API-Envelope als ``dict`` 1:1
durch (Blocker-4-Aufrufvertrag, keine Mapping-Logik hier). Die Tool-Funktionen
sind aber mit ``-> ToolEnvelope`` annotiert, damit FastMCP daraus ein
``outputSchema`` generiert: Verzeichnis-Scanner (Smithery/Glama) bewerten Tools
mit Output-Schema deutlich hoeher, und MCP-Clients erhalten zusaetzlich
strukturierten Inhalt (``structuredContent``) statt nur Text.

WICHTIG (Robustheit vor Striktheit): ``data`` ist ``Any`` (die Nutzlast variiert
je Ressource ueber ~47 Payload-Typen) und ``meta`` erlaubt Zusatzfelder
(``extra="allow"``), damit FastMCPs Rueckgabe-Validierung (``model_validate`` in
func_metadata.convert_result) NIE an einer realen Antwort scheitert. ``source_
status`` ist bewusst ``str`` statt ``Literal``: die API kennt heute ok/disabled/
no_data/not_covered/error/not_found/not_ingested, und ein neuer Wert darf einen
Live-Tool-Call nicht mit einem Validierungsfehler brechen (Graceful Degradation,
nie 5xx).
"""

from __future__ import annotations

from typing import Any, TypedDict


class ToolMeta(TypedDict, total=False):
    """Envelope-Metadaten: Quelle, Status, Cache, Lizenz und Attribution.

    Zusatzfelder (z.B. ``covered_cities``, ``radius_m`` bei partieller Abdeckung)
    bleiben dank ``extra="allow"`` erhalten.
    """

    __pydantic_config__ = {"extra": "allow"}  # type: ignore[misc]

    source: str
    source_status: str
    cache_status: str
    correlation_id: str
    license: str
    attribution: str


class ToolEnvelope(TypedDict):
    """Kanonischer InfraNode-Antwort-Envelope: normalisierte ``data`` + ``meta``.

    ``data`` ist ``null`` wenn die Quelle keine Daten lieferte (siehe
    ``meta.source_status``); sonst ein Objekt oder eine Liste je Ressource.
    """

    data: Any
    meta: ToolMeta
