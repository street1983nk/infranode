"""Reiner BKG-Verwaltungsgrenzen-Mapper map_admin_boundary (DATA-19, GOV-03).

Uebersetzt das flache BKG-Attributtabellen-raw-dict (AGS/GEN/area_km2) deterministisch
in einen ``CanonicalRecord`` mit ``AdminBoundaryPayload`` (kind=admin_boundary). Die
Funktion ist rein: kein HTTP, kein Logging, kein ``datetime.now()``. Der
``retrieved_at``-Zeitstempel wird keyword-only injiziert, damit Tests deterministisch
bleiben.

KRITISCH (Lizenz-Klassifikation GOV-02): BKG-Verwaltungsgrenzen sind Tier A
(offene Lizenz), ``source=SourceId.BKG``, ``license_id=DL_DE_BY_2_0``,
``license_tier=A`` (DL-DE/BY 2.0).

KRITISCH (GOV-03, RESEARCH DATA-19, Pflicht-Wortlaut): Die Attribution traegt PFLICHT
den exakten Wortlaut ``"(c) GeoBasis-DE / BKG (<jahr>)"``. Der Mapper- und Routen-Test
asserted den Substring ``"(c) GeoBasis-DE / BKG"``.

NUR Grenzen + Namen + Flaeche: ``geo`` bleibt ``None`` (KEIN Geometrie-/Geocoding-
Output), KEIN PLZ-Geocoding (Schema ``AdminBoundaryPayload`` traegt keine PLZ-/
Geocoder-Felder). ``observed_at`` bleibt ``None`` (das Bezugsjahr steht im Payload
``reference_year``).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    AdminBoundaryPayload,
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    SourceId,
)

# DL-DE/BY 2.0 (Datenlizenz Deutschland Namensnennung 2.0, govdata.de).
_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"

# Fallback-Bezugsjahr fuer den Pflicht-Quellvermerk, falls das raw-dict kein
# reference_year traegt (defensiv; der Ingest setzt es aus dem VG250-Jahrgang).
_FALLBACK_JAHR = datetime.now().year


def map_admin_boundary(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet einen rohen BKG-Attributtabellen-Eintrag auf einen ``CanonicalRecord`` ab.

    Der ``retrieved_at``-Zeitstempel wird injiziert (kein ``datetime.now()`` im
    Mapper), damit das Ergebnis deterministisch bleibt. Die Join-Keys
    ``ags``/``wikidata_qid`` werden aus dem Register durchgereicht (ARCH-02, Default
    ``None``). ``geo`` bleibt ``None`` (NUR Grenzen/Namen/Flaeche, KEIN Geometrie-/
    Geocoding-Output); ``observed_at`` bleibt ``None`` (Bezugsjahr im Payload).

    KRITISCH (GOV-03, Pflicht-Wortlaut): Die Attribution traegt PFLICHT den exakten
    Wortlaut ``"(c) GeoBasis-DE / BKG (<jahr>)"`` (DL-DE/BY 2.0); der Mapper- und
    Routen-Test asserted den Substring ``"(c) GeoBasis-DE / BKG"``.
    """
    jahr = raw.get("reference_year") or _FALLBACK_JAHR
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.BKG,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=f"(c) GeoBasis-DE / BKG ({jahr})",
            license_url=_DL_DE_BY_URL,
        ),
        payload=AdminBoundaryPayload(
            ags=raw.get("ags"),
            gen_name=raw.get("gen_name"),
            area_km2=raw.get("area_km2"),
            reference_year=raw.get("reference_year"),
        ),
    )
