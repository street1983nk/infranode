"""Mapper ``map_muenchen_radzaehl`` (DATA-40, Münchner Rad-Tageszählwerte, Tier A).

Übersetzt das rohe Adapter-dict (``slug``/``stations``/``as_of``) deterministisch
in einen ``CanonicalRecord`` mit ``CountStationPayload`` (kanonische Zählstellen-
Hülle, wiederverwendet für alle bike-counts-Quellen). Rein: kein HTTP, keine
Systemuhr (``retrieved_at`` keyword-only injiziert).

LIZENZ (GOV-01): Landeshauptstadt München, Open-Data-Portal, Datenlizenz
Deutschland Namensnennung 2.0 (``DL_DE_BY_2_0`` -> Tier A), [VERIFIED 2026-06-23
via package_show license_id ``dl-by-de/2.0``]. Attribution mit Namensnennung.
"""

from __future__ import annotations

from datetime import UTC, datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    CountStationPayload,
    LicenseId,
    LicenseTier,
    SourceId,
)

# Attribution wortgenau wie in sources.SOURCE_LICENSE["muenchen_radzaehl"]
# (T-11-SRC-DRIFT): die DL-DE/BY-Namensnennung ist "Landeshauptstadt München".
_LICENSE_URL = "https://www.govdata.de/dl-de/by-2-0"
_ATTRIBUTION = "Landeshauptstadt München"


def _parse_datum(value: object) -> datetime | None:
    """Parst das Münchner ``datum`` (Format ``JJJJ.MM.TT``) defensiv zu datetime."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.strptime(value, "%Y.%m.%d").replace(tzinfo=UTC)
    except ValueError:
        return None


def _period(value: object) -> str | None:
    """ISO-Tagesdatum (``JJJJ-MM-TT``) aus dem ``JJJJ.MM.TT``-``datum`` oder None."""
    parsed = _parse_datum(value)
    return parsed.date().isoformat() if parsed else None


def _directions(station: dict) -> dict | None:
    """Baut ``{Richtungslabel: Tageswert}`` aus den beiden Richtungen (oder None)."""
    out: dict[str, int | None] = {}
    for label_key, value_key in (
        ("direction_1", "direction_1_value"),
        ("direction_2", "direction_2_value"),
    ):
        label = station.get(label_key)
        if label:
            out[str(label)] = station.get(value_key)
    return out or None


def map_muenchen_radzaehl(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe Münchner Rad-Tageszählwerte auf einen ``CanonicalRecord`` ab.

    Je Station ein schlankes Zähl-dict (``station``/``lat``/``lon``/``value`` =
    Tagessumme/``granularity`` "day"/``period`` ISO-Tag/``directions``) im
    ``CountStationPayload``. ``observed_at`` ist der jüngste Zähltag (``as_of``);
    ``geo=None`` (Koordinaten je Station im Payload). Tier A (DL-DE/BY 2.0).
    """
    counts: list[dict] = []
    for station in raw.get("stations", []):
        if not isinstance(station, dict):
            continue
        counts.append(
            {
                "station": station.get("zaehlstelle"),
                "station_id": station.get("zaehlstelle"),
                "name_long": station.get("name_long"),
                "lat": station.get("lat"),
                "lon": station.get("lon"),
                "value": station.get("value"),
                "vehicle_type": "bicycle",
                "granularity": "day",
                "period": _period(station.get("datum")),
                "directions": _directions(station),
            }
        )

    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=_parse_datum(raw.get("as_of")),
        retrieved_at=retrieved_at,
        source=SourceId.MUENCHEN_RADZAEHL,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_ATTRIBUTION,
            license_url=_LICENSE_URL,
        ),
        payload=CountStationPayload(counts=counts),
    )
