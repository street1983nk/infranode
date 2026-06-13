"""Keyloser Berlin-VIZ-Adapter fetch_berlin_road_events (DATA-15, Tier A).

Die Verkehrsinformationszentrale Berlin (VIZ) stellt Baustellen und Sperrungen
als keyloses GeoJSON bereit. Da ganz Berlin = Berlin gilt, ist kein BBox-Filter
und kein Discovery noetig: der gesamte Layer wird abgefragt und je Feature werden
die relevanten ``properties`` als schlankes Event-dict uebernommen.

Sicherheit (T-9-02 / T-05-13 SSRF): Der Host ist in ``_BASE`` hartkodiert
(nur diese eine oeffentliche VIZ-Instanz), nie aus User-Input. Der ``slug``
stammt aus der Register-Allowlist.

Datenfehler-Schutz (Pitfall 6 / Don't-Hand-Roll): Berlin liefert Features mit
``GeometryCollection``-Geometrie. Der Adapter validiert die Geometrie NICHT und
liest sie nicht aus; er uebernimmt ausschliesslich die schlanken ``properties``.
So bricht ein GeometryCollection-Feature niemals.

Der Adapter ist rein gegenueber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade). ``resp.raise_for_status()`` ist Pflicht,
damit ein 5xx als ``httpx.HTTPError`` an die Fassade durchschlaegt und der
STALE-ON-ERROR-Pfad greift.
"""

from __future__ import annotations

import httpx

# Host hartkodiert (T-9-02 / T-05-13 SSRF): nur diese eine oeffentliche VIZ-Instanz.
_BASE = "https://api.viz.berlin.de/daten/baustellen_sperrungen_viz.json"

# Relevante GeoJSON-properties je Event (schlankes dict, keine Geometry).
_FIELDS = ("street", "section", "content", "validity", "subtype", "severity")


async def fetch_berlin_road_events(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float,
    lon: float,
    radius_km: float = 30.0,
) -> dict:
    """Holt Berliner Baustellen/Sperrungen als keyloses GeoJSON.

    Iteriert ueber die GeoJSON-``features`` und uebernimmt je Feature die
    relevanten ``properties`` (street/section/content/validity/subtype/severity)
    als schlankes Event-dict. Die Geometrie (``GeometryCollection``, Pitfall 6)
    wird bewusst NICHT validiert und nicht ausgelesen. Ganz Berlin = Berlin,
    daher kein BBox-Filter (``lat``/``lon`` nur fuer Signatur-Konsistenz mit den
    uebrigen Stadt-Adaptern).

    Rueckgabe-Keys (exakt das, was ``map_berlin_road_events`` erwartet):
    ``slug`` und ``events``.
    """
    resp = await http.get(_BASE)
    resp.raise_for_status()

    events: list[dict] = []
    for feature in resp.json().get("features", []):
        properties = feature.get("properties") or {}
        events.append({field: properties.get(field) for field in _FIELDS})

    return {"slug": slug, "events": events}
