"""Reiner DB-FaSta-Mapper map_station_facilities (Aufzug-/Rolltreppen-Status).

Uebersetzt das flache raw-dict aus ``fetch_station_facilities`` deterministisch in
einen ``CanonicalRecord`` mit ``StationFacilityPayload``. Rein: kein HTTP, kein
Logging, kein ``datetime.now()`` (``retrieved_at`` injiziert).

Lizenz: CC-BY 4.0 (Tier A), Attribution "Deutsche Bahn / DB InfraGO AG". Die Werte
werden unveraendert durchgereicht (nur ortsnah gefiltert) -> ``modified`` Default.
KRITISCH (Pitfall 4): Anlagen an Bahnhoefen im Stadtgebiet, ``distance_km`` je
Anlage; ``geo`` bleibt ``None``.
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    SourceId,
    StationFacilityPayload,
)

_CC_BY_URL = "https://creativecommons.org/licenses/by/4.0/"


def map_station_facilities(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe DB-FaSta-Anlagendaten auf einen ``CanonicalRecord`` ab.

    ``observed_at`` bleibt ``None`` (FaSta liefert den aktuellen Status ohne
    expliziten Messzeitpunkt; ``retrieved_at`` ist der Abrufzeitpunkt). Join-Keys
    aus dem Register. ``geo=None`` (Pitfall 4: anlagennah, nicht stadtgenau).
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.DB_FASTA,
        license_id=LicenseId.CC_BY_4_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Deutsche Bahn / DB InfraGO AG",
            license_url=_CC_BY_URL,
        ),
        payload=StationFacilityPayload(
            count=raw.get("count", 0),
            counts=raw.get("counts", {}),
            facilities=raw.get("facilities", []),
            truncated=raw.get("truncated", False),
        ),
    )
