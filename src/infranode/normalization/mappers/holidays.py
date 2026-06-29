"""Feiertage/Schulferien-Seed-Reader + reiner Mapper map_holidays (DATA-21).

Liest die eingebetteten, committeten Seeds (``data/seeds/feiertage_<year>.json``
und ``data/seeds/schulferien_<year>.json``) via stdlib ``json`` je Bundesland
(``entry.state``-Kürzel) und bildet sie deterministisch auf einen
``CanonicalRecord`` mit ``HolidayPayload`` (kind="holiday") ab.

KRITISCH (Gray-Area-Entscheidung, GOV-02/03): Feiertage/Schulferien sind
GEMEINFREIE Fakten (``license_id=CC0``). Die Attribution weist die
gemeinfreie Herkunft (KMK-validiert) aus. Die Seeds sind statisch im Repo
(kein DB-Schutzrecht).

KRITISCH (T-08-DEP/T-08-SC): KEINE Laufzeit-Fremd-API, KEINE neue Dependency.
Der Reader nutzt ausschließlich stdlib ``json``; ``load_holidays`` ist tolerant
(fehlende Datei/fehlendes Bundesland -> leere Listen, kein Crash, kein 5xx).

Der Mapper ist rein: kein HTTP, kein Logging, kein ``datetime.now()``. Der
``retrieved_at``-Zeitstempel wird keyword-only injiziert, damit Tests
deterministisch bleiben.
"""

from __future__ import annotations

import json
from datetime import datetime

from infranode.infra.seeds import seeds_dir
from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    HolidayPayload,
    LicenseId,
    LicenseTier,
    SourceId,
)

# CC0 / gemeinfreie Fakten. Die Lizenz-URL dient nur der Attribution; die Daten
# sind ausdrücklich NICHT permissiv lizenziert (siehe Modul-Docstring).
_CC0_URL = "https://creativecommons.org/publicdomain/zero/1.0/"

# Wortgenaue Attribution: gemeinfreie, KMK-validierte Fakten (CC0).
_ATTRIBUTION_TEXT = "Feiertage/Schulferien (gemeinfreie Fakten, gegen KMK validiert)"


def _read_seed(filename: str, state: str) -> list[dict]:
    """Liest eine Seed-Datei via stdlib json und gibt die Einträge für ``state``.

    Tolerant by design (T-08-DEP, no_data-Pfad): fehlende Datei oder fehlendes
    Bundesland -> leere Liste (kein Crash, KEIN Fremd-API-Call). ``_meta``-Keys
    werden nie als Bundesland interpretiert (der Lookup ist exakt ``state``).

    Der Seed-Pfad wird lazy via ``seeds_dir()`` aufgelöst (respektiert
    ``INFRANODE_SEEDS_DIR``, Live-Report M1): nie auf Import-Zeit einfrieren,
    sonst greift im Prod-Container der Volume-Override nicht.
    """
    path = seeds_dir() / filename
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get(state)
    return entries if isinstance(entries, list) else []


def load_holidays(state: str, year: int) -> dict:
    """Liest Feiertage + Schulferien je Bundesland aus den eingebetteten Seeds.

    Liest ``data/seeds/feiertage_<year>.json`` und
    ``data/seeds/schulferien_<year>.json`` via stdlib ``json`` und extrahiert die
    Einträge für das Bundesland-Kürzel ``state`` (z. B. "BY"). Unbekanntes
    Bundesland oder fehlendes Jahr -> leere Listen (kein Crash, KEIN Fremd-API).

    Returns:
        dict mit ``holidays`` und ``school_holidays`` (je list[dict]).
    """
    return {
        "holidays": _read_seed(f"feiertage_{year}.json", state),
        "school_holidays": _read_seed(f"schulferien_{year}.json", state),
    }


def map_holidays(
    state: str,
    year: int,
    holidays: list[dict],
    school_holidays: list[dict],
    *,
    slug: str,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet Feiertage/Schulferien auf einen ``CanonicalRecord`` ab (rein).

    Der ``retrieved_at``-Zeitstempel wird injiziert (kein ``datetime.now()`` im
    Mapper), damit das Ergebnis deterministisch bleibt. Die Join-Keys
    ``ags``/``wikidata_qid`` werden aus dem Register durchgereicht (Default
    ``None``). ``geo`` bleibt ``None`` (Stadtebene, keine Punkt-Geometrie);
    ``observed_at`` bleibt ``None`` (statische Jahres-Fakten, kein Mess-Zeitstempel).

    KRITISCH (Gray-Area, GOV-02/03): ``source=FEIERTAGE``, ``license_id=CC0``
    (gemeinfreie Fakten), ``license_tier=A``. Die Attribution weist die
    gemeinfreie, KMK-validierte Herkunft aus. Leere Listen sind KEIN Fehler.
    """
    return CanonicalRecord(
        city_slug=slug,
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.FEIERTAGE,
        license_id=LicenseId.CC0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_ATTRIBUTION_TEXT,
            license_url=_CC0_URL,
        ),
        payload=HolidayPayload(
            state=state,
            year=year,
            holidays=holidays,
            school_holidays=school_holidays,
        ),
    )
