"""Dach-Solarkataster-Seed-Reader + reiner Mapper map_solar_roofs (DATA-39).

Liest den committeten Seed ``data/seeds/solar_cadastre_nrw.json`` (erzeugt von
``scripts/build_solar_cadastre_seed.py`` aus dem amtlichen NRW-Gemeinde-Aggregat,
Solarkataster NRW / MaStR / LANUK / Geobasis NRW, DL-DE/Zero 2.0) via stdlib
``json`` je Gemeinde (AGS) und bildet ihn deterministisch auf einen
``CanonicalRecord`` mit ``SolarRoofsPayload`` (kind="solar_roofs") ab.

KRITISCH (T-08-DEP): KEINE Laufzeit-Fremd-API, KEINE openpyxl-Runtime-Dep. Der
Reader nutzt ausschliesslich stdlib ``json`` und ist tolerant (fehlende Datei /
fehlender AGS -> ``None`` -> no_data-Pfad, kein Crash, kein 5xx). Analog
Feiertage-Seed.

Der Mapper ist rein: kein HTTP, kein Logging, kein ``datetime.now()`` (der
``retrieved_at``-Zeitstempel wird keyword-only injiziert). PVGIS-unabhaengig: dies
ist das Dach-Solarkataster (Pro-Stadt-Potenzial), nicht die Einstrahlung je kWp
(das ist die separate ``solar``-Quelle, PVGIS).
"""

from __future__ import annotations

import json
from datetime import datetime

from infranode.infra.seeds import seeds_dir
from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    SolarRoofsPayload,
    SourceId,
)

_SEED_FILE = "solar_cadastre_nrw.json"
# Fallback (NRW), falls ein Seed-Eintrag ausnahmsweise kein states-Meta traegt.
_FALLBACK_LICENSE_ID = "dl_de_zero_2_0"
_FALLBACK_LICENSE_URL = "https://www.govdata.de/dl-de/zero-2-0"
_FALLBACK_ATTRIBUTION = "Land NRW / GeoBasis NRW / LANUK (MaStR), Solarkataster NRW"


def load_solar_roofs(ags: str | None) -> dict | None:
    """Liest den Dach-Solarkataster-Eintrag einer Gemeinde aus dem Seed.

    Tolerant by design (T-08-DEP, no_data-Pfad): fehlende Seed-Datei, fehlender
    ``ags`` oder unbekannte Gemeinde -> ``None`` (kein Crash, KEIN Fremd-API).
    Der Bezugszeitraum (``reference_date`` aus ``_meta``) wird in das zurueck-
    gegebene dict gehoben. Der Seed-Pfad wird lazy via ``seeds_dir()`` aufgeloest
    (respektiert ``INFRANODE_SEEDS_DIR``, Prod-Volume-Override).
    """
    if not ags:
        return None
    path = seeds_dir() / _SEED_FILE
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    entry = (data.get("cities") or {}).get(ags)
    if not isinstance(entry, dict):
        return None
    # Lizenz/Attribution/Stichtag stehen je Bundesland im states-Block (foederiert,
    # GOV-04): NRW = DL-DE/Zero 2.0, Bayern = CC BY 4.0. Ins Entry-dict heben, damit
    # der reine Mapper die Pro-Record-Lizenz daraus ableitet.
    state_meta = (data.get("states") or {}).get(entry.get("state")) or {}
    return {**state_meta, **entry}


def map_solar_roofs(
    raw: dict,
    *,
    slug: str,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet einen Dach-Solarkataster-Seed-Eintrag auf einen ``CanonicalRecord`` ab.

    ``retrieved_at`` wird injiziert (kein ``datetime.now()`` im Mapper). ``geo``
    bleibt ``None`` (Stadtebene), ``observed_at`` bleibt ``None`` (Stichtags-/
    Stammdaten, kein Mess-Zeitstempel; ``reference_date`` traegt den Stand im
    Payload). ``exploitation_pct`` = installed_kwp/potential_kwp*100 wird hier
    deterministisch abgeleitet (Ausschoepfungsgrad). Lizenz DL-DE/Zero 2.0 = Tier A;
    Attribution ``modified=True`` (Aggregation + Einheiten-Umrechnung kWh->MWh +
    abgeleiteter Ausschoepfungsgrad).
    """
    potential_kwp = raw.get("potential_kwp")
    installed_kwp = raw.get("installed_kwp")
    # Ausbaugrad: aus dem Seed (Bayern liefert ppvd_ant) oder abgeleitet (NRW).
    exploitation_pct = raw.get("exploitation_pct")
    if (
        exploitation_pct is None
        and isinstance(potential_kwp, int | float)
        and potential_kwp > 0
        and isinstance(installed_kwp, int | float)
    ):
        exploitation_pct = round(installed_kwp / potential_kwp * 100, 1)

    return CanonicalRecord(
        city_slug=slug,
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.SOLAR_CADASTRE,
        license_id=LicenseId(raw.get("license_id") or _FALLBACK_LICENSE_ID),
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=raw.get("attribution") or _FALLBACK_ATTRIBUTION,
            license_url=raw.get("license_url") or _FALLBACK_LICENSE_URL,
            modified=True,
        ),
        payload=SolarRoofsPayload(
            potential_kwp=potential_kwp,
            potential_yield_mwh=raw.get("potential_yield_mwh"),
            installed_kwp=installed_kwp,
            installed_yield_mwh=raw.get("installed_yield_mwh"),
            exploitation_pct=exploitation_pct,
            potential_by_category=raw.get("potential_by_category") or {},
            reference_date=raw.get("reference_date"),
        ),
    )
