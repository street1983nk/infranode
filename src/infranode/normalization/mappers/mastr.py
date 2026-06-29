"""Reiner MaStR-Energie-Mapper map_mastr_assets (DATA-18, GOV-02/03).

Aggregiert die schlanken Anlagen-dicts aus dem SQLite-Reader (read_energy)
deterministisch zu einem ``CanonicalRecord`` mit ``EnergyAssetPayload``
(kind=energy_asset). Die Funktion ist rein: kein HTTP, kein Logging, kein
``datetime.now()``. Der ``retrieved_at``-Zeitstempel wird keyword-only injiziert,
damit Tests deterministisch bleiben.

KRITISCH (Lizenz-Klassifikation GOV-02): MaStR-Energieanlagen sind Tier A
(offene Lizenz), ``source=SourceId.MASTR``, ``license_id=DL_DE_BY_2_0``,
``license_tier=A``. Die
Attribution nennt PFLICHT die Bundesnetzagentur/Marktstammdatenregister samt der
DL-DE/BY-2.0-Lizenz-URL (GOV-03).

``observed_at`` bleibt ``None`` (kein Mess-Zeitstempel auf Stadtebene); ``geo``
bleibt ``None`` (die Einzel-Koordinaten stehen in den ``assets``-dicts).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    EnergyAssetPayload,
    LicenseId,
    LicenseTier,
    SourceId,
)

# DL-DE/BY 2.0 (Datenlizenz Deutschland Namensnennung 2.0, govdata.de).
_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"


def map_mastr_assets(
    slug: str,
    rows: list[dict],
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet die schlanken MaStR-Anlagen-dicts auf einen ``CanonicalRecord`` ab.

    ``rows`` sind die vom SQLite-Reader gelieferten schlanken Anlagen-dicts (je
    ein dict mit ``einheit_typ``/``plz``/``lat``/``lon``/``leistung_kw``). Der
    ``retrieved_at``-Zeitstempel wird injiziert (kein ``datetime.now()`` im
    Mapper), damit das Ergebnis deterministisch bleibt. Die Join-Keys
    ``ags``/``wikidata_qid`` werden aus dem Register durchgereicht (ARCH-02,
    Default ``None``). ``geo`` bleibt ``None`` (Stadtebene); ``observed_at``
    bleibt ``None``.

    ``by_type`` zählt die Anlagen je Typ (pv/wind/speicher/biogas). Leere
    ``rows`` sind KEIN Fehler (Batch ohne Treffer -> count 0).
    """
    by_type: dict[str, int] = {}
    # H7: leistung_kw je Anlage zur Stadt-Gesamtleistung (+ je Typ) aggregieren -
    # die wichtigste MaStR-Kennzahl. Nur echte Zahlen zählen; trägt keine Anlage
    # eine Leistung, bleibt total_power_kw None (ehrliche Null statt 0.0).
    power_by_type: dict[str, float] = {}
    total_power_kw = 0.0
    has_power = False
    for row in rows:
        typ = row.get("einheit_typ")
        if typ:
            by_type[typ] = by_type.get(typ, 0) + 1
        leistung = row.get("leistung_kw")
        if isinstance(leistung, (int, float)) and not isinstance(leistung, bool):
            has_power = True
            total_power_kw += leistung
            if typ:
                power_by_type[typ] = power_by_type.get(typ, 0.0) + leistung

    total_power = round(total_power_kw, 1) if has_power else None
    power_by_type = {t: round(p, 1) for t, p in power_by_type.items()}

    return CanonicalRecord(
        city_slug=slug,
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.MASTR,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Bundesnetzagentur - Marktstammdatenregister",
            license_url=_DL_DE_BY_URL,
        ),
        payload=EnergyAssetPayload(
            count=len(rows),
            by_type=by_type,
            total_power_kw=total_power,
            power_by_type=power_by_type,
            assets=list(rows),
        ),
    )
