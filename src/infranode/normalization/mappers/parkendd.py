"""Reiner ParkenDD-Mapper map_parkendd (DATA-40, Live-Parken, Tier A je Stadt).

Uebersetzt das rohe Adapter-dict (``slug``/``facilities``/``as_of``) deterministisch
in einen ``CanonicalRecord`` mit ``ParkingPayload``. Rein: kein HTTP, keine
Systemuhr (``retrieved_at`` keyword-only injiziert).

LIZENZ (B-1, GOV-01): ParkenDD aggregiert heterogen lizenzierte Stadt-Quellen ohne
einheitliche Lizenz. Die Lizenz wird daher PRO STADT am echten Ursprung verifiziert
(``_PARKENDD_LICENSE``) und mit korrektem Tier getragen (CC0/DL-DE-Zero/DL-DE-BY/
CC-BY, je Stadt; alle Tier A). Es werden NUR Staedte mit offener Standardlizenz
ausgeliefert (Owner-Entscheidung 2026-06-23: keine Tier-B/C-/NC-Auslieferung); die
uebrigen sind aus ``PARKENDD_CITIES`` entfernt (not_covered). Reine Live-Daten.
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

_PARKENDD_URL = "https://github.com/ParkenDD"

# Kanonische Lizenz-Deed-URL je LicenseId (Attribution.license_url). Fuer nicht
# gelistete (UNKNOWN) Lizenzen bleibt die ParkenDD-Projektseite die Quellangabe.
_LICENSE_DEED: dict[LicenseId, str] = {
    LicenseId.DL_DE_BY_2_0: "https://www.govdata.de/dl-de/by-2-0",
    LicenseId.DL_DE_ZERO_2_0: "https://www.govdata.de/dl-de/zero-2-0",
    LicenseId.CC0: "https://creativecommons.org/publicdomain/zero/1.0/",
    LicenseId.CC_BY_4_0: "https://creativecommons.org/licenses/by/4.0/",
}

# Per-Stadt-Lizenz der Parkdaten-URSPRUNGSQUELLE (NICHT ParkenDD selbst): ParkenDD
# aggregiert heterogen lizenzierte Stadt-Quellen, daher wird die Lizenz je Stadt an
# der echten Quelle verifiziert und hier getragen (Owner-Entscheidung 2026-06-23:
# "Ursprung je Stadt verifizieren"). Eintrag: slug -> (LicenseId, LicenseTier,
# attribution_text). Lizenz-Recherche je Ursprung 2026-06-23: genau diese 13
# ParkenDD-Staedte fuehren am Ursprung eine OFFENE Standardlizenz und werden
# ausgeliefert (deckungsgleich mit ``adapters.parkendd.PARKENDD_CITIES``); die
# uebrigen 9 wurden entfernt (bonn CC BY-NC, hanau/ingolstadt/nuernberg proprietaer,
# luebeck/magdeburg/mannheim/regensburg/wiesbaden ohne auffindbare Lizenz). Der
# ``_DEFAULT_LICENSE`` (UNKNOWN/C) ist nur noch ein Fail-safe (keine ausgelieferte
# Stadt faellt darauf).
_PARKENDD_LICENSE: dict[str, tuple[LicenseId, LicenseTier, str]] = {
    "aachen": (LicenseId.CC0, LicenseTier.A, "APAG - Aachener Parkhaus GmbH"),
    "dortmund": (LicenseId.DL_DE_ZERO_2_0, LicenseTier.A, "Stadt Dortmund"),
    "dresden": (LicenseId.DL_DE_BY_2_0, LicenseTier.A, "Landeshauptstadt Dresden"),
    "freiburg-im-breisgau": (LicenseId.DL_DE_BY_2_0, LicenseTier.A, "Stadt Freiburg"),
    "hamburg": (
        LicenseId.DL_DE_BY_2_0,
        LicenseTier.A,
        "Freie und Hansestadt Hamburg, Behörde für Verkehr und Mobilitätswende",
    ),
    "heidelberg": (
        LicenseId.CC_BY_4_0,
        LicenseTier.A,
        "Stadt Heidelberg, Amt für Mobilität",
    ),
    # Namensnennung wortgenau "Stadtwerke Heilbronn" (NICHT "Stadt Heilbronn").
    "heilbronn": (LicenseId.DL_DE_BY_2_0, LicenseTier.A, "Stadtwerke Heilbronn"),
    "kaiserslautern": (LicenseId.CC0, LicenseTier.A, "Stadtverwaltung Kaiserslautern"),
    "karlsruhe": (LicenseId.CC_BY_4_0, LicenseTier.A, "Stadt Karlsruhe"),
    "koeln": (LicenseId.DL_DE_ZERO_2_0, LicenseTier.A, "Stadt Köln"),
    "muenster": (LicenseId.DL_DE_BY_2_0, LicenseTier.A, "Stadt Münster"),
    "oldenburg": (LicenseId.DL_DE_BY_2_0, LicenseTier.A, "Stadt Oldenburg (Oldb)"),
    "ulm": (LicenseId.CC0, LicenseTier.A, "Stadt Ulm"),
}

# Fail-safe fuer einen nicht gelisteten Slug (sollte nie ausgeliefert werden, da
# PARKENDD_CITIES == Schluessel dieser Map): ehrlich UNKNOWN/Tier C.
_DEFAULT_LICENSE: tuple[LicenseId, LicenseTier, str] = (
    LicenseId.UNKNOWN,
    LicenseTier.C,
    "ParkenDD",
)


def _parse_as_of(value: object) -> datetime | None:
    """Parst den ParkenDD-``last_updated``-String defensiv zu datetime (sonst None)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def map_parkendd(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe ParkenDD-Parkdaten auf einen ``CanonicalRecord`` (Tier C) ab.

    Die ``facilities`` (Parkhaeuser mit frei/gesamt/Zustand) wandern unveraendert
    in den ``ParkingPayload``. ``observed_at`` kommt aus dem ParkenDD-Datenstand
    (``as_of``), ``geo=None`` (Koordinaten je Facility im Payload). ``license_id``/
    ``license_tier``/Attribution kommen PRO STADT aus ``_PARKENDD_LICENSE`` (am
    Ursprung verifiziert); nicht gelistete Staedte fallen ehrlich auf UNKNOWN/Tier C.
    """
    slug = raw["slug"]
    license_id, license_tier, attribution_text = _PARKENDD_LICENSE.get(
        slug, _DEFAULT_LICENSE
    )
    license_url = _LICENSE_DEED.get(license_id, _PARKENDD_URL)
    return CanonicalRecord(
        city_slug=slug,
        geo=None,
        observed_at=_parse_as_of(raw.get("as_of")),
        retrieved_at=retrieved_at,
        source=SourceId.PARKENDD,
        license_id=license_id,
        license_tier=license_tier,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=attribution_text,
            license_url=license_url,
        ),
        payload=ParkingPayload(
            facilities=raw.get("facilities", []),
        ),
    )
