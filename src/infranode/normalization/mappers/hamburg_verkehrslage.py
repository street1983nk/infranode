"""Reiner Hamburg-Verkehrslage-Mapper (DATA-26, Tier A DL-DE/BY, keylos).

Übersetzt das rohe Adapter-dict aus ``adapters/hamburg_verkehrslage.py``
deterministisch in einen ``CanonicalRecord``:
- ``map_hamburg_verkehrslage``: ``segments`` (nicht-fließende Straßenabschnitte)
  + ``summary`` (Netz-Zählung je Zustandsklasse) -> ``TrafficFlowPayload``.

Schablone ist ``mappers/mobilithek_koeln.py`` (map_koeln_traffic_flow): rein
(kein HTTP, kein Geo-Parse, keine Systemuhr), ``retrieved_at`` keyword-only
injiziert (deterministisch). Der Hamburger Verkehrslage-Datensatz steht unter der
Datenlizenz Deutschland Namensnennung 2.0: ``license_id=DL_DE_BY_2_0``,
``license_tier=A`` (anders als der HVV-Geofox-Live-Pfad, der NICHT offen ist).
Attribution "Freie und Hansestadt Hamburg" (wortgenau wie SOURCE_LICENSE /
DATA-LICENSES.md, identisch zum hamburg_baustellen-Datensatz derselben Plattform).

Reine Live-Daten -> ``geo=None`` (der Feed trägt die Abschnitts-Geo je Segment im
Payload, nicht stadtweit); ``observed_at`` aus dem jüngsten Datenstand (``as_of``)
falls vorhanden, sonst ``None`` (ehrlich, keine Systemuhr). KEIN Archiv (Live-only).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    SourceId,
    TrafficFlowPayload,
)

_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"
_HAMBURG_ATTRIBUTION = "Freie und Hansestadt Hamburg"


def _parse_as_of(raw: dict) -> datetime | None:
    """Liest ``as_of`` (jüngster Datenstand) als aware ``datetime`` oder None.

    Rein (keine Systemuhr); nicht-parsebarer/fehlender Wert -> ``None`` (ehrlich).
    """
    text = raw.get("as_of")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None


def map_hamburg_verkehrslage(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet die Hamburg-Verkehrslage auf einen ``CanonicalRecord`` ab.

    Die ``segments`` (nicht-fließende Abschnitte je state/road_class/lat/lon)
    wandern in ``TrafficFlowPayload.measurements``, die Netz-Zählung in
    ``TrafficFlowPayload.summary``; ``station_id`` bleibt None (flächige Quelle,
    keine Messpunkt-Referenz). ``observed_at`` aus ``as_of`` falls vorhanden;
    ``retrieved_at`` injiziert (keine Systemuhr im Mapper).
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=_parse_as_of(raw),
        retrieved_at=retrieved_at,
        source=SourceId.HAMBURG_VERKEHRSLAGE,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text=_HAMBURG_ATTRIBUTION,
            license_url=_DL_DE_BY_URL,
        ),
        payload=TrafficFlowPayload(
            station_id=None,
            measurements=raw.get("segments", []),
            summary=raw.get("summary"),
        ),
    )
