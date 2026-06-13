"""Reine Parken-/Zaehldaten-Mobilithek-Mapper (LIVE-09/10, Tier A, Phase 20).

Uebersetzt die rohen Adapter-dicts aus ``adapters/mobilithek_datex2.py``
deterministisch in einen ``CanonicalRecord``:
- ``map_dortmund_parking``: Dortmund Parkleitsystem dynamisch
  (ParkingStatusPublication, ``facilities``) -> ``ParkingPayload``,
  SourceId.DORTMUND_PARKING (LIVE-09, schliesst die DATA-09-Belegungsluecke Parken).
- ``map_kiel_counts``: Kiel MIV-/Radzaehlstellen (MeasuredDataPublication,
  ``measurements``) -> ``CountStationPayload`` (``counts``),
  SourceId.KIEL_ZAEHLSTELLEN (LIVE-10).

Schablone ist ``mappers/mobilithek_koeln.py`` (exakt, Plan 04): rein (kein HTTP,
kein XML-Parse, keine Systemuhr), ``retrieved_at`` keyword-only injiziert
(deterministisch). Beide Quellen stehen unter der Datenlizenz Deutschland
Namensnennung 2.0: ``license_id=DL_DE_BY_2_0``, ``license_tier=A`` (verifiziert,
T-20-TIER: KEIN pauschales Tier-A ueber alle Quellen, nur diese DL-DE/BY-Feeds).
Attribution "Stadt Dortmund" bzw. "Landeshauptstadt Kiel".

Reine Live-Daten -> ``geo=None`` (der dynamische Feed traegt nur ID-Referenzen);
``observed_at`` aus der DATEX-II ``publicationTime`` (``as_of``) falls vorhanden,
sonst ``None`` (ehrlich, keine Systemuhr).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    CountStationPayload,
    LicenseId,
    LicenseTier,
    ParkingPayload,
    SourceId,
)

_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"
_DORTMUND_ATTRIBUTION = "Stadt Dortmund"
_KIEL_ATTRIBUTION = "Landeshauptstadt Kiel"


def _parse_as_of(raw: dict) -> datetime | None:
    """Liest ``as_of`` (DATEX-II publicationTime) als aware ``datetime`` oder None.

    Rein (keine Systemuhr). Ein nicht-parsebarer/fehlender Wert -> ``None``
    (ehrlich, kein Fehler).
    """
    text = raw.get("as_of")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None


def map_dortmund_parking(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet die Dortmund-Parkbelegung (parking) auf einen ``CanonicalRecord`` ab.

    Die ``facilities`` (je Parkhaus facility_id + free/capacity/occupancy,
    LIVE-09) wandern in den ``ParkingPayload``. ``observed_at`` aus der DATEX-II
    ``publicationTime`` (``as_of``) falls vorhanden. ``retrieved_at`` injiziert
    (keine Systemuhr im Mapper). Tier A, DL-DE/BY 2.0, Attribution
    "Stadt Dortmund". Schliesst die DATA-09-Echtzeit-Parkbelegungsluecke.
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=_parse_as_of(raw),
        retrieved_at=retrieved_at,
        source=SourceId.DORTMUND_PARKING,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_DORTMUND_ATTRIBUTION,
            license_url=_DL_DE_BY_URL,
        ),
        payload=ParkingPayload(
            facilities=raw.get("facilities", []),
        ),
    )


def map_kiel_counts(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet die Kiel-Zaehldaten (measured) auf einen ``CanonicalRecord`` ab.

    Die ``measurements`` (je Zaehlstelle station_id + flow/speed, LIVE-10) werden
    als ``counts`` in den ``CountStationPayload`` interpretiert. ``observed_at``
    aus der DATEX-II ``publicationTime`` (``as_of``) falls vorhanden.
    ``retrieved_at`` injiziert (keine Systemuhr im Mapper). Tier A, DL-DE/BY 2.0,
    Attribution "Landeshauptstadt Kiel".
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=_parse_as_of(raw),
        retrieved_at=retrieved_at,
        source=SourceId.KIEL_ZAEHLSTELLEN,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_KIEL_ATTRIBUTION,
            license_url=_DL_DE_BY_URL,
        ),
        payload=CountStationPayload(
            counts=raw.get("measurements", []),
        ),
    )
