"""Reiner HVV-GTFS-Mapper auf CanonicalRecord (DATA-05, GOV-01/02).

Schwester-Mapper zu ``map_delfi_stop``: übersetzt eine GTFS-``stops.txt``-Zeile
des Hamburger Verkehrsverbunds deterministisch in einen ``CanonicalRecord`` mit
``TransitStopPayload``. Die Funktion ist rein: kein HTTP, kein Logging, kein
``datetime.now()``. Der ``retrieved_at``-Zeitstempel wird keyword-only injiziert,
damit Tests deterministisch bleiben.

Die HVV-GTFS-Daten (bereitgestellt über das Hamburger Transparenzportal) sind
unter der Datenlizenz Deutschland - Namensnennung 2.0 (DL-DE/BY 2.0) verfügbar:
``license_id=DL_DE_BY_2_0``, ``license_tier=A`` (HART, Owner-Entscheid;
kennzeichnet die permissive Lizenz zur korrekten Attribution und Weiternutzung)
und die wortgenaue Attribution "Hamburger Verkehrsverbund GmbH (HVV)"
(deckungsgleich mit
DATA-LICENSES.md). ``geo`` wird PRO Stop aus ``stop_lat``/``stop_lon`` gesetzt;
``observed_at=None`` (Haltestellen sind statisch). HVV liefert gegenüber dem
Minimal-DELFI-Feed das zusätzliche Hamburg-Detail ``wheelchair_boarding`` und
``platform_code``.
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    GeoPoint,
    LicenseId,
    LicenseTier,
    SourceId,
    TransitStopPayload,
)

_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"


def _opt_int(value: str | None) -> int | None:
    """GTFS-Ganzzahlfeld zu ``int`` oder ``None`` (leere/fehlende Werte)."""
    if value in (None, ""):
        return None
    return int(value)


def map_hvv_stop(
    row: dict,
    *,
    city_slug: str,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet eine HVV-GTFS-stops.txt-Zeile auf einen ``CanonicalRecord`` ab.

    Identisches Muster wie ``map_delfi_stop``, nur mit HVV-Quelle, DL-DE/BY-2.0-
    Lizenz und HVV-Attribution. ``geo`` wird PRO Stop aus ``stop_lat``/
    ``stop_lon`` gesetzt; ``observed_at`` ist ``None`` (Haltestellen sind
    statisch). Der ``retrieved_at``-Zeitstempel wird injiziert (kein
    ``datetime.now()`` im Mapper). Die Join-Keys ``ags``/``wikidata_qid`` werden
    aus dem Register durchgereicht (Default ``None``); ein ``TransitStopPayload``
    nutzt ``stop_id`` als fachlichen Schluessel, daher KEIN ``station_id``.
    """
    return CanonicalRecord(
        city_slug=city_slug,
        geo=GeoPoint(lat=float(row["stop_lat"]), lon=float(row["stop_lon"])),
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.HVV,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Hamburger Verkehrsverbund GmbH (HVV)",
            license_url=_DL_DE_BY_URL,
        ),
        payload=TransitStopPayload(
            stop_id=row["stop_id"],
            stop_name=row["stop_name"],
            location_type=_opt_int(row.get("location_type")),
            parent_station=row.get("parent_station") or None,
            platform_code=row.get("platform_code") or None,
            wheelchair_boarding=_opt_int(row.get("wheelchair_boarding")),
        ),
    )
