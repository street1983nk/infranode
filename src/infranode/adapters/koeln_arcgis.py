"""Keyloser Koeln-Verkehrs-Adapter fetch_koeln_road_events (DATA-15, Tier A).

Die Stadt Koeln stellt Baustellen/Verkehrsbeeintraechtigungen ueber einen
ArcGIS-REST-Endpunkt (Verkehrskalender, MapServer) bereit. Der alte CKAN-Pfad
ist seit der Drupal-10-Migration tot (404); deshalb wird hier 1:1 die in Phase 7
erprobte BNetzA-ArcGIS-Blaupause gespiegelt (Plan 09-02, Decision 2). Der Adapter
fragt eine Envelope-Geometry (Bounding-Box) um den Register-Geo (``lat``/``lon``)
der Stadt ab und reduziert die ``features`` auf eine schlanke Event-Liste.

Layer [VERIFIED 2026-06-10] per Live-Probe gegen den MapServer:
Layer 0 "Standort" (Punkt) und Layer 2 "Bereich" (Flaeche) tragen das
Baustellen-Schema (``name``/``typ``/``datum_von``/``datum_bis``/``beschreibung``)
und werden beide abgefragt (additiv zusammengefuehrt). Layer 1 "Strecke" ist
live verifiziert KEIN Baustellen-Layer (Schema ``identifier``/``auslastung``/
``tendenz`` = Verkehrslage-Strecken ohne Datumsfelder) und wird bewusst NICHT
abgefragt. TODO: erneut pruefen, falls die Stadt Koeln einen echten
Linien-Baustellen-Layer ergaenzt.

Felder [VERIFIED 2026-06-10] per Live-Probe: ``objectid``, ``name``,
``datum_von``, ``datum_bis``, ``link``, ``typ``, ``anzeige``, ``beschreibung``.
``typ`` ist ein Integer-Code (kein Text) und wird roh als String durchgereicht;
``datum_von``/``datum_bis`` sind Epoch-MILLISEKUNDEN (z. B. 1725408000000) und
werden defensiv nach ISO-8601 (UTC) konvertiert. Das Service-CRS ist UTM, daher
wird ``outSR=4326`` mitgesendet; dann ist ``geometry.x``=lon, ``geometry.y``=lat.

Sicherheit (T-9-02 SSRF): Der Host ist in ``_BASE`` hartkodiert; die Geometry
wird ausschliesslich aus (``lat``/``lon``) gebaut, nie aus einem User-Host. Der
Slug stammt aus dem Register-Allowlist (Route), nie roher User-Input.

DoS-Schutz (T-9-DOS): enge Bounding-Box (``delta=0.15``) plus
``resultRecordCount=1000`` als harter Cap je Layer; Cache/SWR/Single-Flight/
Breaker liefert die Resilienz-Fassade.

Datenfehler-Schutz (T-9-02 / Phase-7/8-Konvention): Der Adapter liest jedes Feld
defensiv per ``.get(...)`` mit None-Fallback, daher kein ``KeyError`` bei einem
fehlenden oder anders benannten Feld; die Epoch-ms-Konvertierung faengt
None/0/Unsinn ab.

Der Adapter ist rein gegenueber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade). ``resp.raise_for_status()`` ist Pflicht,
damit ein 5xx als ``httpx.HTTPError`` an die Fassade durchschlaegt und der
STALE-ON-ERROR-Pfad greift.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx

# [VERIFIED 2026-06-10] Layer 0 "Standort" (Punkt) + Layer 2 "Bereich" (Flaeche)
# tragen das Baustellen-Schema; Layer 1 "Strecke" ist ein Verkehrslage-Layer
# (auslastung/tendenz, keine Datumsfelder) und bleibt bewusst aussen vor.
_LAYERS: tuple[int, ...] = (0, 2)

# Host hartkodiert (T-9-02 SSRF): nur dieser eine ArcGIS-REST-Endpunkt der Stadt
# Koeln. Der Layer-Index wird je Abfrage an _BASE angehaengt (nur aus _LAYERS).
_BASE = (
    "https://geoportal.stadt-koeln.de/arcgis/rest/services/"
    "verkehr/verkehrskalender/MapServer"
)

# [VERIFIED 2026-06-10] Feldnamen per Live-Probe gegen Layer 0/2. Defensiv per
# .get() gelesen -> None-Fallback statt KeyError (T-9-02, Phase-7/8-Konvention).
_FIELD_BEZEICHNUNG = "name"  # [VERIFIED 2026-06-10] Titel/Strasse der Massnahme
_FIELD_ART = "typ"  # [VERIFIED 2026-06-10] Integer-Code, als String durchgereicht
_FIELD_BEGINN = "datum_von"  # [VERIFIED 2026-06-10] Epoch-ms -> ISO-8601
_FIELD_ENDE = "datum_bis"  # [VERIFIED 2026-06-10] Epoch-ms -> ISO-8601


def _epoch_ms_to_iso(value: object) -> str | None:
    """Konvertiert Epoch-MILLISEKUNDEN defensiv nach ISO-8601 (UTC).

    [VERIFIED 2026-06-10]: der ArcGIS-Dienst liefert ``datum_von``/``datum_bis``
    als Epoch-ms (z. B. 1725408000000). None/0/negative Werte oder Nicht-Zahlen
    (auch bool) -> None statt Crash (T-9-02).
    """
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value / 1000.0, tz=UTC).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _extract_point(geom: dict) -> tuple[float | None, float | None]:
    """Liefert (lon, lat) als repraesentativen Punkt einer ArcGIS-Geometrie.

    Punkt-Layer (0): ``x``/``y`` direkt. Flaechen-Layer (2): erste Koordinate des
    ersten Rings (``rings``); analog ``paths`` fuer etwaige Linien. Mit
    ``outSR=4326`` gilt x=lon, y=lat ([VERIFIED 2026-06-10]). Defensiv: jede
    abweichende Struktur -> (None, None) statt Crash (T-9-02).
    """
    x, y = geom.get("x"), geom.get("y")
    if isinstance(x, int | float) and isinstance(y, int | float):
        return float(x), float(y)
    for key in ("rings", "paths"):
        parts = geom.get(key)
        if not (isinstance(parts, list) and parts and isinstance(parts[0], list)):
            continue
        first_part = parts[0]
        if not first_part:
            continue
        coord = first_part[0]
        if (
            isinstance(coord, list)
            and len(coord) >= 2
            and isinstance(coord[0], int | float)
            and isinstance(coord[1], int | float)
        ):
            return float(coord[0]), float(coord[1])
    return None, None


async def fetch_koeln_road_events(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float,
    lon: float,
    delta: float = 0.15,
) -> dict:
    """Holt Koeln-Baustellen/Sperrungen in einer Bounding-Box um (``lat``, ``lon``).

    Baut eine ArcGIS-Envelope-Geometry (``xmin``/``ymin``/``xmax``/``ymax`` aus
    ``lat``/``lon`` +/- ``delta``, ``wkid=4326``) und fragt die Baustellen-Layer
    ``_LAYERS`` (0 "Standort" + 2 "Bereich", [VERIFIED 2026-06-10]) des MapServers
    mit ``f=json``, ``returnGeometry=true``, ``outSR=4326`` (Service-CRS ist UTM)
    und ``resultRecordCount=1000`` (DoS-Cap je Layer) ab; die Ergebnisse werden
    additiv zusammengefuehrt. Aus ``features`` wird je Event
    ``bezeichnung``/``art``/``beginn``/``ende`` (aus ``attributes`` per ``.get()``
    mit None-Fallback, T-9-02; ``typ`` als String, Epoch-ms -> ISO-8601) und
    ``lat``/``lon`` (repraesentativer Punkt) extrahiert.

    Rueckgabe-Keys (exakt das, was ``map_koeln_road_events`` erwartet): ``slug``
    und ``events``.
    """
    geometry = {
        "xmin": lon - delta,
        "ymin": lat - delta,
        "xmax": lon + delta,
        "ymax": lat + delta,
        "spatialReference": {"wkid": 4326},
    }
    params = {
        "f": "json",
        "geometry": json.dumps(geometry),
        "geometryType": "esriGeometryEnvelope",
        "inSR": 4326,
        # [VERIFIED 2026-06-10]: ohne outSR kommt das Service-CRS (UTM); mit
        # outSR=4326 ist geometry.x=lon und geometry.y=lat.
        "outSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true",
        "resultRecordCount": 1000,
    }

    events: list[dict] = []
    for layer in _LAYERS:
        resp = await http.get(f"{_BASE}/{layer}/query", params=params)
        resp.raise_for_status()

        body = resp.json()
        features = body.get("features", []) if isinstance(body, dict) else []
        for feature in features:
            if not isinstance(feature, dict):
                continue
            attributes = feature.get("attributes") or {}
            geom = feature.get("geometry") or {}
            feature_lon, feature_lat = _extract_point(geom)
            art = attributes.get(_FIELD_ART)
            # T-9-02: fehlendes Feld -> None (kein KeyError). typ ist ein
            # Integer-Code [VERIFIED 2026-06-10] und wird als String gereicht.
            events.append(
                {
                    "bezeichnung": attributes.get(_FIELD_BEZEICHNUNG),
                    "art": str(art) if art is not None else None,
                    "beginn": _epoch_ms_to_iso(attributes.get(_FIELD_BEGINN)),
                    "ende": _epoch_ms_to_iso(attributes.get(_FIELD_ENDE)),
                    "lat": feature_lat,
                    "lon": feature_lon,
                }
            )

    return {"slug": slug, "events": events}
