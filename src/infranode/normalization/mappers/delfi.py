"""Reiner DELFI-GTFS-Mapper auf CanonicalRecord (DATA-05, GOV-01/03).

Übersetzt eine GTFS-``stops.txt``-Zeile deterministisch in einen
``CanonicalRecord`` mit ``TransitStopPayload``. Die Funktion ist rein: kein HTTP,
kein Logging, kein ``datetime.now()``. Der ``retrieved_at``-Zeitstempel wird
keyword-only injiziert, damit Tests deterministisch bleiben.

Die DELFI-Daten (bundesweiter GTFS-Datensatz, bereitgestellt von der DELFI e.V.)
sind unter CC-BY 4.0 verfügbar: ``license_id=CC_BY_4_0``, ``license_tier=A``
(HART, Owner-Entscheid; kennzeichnet die permissive Lizenz zur korrekten
Attribution und Weiternutzung) und die wortgenaue Attribution "DELFI e.V."
(deckungsgleich mit
DATA-LICENSES.md). Anders als der Autobahn-Mapper setzt DELFI ``geo`` PRO Stop
aus ``stop_lat``/``stop_lon``; ``observed_at=None`` (Haltestellen sind statisch).
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

_CC_BY_URL = "https://creativecommons.org/licenses/by/4.0/"


def _opt_int(value: str | None) -> int | None:
    """GTFS-Ganzzahlfeld zu ``int`` oder ``None`` (leere/fehlende Werte)."""
    if value in (None, ""):
        return None
    return int(value)


def map_delfi_stop(
    row: dict,
    *,
    city_slug: str,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet eine GTFS-stops.txt-Zeile auf einen ``CanonicalRecord`` (Tier A) ab.

    ``geo`` wird PRO Stop aus ``stop_lat``/``stop_lon`` gesetzt; ``observed_at``
    ist ``None`` (Haltestellen sind statisch). Der ``retrieved_at``-Zeitstempel
    wird injiziert (kein ``datetime.now()`` im Mapper). Die Join-Keys
    ``ags``/``wikidata_qid`` werden aus dem Register durchgereicht (Default
    ``None``); ein ``TransitStopPayload`` nutzt ``stop_id`` als fachlichen
    Schlüssel, daher KEIN ``station_id``.
    """
    return CanonicalRecord(
        city_slug=city_slug,
        geo=GeoPoint(lat=float(row["stop_lat"]), lon=float(row["stop_lon"])),
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.DELFI,
        license_id=LicenseId.CC_BY_4_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(text="DELFI e.V.", license_url=_CC_BY_URL),
        payload=TransitStopPayload(
            stop_id=row["stop_id"],
            stop_name=row["stop_name"],
            location_type=_opt_int(row.get("location_type")),
            parent_station=row.get("parent_station") or None,
            platform_code=row.get("platform_code") or None,
            wheelchair_boarding=_opt_int(row.get("wheelchair_boarding")),
        ),
    )
