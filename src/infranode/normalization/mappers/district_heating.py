"""Reiner Fernwärme-/Wärmenetz-Mapper map_district_heating (DATA-41, Tier A).

Übersetzt das aggregierte Adapter-dict (aus ``ingest.district_heating._aggregate``)
deterministisch in einen ``CanonicalRecord`` mit ``DistrictHeatingPayload``. Die
Funktion ist rein: kein HTTP, kein Logging, kein ``datetime.now()`` (der
``retrieved_at``-Zeitstempel wird keyword-only injiziert, damit Tests
deterministisch bleiben).

Föderiert je Stadt-WFS (wie ``map_solar_roofs``): Lizenz/Attribution/Lizenz-URL
stehen je Stadt im raw-dict (Berlin DL-DE/Zero 2.0, Hamburg DL-DE/BY 2.0, beide
Tier A) und werden hier mit Fallback gelesen. Attribution ``modified=True``: der
Record ist ein verdichtetes Stadt-Aggregat (Flächen/Hausanschlüsse/Trassenlänge
je Betreiber), nicht die rohe WFS-Geometrie. ``geo=None`` (Stadtebene),
``observed_at=None`` (Stammdaten/Stichtag; ``reference_date`` trägt den Stand).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    DistrictHeatingPayload,
    LicenseId,
    LicenseTier,
    SourceId,
)

_FALLBACK_LICENSE_ID = "dl_de_zero_2_0"
_FALLBACK_LICENSE_URL = "https://www.govdata.de/dl-de/zero-2-0"
_FALLBACK_ATTRIBUTION = "Kommunale Wärmeplanung"


def map_district_heating(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet ein aggregiertes Wärmenetz-dict auf einen ``CanonicalRecord`` ab.

    ``retrieved_at`` wird injiziert (kein ``datetime.now()`` im Mapper). Lizenz/
    Attribution je Stadt aus dem raw-dict (Fallback DL-DE/Zero 2.0). Alle
    Payload-Felder werden defensiv per ``raw.get(...)`` gelesen (None-Fallback,
    T-07-IN); ``networks``/``operators`` fallen leer-defensiv auf Listen zurück.
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.DISTRICT_HEATING,
        license_id=LicenseId(raw.get("license_id") or _FALLBACK_LICENSE_ID),
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=raw.get("attribution") or _FALLBACK_ATTRIBUTION,
            license_url=raw.get("license_url") or _FALLBACK_LICENSE_URL,
            modified=True,
        ),
        payload=DistrictHeatingPayload(
            network_area_count=raw.get("network_area_count"),
            supplied_area_km2=raw.get("supplied_area_km2"),
            operator_count=raw.get("operator_count"),
            operators=raw.get("operators") or [],
            house_connections=raw.get("house_connections"),
            network_length_km=raw.get("network_length_km"),
            networks=raw.get("networks") or [],
            area_basis=raw.get("area_basis"),
            reference_date=raw.get("reference_date"),
        ),
    )
