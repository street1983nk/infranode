"""Reiner GENESIS-Demografie-Mapper map_demographics (DATA-17, GOV-02/03).

Uebersetzt das flache GENESIS-raw-dict deterministisch in einen
``CanonicalRecord`` mit ``DemographicsPayload`` (kind=demographics). Die Funktion
ist rein: kein HTTP, kein Logging, kein ``datetime.now()``. Der
``retrieved_at``-Zeitstempel wird keyword-only injiziert, damit Tests
deterministisch bleiben.

KRITISCH (Lizenz-Klassifikation GOV-02): GENESIS-Demografie ist Tier A (offene Lizenz),
``source=SourceId.GENESIS``, ``license_id=DL_DE_BY_2_0``, ``license_tier=A``.
Die Attribution traegt PFLICHT die Destatis-/Regionalstatistik-Quelle samt der
DL-DE/BY-2.0-Lizenz-URL (GOV-03).

``observed_at`` bleibt ``None`` (das Stichjahr steht im Payload,
``reference_year``); ``geo`` bleibt ``None`` (Stadtebene, kein Punkt-Geo).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    DemographicsPayload,
    LicenseId,
    LicenseTier,
    RegionalStatPayload,
    SourceId,
)

# DL-DE/BY 2.0 (Datenlizenz Deutschland Namensnennung 2.0, govdata.de).
_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"

# Wikidata-Einwohnerzahl (CC0) als Minimal-Fallback, wenn GENESIS aus ist.
_CC0_URL = "https://creativecommons.org/publicdomain/zero/1.0/"


def map_demographics(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe GENESIS-Demografiedaten auf einen ``CanonicalRecord`` ab.

    Der ``retrieved_at``-Zeitstempel wird injiziert (kein ``datetime.now()`` im
    Mapper), damit das Ergebnis deterministisch bleibt. Die Join-Keys
    ``ags``/``wikidata_qid`` werden aus dem Register durchgereicht (ARCH-02,
    Default ``None``). ``geo`` bleibt ``None`` (Stadtebene); ``observed_at``
    bleibt ``None`` (Stichjahr im Payload ``reference_year``).

    KRITISCH (GOV-02/03): ``source=GENESIS``, ``license_id=DL_DE_BY_2_0``,
    ``license_tier=A``; die Attribution nennt PFLICHT die Destatis-/
    Regionalstatistik-Quelle samt DL-DE/BY-2.0-Lizenz-URL.
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.GENESIS,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Statistisches Bundesamt (Destatis) / Regionalstatistik",
            license_url=_DL_DE_BY_URL,
        ),
        payload=DemographicsPayload(
            population=raw.get("population"),
            households=raw.get("households"),
            buildings=raw.get("buildings"),
            rent_avg=raw.get("rent_avg"),
            reference_year=raw.get("reference_year"),
            series=raw.get("series", []),
        ),
    )


def map_regional_stat(
    slug: str,
    raw: dict,
    *,
    dataset: str,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet eine GENESIS-Regionalstatistik-Kennzahl auf einen ``CanonicalRecord`` ab.

    ``raw`` ist das vom Adapter (``fetch_genesis_table``) gelieferte dict
    (``reference_year``/``region_name``/``values``). ``dataset`` benennt den
    Datensatz (unemployment/tourism/construction). Rein: kein HTTP, kein
    ``datetime.now()`` (injiziert). GOV-02/03: ``source=GENESIS``,
    ``license_id=DL_DE_BY_2_0``, Tier A, Destatis-/Regionalstatistik-Attribution.
    ``observed_at``/``geo`` bleiben ``None`` (Jahreswert je Kreis, kein Punkt-Geo).
    """
    return CanonicalRecord(
        city_slug=slug,
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.GENESIS,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Statistisches Bundesamt (Destatis) / Regionalstatistik",
            license_url=_DL_DE_BY_URL,
        ),
        payload=RegionalStatPayload(
            dataset=dataset,
            reference_year=raw.get("reference_year"),
            region_name=raw.get("region_name"),
            values=raw.get("values", {}),
        ),
    )


def map_population_demographics(
    *,
    slug: str,
    population: int | None,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Minimal-Demografie-Record aus der Register-Einwohnerzahl (Wikidata/CC0).

    Fallback, wenn GENESIS deaktiviert ist (DATA-17): liefert nur population
    aus dem Register (Herkunft Wikidata, CC0). Sortenrein Tier A mit eigener
    Wikidata-Attribution - KEINE Vermischung mit GENESIS (das einen vollen
    DemographicsPayload liefert). reference_year bleibt None (Wikidata-Stand
    ist nicht jahresscharf gefuehrt).
    """
    return CanonicalRecord(
        city_slug=slug,
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.WIKIDATA,
        license_id=LicenseId.CC0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(text="Wikidata (Einwohnerzahl)", license_url=_CC0_URL),
        payload=DemographicsPayload(population=population),
    )
