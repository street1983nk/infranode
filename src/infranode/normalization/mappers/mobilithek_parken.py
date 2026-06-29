"""Reine Parken-/Zaehldaten-Mobilithek-Mapper (LIVE-09/10, Tier A, Phase 20).

Übersetzt die rohen Adapter-dicts aus ``adapters/mobilithek_datex2.py``
deterministisch in einen ``CanonicalRecord``:
- ``map_dortmund_parking``: Dortmund Parkleitsystem dynamisch
  (ParkingStatusPublication, ``facilities``) -> ``ParkingPayload``,
  SourceId.DORTMUND_PARKING (LIVE-09, schließt die DATA-09-Belegungslücke Parken).
- ``map_kiel_counts``: Kiel MIV-/Radzaehlstellen (MeasuredDataPublication,
  ``measurements``) -> ``CountStationPayload`` (``counts``),
  SourceId.KIEL_ZAEHLSTELLEN (LIVE-10).

Schablone ist ``mappers/mobilithek_koeln.py`` (exakt, Plan 04): rein (kein HTTP,
kein XML-Parse, keine Systemuhr), ``retrieved_at`` keyword-only injiziert
(deterministisch). Beide Quellen stehen unter der Datenlizenz Deutschland
Namensnennung 2.0: ``license_id=DL_DE_BY_2_0``, ``license_tier=A`` (verifiziert,
T-20-TIER: KEIN pauschales Tier-A über alle Quellen, nur diese DL-DE/BY-Feeds).
Attribution "Stadt Dortmund" bzw. "Landeshauptstadt Kiel".

Reine Live-Daten -> ``geo=None`` (der dynamische Feed trägt nur ID-Referenzen);
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
_FRANKFURT_ATTRIBUTION = "Stadt Frankfurt am Main"
_WUPPERTAL_ATTRIBUTION = "Stadt Wuppertal"
# Dortmund-Parken kommt seit 2026-06-13 aus dem direkten, keylosen Opendatasoft-
# Feed der Stadt (adapters/dortmund_parking, statt Mobilithek). Dieser Datensatz
# steht unter Datenlizenz Deutschland Zero 2.0 (am Datensatz-Meta verifiziert) ->
# noch freier als DL-DE/BY, weiterhin Tier A. Kiel bleibt DL-DE/BY (Mobilithek).
_DL_DE_ZERO_URL = "https://www.govdata.de/dl-de/zero-2-0"
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
    LIVE-09) wandern in den ``ParkingPayload``. ``observed_at`` aus dem jüngsten
    ``zeitstempel`` (``as_of``) falls vorhanden. ``retrieved_at`` injiziert
    (keine Systemuhr im Mapper). Tier A, DL-DE Zero 2.0 (direkter keyloser
    Opendatasoft-Feed der Stadt Dortmund), Attribution "Stadt Dortmund".
    Schließt die DATA-09-Echtzeit-Parkbelegungslücke.
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=_parse_as_of(raw),
        retrieved_at=retrieved_at,
        source=SourceId.DORTMUND_PARKING,
        license_id=LicenseId.DL_DE_ZERO_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_DORTMUND_ATTRIBUTION,
            license_url=_DL_DE_ZERO_URL,
        ),
        payload=ParkingPayload(
            facilities=raw.get("facilities", []),
        ),
    )


def map_frankfurt_parking(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet die Frankfurt-Parkdaten (parking) auf einen ``CanonicalRecord`` ab.

    Die ``facilities`` (je Parkplatz facility_id + free/occupancy/
    occupancy_graded/observed_at aus dem dynamischen Feed, angereichert um
    name/lat/lon/capacity aus dem statischen Pendant, DATEX II V3 gejoint im
    Adapter ``mobilithek_datex3``) wandern in den ``ParkingPayload``.
    ``observed_at`` aus der DATEX-II ``publicationTime`` (``as_of``) des
    dynamischen Feeds falls vorhanden. ``retrieved_at`` injiziert (keine
    Systemuhr im Mapper). Tier A, DL-DE/BY 2.0 (opendata.hessen.de verifiziert
    2026-06-22, license_id dl-by-de/2.0), Attribution "Stadt Frankfurt am Main".
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=_parse_as_of(raw),
        retrieved_at=retrieved_at,
        source=SourceId.FRANKFURT_PARKING,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_FRANKFURT_ATTRIBUTION,
            license_url=_DL_DE_BY_URL,
        ),
        payload=ParkingPayload(
            facilities=raw.get("facilities", []),
        ),
    )


def map_wuppertal_parking(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet die Wuppertal-Parkdaten (parking) auf einen ``CanonicalRecord`` ab.

    Die ``facilities`` (je Parkplatz facility_id + free/capacity/occupied/
    occupancy/status/trend/observed_at aus dem dynamischen Feed, angereichert um
    name/lat/lon aus dem statischen Pendant, DATEX II V2 ParkingFacility-Profil
    gejoint im Adapter ``mobilithek_datex2``) wandern in den ``ParkingPayload``.
    ``observed_at`` aus der DATEX-II ``publicationTime`` (``as_of``) des
    dynamischen Feeds falls vorhanden. ``retrieved_at`` injiziert (keine Systemuhr
    im Mapper). Tier A, DL-DE/Zero 2.0 (mobilitaetsdaten.nrw / Mobilithek-Abo-
    Lizenz dl-zero-de/2.0 verifiziert 2026-06-22), Attribution "Stadt Wuppertal".
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=_parse_as_of(raw),
        retrieved_at=retrieved_at,
        source=SourceId.WUPPERTAL_PARKING,
        license_id=LicenseId.DL_DE_ZERO_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_WUPPERTAL_ATTRIBUTION,
            license_url=_DL_DE_ZERO_URL,
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
    """Bildet die Kiel-Zähldaten (measured) auf einen ``CanonicalRecord`` ab.

    Die ``measurements`` (je Zählstelle station_id + flow/speed, LIVE-10) werden
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
