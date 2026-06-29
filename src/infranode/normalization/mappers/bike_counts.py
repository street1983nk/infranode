"""bike-counts-Mapper je Stadt + gemeinsamer Record-Helper (DATA-40, Tier A).

Alle bike-counts-Quellen münden in die kanonische ``CountStationPayload``-Hülle
(``kind="count_station"``, ``counts`` je Station). ``build_bike_count_record``
baut den ``CanonicalRecord``-Envelope (Lizenz/Attribution/observed_at) einheitlich;
die per-Stadt-Mapper liefern nur die ``counts``-Liste + Lizenz-Parameter. Rein:
kein HTTP, keine Systemuhr (``retrieved_at`` keyword-only injiziert).

Lizenz JE URSPRUNG verifiziert (GOV-01). Eco-Counter/Eco-Visio ist ausgeschlossen
(Owner-Entscheidung 2026-06-23: Lizenz ungeklärt).
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

_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"
_DL_DE_ZERO_URL = "https://www.govdata.de/dl-de/zero-2-0"
_CC_BY_URL = "https://creativecommons.org/licenses/by/4.0/"


def _counts_from_stations(raw: dict, granularity: str = "hour") -> list[dict]:
    """Baut die kanonische ``counts``-Liste aus rohen Stations-dicts (je Quelle)."""
    counts: list[dict] = []
    for station in raw.get("stations", []):
        if not isinstance(station, dict):
            continue
        counts.append(
            {
                "station": station.get("station"),
                "station_id": station.get("station_id"),
                "lat": station.get("lat"),
                "lon": station.get("lon"),
                "value": station.get("value"),
                "vehicle_type": "bicycle",
                "granularity": granularity,
                "period": station.get("period"),
                "directions": None,
            }
        )
    return counts


def build_bike_count_record(
    slug: str,
    counts: list[dict],
    observed_at: datetime | None,
    *,
    retrieved_at: datetime,
    ags: str | None,
    wikidata_qid: str | None,
    source: SourceId,
    license_id: LicenseId,
    license_tier: LicenseTier,
    attribution_text: str,
    license_url: str,
) -> CanonicalRecord:
    """Baut den kanonischen ``CountStationPayload``-Record einer bike-counts-Quelle."""
    return CanonicalRecord(
        city_slug=slug,
        geo=None,
        observed_at=observed_at,
        retrieved_at=retrieved_at,
        source=source,
        license_id=license_id,
        license_tier=license_tier,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(text=attribution_text, license_url=license_url),
        payload=CountStationPayload(counts=counts),
    )


def _parse_iso(value: object) -> datetime | None:
    """Parst einen ISO-Zeitstempel defensiv zu UTC-datetime (sonst None)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def map_leipzig_radzaehl(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe Leipziger Rad-Stundenzählwerte auf einen ``CanonicalRecord`` ab.

    Je Station ein Zähl-dict (``value`` = jüngster Stundenwert, ``granularity``
    "hour", ``period`` = ISO-Stundenzeitstempel). ``observed_at`` = jüngster
    ``phenomenontime`` (``as_of``). Lizenz DL-DE/BY 2.0, Tier A, "Stadt Leipzig".
    """
    return build_bike_count_record(
        raw["slug"],
        _counts_from_stations(raw),
        _parse_iso(raw.get("as_of")),
        retrieved_at=retrieved_at,
        ags=ags,
        wikidata_qid=wikidata_qid,
        source=SourceId.LEIPZIG_RADZAEHL,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        attribution_text="Stadt Leipzig",
        license_url=_DL_DE_BY_URL,
    )


def map_hamburg_radzaehl(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet den Hamburger Rad-Stundenwert (Dauerzählstelle Gurlittinsel) ab.

    Eine Station, ``value`` = jüngster Stundenwert, ``granularity`` "hour",
    ``period`` = ISO-Stundenzeitstempel. Lizenz DL-DE/BY 2.0, Tier A,
    "Freie und Hansestadt Hamburg, Behörde für Verkehr und Mobilitätswende".
    """
    return build_bike_count_record(
        raw["slug"],
        _counts_from_stations(raw),
        _parse_iso(raw.get("as_of")),
        retrieved_at=retrieved_at,
        ags=ags,
        wikidata_qid=wikidata_qid,
        source=SourceId.HAMBURG_RADZAEHL,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        attribution_text=(
            "Freie und Hansestadt Hamburg, Behörde für Verkehr und Mobilitätswende"
        ),
        license_url=_DL_DE_BY_URL,
    )


def map_berlin_radzaehl(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet die jüngsten Berliner Rad-Stundenwerte ab (DL-DE/Zero 2.0, Tier A).

    Je Station ``value`` = jüngster Stundenwert, ``granularity`` "hour". Lizenz
    Datenlizenz Deutschland Zero 2.0 (keine Namensnennungspflicht), Tier A,
    Attribution "Senatsverwaltung für Mobilität, Verkehr, Klimaschutz und Umwelt
    Berlin".
    """
    return build_bike_count_record(
        raw["slug"],
        _counts_from_stations(raw),
        _parse_iso(raw.get("as_of")),
        retrieved_at=retrieved_at,
        ags=ags,
        wikidata_qid=wikidata_qid,
        source=SourceId.BERLIN_RADZAEHL,
        license_id=LicenseId.DL_DE_ZERO_2_0,
        license_tier=LicenseTier.A,
        attribution_text=(
            "Senatsverwaltung für Mobilität, Verkehr, Klimaschutz und Umwelt Berlin"
        ),
        license_url=_DL_DE_ZERO_URL,
    )


def map_stuttgart_radzaehl(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet die Stuttgarter Rad-Jahreswerte ab (CC BY 4.0, Tier A).

    Je Station ``value`` = jüngster Jahres-Summenwert, ``granularity`` "year",
    ``period`` = Jahr; KEINE Koordinaten (Quelle liefert keine). ``observed_at``
    None (Jahreswert ohne Stundenzeitstempel). Attribution "Landeshauptstadt
    Stuttgart" (CC BY verlangt Namensnennung).
    """
    return build_bike_count_record(
        raw["slug"],
        _counts_from_stations(raw, "year"),
        None,
        retrieved_at=retrieved_at,
        ags=ags,
        wikidata_qid=wikidata_qid,
        source=SourceId.STUTTGART_RADZAEHL,
        license_id=LicenseId.CC_BY_4_0,
        license_tier=LicenseTier.A,
        attribution_text="Landeshauptstadt Stuttgart",
        license_url=_CC_BY_URL,
    )
