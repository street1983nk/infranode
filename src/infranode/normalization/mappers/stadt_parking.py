"""Reine Stadt-Parkmapper (PARK-06) für Münster/Aachen/Oldenburg/Hamburg.

Übersetzt das rohe Adapter-dict (``slug``/``facilities``/``as_of``) je Stadt
deterministisch in einen ``CanonicalRecord`` mit ``ParkingPayload``. Rein: kein
HTTP, keine Systemuhr (``retrieved_at`` keyword-only injiziert). Vorlage ist
``mappers/parkendd.map_parkendd`` bzw. ``mappers/mobidata_parkapi``.

LIZENZ (PARK-06, T-25-10): Jede Stadt trägt ihre am Ursprung verifizierte offene
Lizenz, wortgenau identisch zu ``DATA-LICENSES.md`` und ``registry/source_specs``
(T-11-SRC-DRIFT):
- Münster: DL-DE/BY 2.0, "Stadt Münster"
- Aachen (regress-kritisch): UNKNOWN / Tier C (Owner-Entscheid 2026-07-19, Direktbezug
  APAG über NRW.Mobidrom nicht offen deklariert -> live-only, NICHT public bis geklärt)
- Oldenburg: UNKNOWN / Tier C (Owner-Entscheid 2026-10-20, Open-Data-Datensatz nach
  Portal-Relaunch verschwunden, Bezug über oldenburg-service.de/pls.php -> live-only,
  NICHT public bis zur Lizenzklärung bei der Stadt Oldenburg)

mannheim/koeln sind hier bewusst NICHT enthalten (nicht Teil dieses Slices).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    ParkingPayload,
    SourceId,
)

# Kanonische Lizenz-Deed-URL je LicenseId (Attribution.license_url).
_LICENSE_DEED: dict[LicenseId, str] = {
    LicenseId.DL_DE_BY_2_0: "https://www.govdata.de/dl-de/by-2-0",
    LicenseId.DL_DE_ZERO_2_0: "https://www.govdata.de/dl-de/zero-2-0",
    LicenseId.CC0: "https://creativecommons.org/publicdomain/zero/1.0/",
    LicenseId.CC_BY_4_0: "https://creativecommons.org/licenses/by/4.0/",
}

# Fallback-Quellangabe für UNKNOWN-lizenzierte Direktquellen (Tier C, live-only):
# die NRW.Mobidrom-Plattform, über die der Aachener APAG-Feed bezogen wird.
_UNKNOWN_URL = "https://www.mobilitaetsdaten.nrw"
# Quellangabe für Oldenburg (UNKNOWN, Tier C): die städtische Parkleitsystem-Seite.
_OLDENBURG_SOURCE_URL = "https://oldenburg-service.de/pls.php"


def _parse_as_of(value: object) -> datetime | None:
    """Parst den Stadt-OpenData-``as_of``-String defensiv zu datetime (sonst None)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _build(
    raw: dict,
    *,
    source: SourceId,
    license_id: LicenseId,
    license_tier: LicenseTier,
    attribution_text: str,
    retrieved_at: datetime,
    ags: str | None,
    wikidata_qid: str | None,
    unknown_url: str = _UNKNOWN_URL,
) -> CanonicalRecord:
    """Gemeinsamer reiner Aufbau des ``CanonicalRecord`` (keine Systemuhr, geo=None).

    ``unknown_url`` ist die Quellangabe, falls ``license_id`` keine Deed-URL hat.
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=_parse_as_of(raw.get("as_of")),
        retrieved_at=retrieved_at,
        source=source,
        license_id=license_id,
        license_tier=license_tier,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=attribution_text,
            license_url=_LICENSE_DEED.get(license_id, unknown_url),
        ),
        payload=ParkingPayload(
            facilities=raw.get("facilities", []),
        ),
    )


def map_muenster_parking(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe Münster-Parkdaten auf einen ``CanonicalRecord`` (Tier A) ab."""
    return _build(
        raw,
        source=SourceId.MUENSTER_PARKING,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        attribution_text="Stadt Münster",
        retrieved_at=retrieved_at,
        ags=ags,
        wikidata_qid=wikidata_qid,
    )


def map_aachen_parking(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe Aachen-Parkdaten auf einen ``CanonicalRecord`` (Tier C) ab.

    Regress-kritisch (heute LIVE via ParkenDD). Direktbezug der APAG-Parkdaten über
    den NRW.Mobidrom-Systemadapter-Export. LIZENZ (Owner-Entscheid 2026-07-19):
    NICHT offen deklariert (CKAN ``isopen=false``; Mobidrom-Nutzungsbedingungen
    sehen Registrierung vor) -> konservativ ``LicenseId.UNKNOWN`` / ``LicenseTier.C``
    (live-only, NICHT public) bis zur schriftlichen Lizenzklärung bei
    NRW.Mobidrom/APAG. Attribution "APAG - Aachener Parkhaus GmbH, bereitgestellt
    über NRW.Mobidrom (mobilitaetsdaten.nrw)".
    """
    return _build(
        raw,
        source=SourceId.AACHEN_PARKING,
        license_id=LicenseId.UNKNOWN,
        license_tier=LicenseTier.C,
        attribution_text=(
            "APAG - Aachener Parkhaus GmbH, bereitgestellt über "
            "NRW.Mobidrom (mobilitaetsdaten.nrw)"
        ),
        retrieved_at=retrieved_at,
        ags=ags,
        wikidata_qid=wikidata_qid,
    )


def map_hamburg_parking(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe Hamburg-Parkdaten auf einen ``CanonicalRecord`` (Tier A) ab.

    Direktbezug aus dem keylosen Hamburg-Urban-Platform-WFS
    (``geodienste.hamburg.de/wfs_parkhaeuser``, umgeht den api.hamburg.de-Box-IP-
    Block). Lizenz dl-de/by-2.0 = Tier A, Herausgeber "Freie und Hansestadt Hamburg,
    Behörde für Verkehr und Mobilitätswende". Ersetzt das eingefrorene
    ParkenDD-Hamburg durch eine echte Live-Quelle.
    """
    return _build(
        raw,
        source=SourceId.HAMBURG_PARKING,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        attribution_text=(
            "Freie und Hansestadt Hamburg, Behörde für Verkehr und Mobilitätswende"
        ),
        retrieved_at=retrieved_at,
        ags=ags,
        wikidata_qid=wikidata_qid,
    )


def map_oldenburg_parking(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe Oldenburg-Parkdaten auf einen ``CanonicalRecord`` (Tier C) ab.

    LIZENZ (Owner-Entscheid 2026-10-20): Der DL-DE/BY-2.0-Datensatz ist nach dem
    Relaunch von opendata.oldenburg.de verschwunden; Bezug jetzt über die städtische
    Parkleitsystem-Seite ``oldenburg-service.de/pls.php`` ohne erkennbare Lizenz ->
    konservativ ``LicenseId.UNKNOWN`` / ``LicenseTier.C`` (live-only, NICHT public)
    bis zur Lizenzklärung bei der Stadt Oldenburg. Muster ``map_aachen_parking``.
    """
    return _build(
        raw,
        source=SourceId.OLDENBURG_PARKING,
        license_id=LicenseId.UNKNOWN,
        license_tier=LicenseTier.C,
        attribution_text="Stadt Oldenburg (Oldb)",
        retrieved_at=retrieved_at,
        ags=ags,
        wikidata_qid=wikidata_qid,
        unknown_url=_OLDENBURG_SOURCE_URL,
    )
