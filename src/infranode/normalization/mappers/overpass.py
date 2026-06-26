"""Reiner Overpass-POI-Mapper (DATA-04, Tier B copyleft).

Uebersetzt rohe Overpass-Elemente (ein dict mit ``poi_type`` und ``elements``)
deterministisch in einen ``CanonicalRecord`` mit ``PoiPayload``. Die Funktion ist
rein: kein HTTP, kein Logging, kein ``datetime.now()``. Der ``retrieved_at``-
Zeitstempel wird keyword-only injiziert, damit Tests deterministisch bleiben.

OSM ist ODbL-lizenziert (Tier B copyleft): ``license_id=ODBL``,
``license_tier=B`` (kennzeichnet die Copyleft-Lizenz zur korrekten Attribution
und Weiternutzung) und die wortgenaue Attribution
"© OpenStreetMap contributors". POIs sind
statisch, daher ``observed_at=None``; ``geo`` ist ``None`` (die Einzel-POIs
tragen ihre Koordinaten im Payload, kein einzelner Stadt-Geo noetig).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    PoiPayload,
    SourceId,
)

_ODBL_URL = "https://opendatacommons.org/licenses/odbl/1-0/"


def map_overpass_pois(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe Overpass-POIs auf einen ``CanonicalRecord`` (Tier B) ab.

    Jedes Element wird auf ein schlankes dict (``name``/``lat``/``lon``)
    reduziert. ``count`` ist immer ``len(items)``. POIs sind statisch, daher ist
    ``observed_at`` ``None``; der ``retrieved_at``-Zeitstempel wird injiziert
    (kein ``datetime.now()`` im Mapper), damit das Ergebnis deterministisch
    bleibt. Die Join-Keys ``ags``/``wikidata_qid`` werden aus dem Register
    durchgereicht (Default ``None``); POIs haben keine punktstabile Mess-Station,
    daher KEIN ``station_id`` (``poi_type`` ist der fachliche Schluessel).
    """
    items = [
        {
            "name": element.get("tags", {}).get("name"),
            # node: lat/lon direkt; way/relation (out center): aus center.
            "lat": element.get("lat") or (element.get("center") or {}).get("lat"),
            "lon": element.get("lon") or (element.get("center") or {}).get("lon"),
        }
        for element in raw["elements"]
    ]
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.OSM,
        license_id=LicenseId.ODBL,
        license_tier=LicenseTier.B,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="© OpenStreetMap contributors",
            license_url=_ODBL_URL,
        ),
        payload=PoiPayload(
            poi_type=raw["poi_type"],
            count=len(items),
            items=items,
        ),
    )


def map_osm_feature(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet eine generische OSM-Feature-Datenart auf einen ``CanonicalRecord`` ab.

    Wie ``map_overpass_pois``, aber mit zusaetzlichen, je Feature konfigurierten
    OSM-Tag-Feldern (``raw["extra_tags"]``, z.B. ``collection_times`` am Briefkasten
    oder ``opening_hours`` am Markt). Ein Extra-Tag wird nur gesetzt, wenn das
    Element es traegt (kein ``null``-Rauschen). Rein, deterministisch (kein
    ``datetime.now()``), ODbL/Tier B wie der POI-Mapper.
    """
    extra_tags = raw.get("extra_tags", [])
    items = []
    for element in raw["elements"]:
        tags = element.get("tags", {})
        item = {
            "name": tags.get("name"),
            # node: lat/lon direkt; way/relation (out center): aus center.
            "lat": element.get("lat") or (element.get("center") or {}).get("lat"),
            "lon": element.get("lon") or (element.get("center") or {}).get("lon"),
        }
        for tag in extra_tags:
            value = tags.get(tag)
            if value is not None:
                item[tag] = value
        items.append(item)
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.OSM,
        license_id=LicenseId.ODBL,
        license_tier=LicenseTier.B,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="© OpenStreetMap contributors",
            license_url=_ODBL_URL,
        ),
        payload=PoiPayload(
            poi_type=raw["poi_type"],
            count=len(items),
            items=items,
        ),
    )
