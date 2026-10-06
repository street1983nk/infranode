"""Rostock-Baustellen-Adapter ``fetch_rostock_road_events`` (road-events, Tier A).

Liefert die Baustellen der Hanse- und Universitaetsstadt Rostock keylos aus dem
offenen Datenportal OpenData.HRO (GeoJSON-Download, CC0-1.0, [VERIFIED 2026-07-17]):

  geo.sv.rostock.de/download/opendata/baustellen/baustellen.json

Je Baustelle ein Punkt-Feature (WGS84) mit Massnahme, Sparte, Strasse, Abschnitt
(von/nach), Zeitraum (baubeginn/bauende) und Verkehrsbeeintraechtigung. Die Events
wandern als schlanke dicts in den ``RoadEventPayload`` (wie Dortmund/Muenchen).

Sicherheit (T-9-02 SSRF): Host + Pfad hartkodiert (kein User-Input). DoS-/Daten-
fehler-Schutz: ``raise_for_status()`` (5xx -> STALE-ON-ERROR der Fassade); Felder
defensiv (fehlend -> None statt KeyError).
"""

from __future__ import annotations

import httpx

_GEOJSON_URL = "https://geo.sv.rostock.de/download/opendata/baustellen/baustellen.json"


def _point_lat_lon(geometry: dict | None) -> tuple[float | None, float | None]:
    """Liest lat/lon aus einer GeoJSON-Punkt-Geometrie (``[lon, lat]``, WGS84)."""
    if not isinstance(geometry, dict):
        return (None, None)
    coords = geometry.get("coordinates")
    if (
        isinstance(coords, (list, tuple))
        and len(coords) >= 2
        and isinstance(coords[0], (int, float))
        and isinstance(coords[1], (int, float))
    ):
        return (float(coords[1]), float(coords[0]))
    return (None, None)


async def fetch_rostock_road_events(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float | None = None,
    lon: float | None = None,
) -> dict:
    """Holt die Rostocker Baustellen (GeoJSON, keylos).

    ``lat``/``lon`` sind vertragskonform Teil der Signatur (ungenutzt: der Export
    ist bereits stadtscharf). Rueckgabe: ``slug`` + ``events`` (je Baustelle ein
    schlankes dict mit Massnahme/Sparte/Strasse/Abschnitt/Zeitraum + lat/lon).
    """
    resp = await http.get(_GEOJSON_URL)
    resp.raise_for_status()
    data = resp.json()
    features = data.get("features", []) if isinstance(data, dict) else []
    events: list[dict] = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties") or {}
        feat_lat, feat_lon = _point_lat_lon(feature.get("geometry"))
        description = props.get("baumassnahme")
        sector = props.get("sparte")
        restriction = props.get("verkehrsbeeintraechtigungen")
        street = props.get("strasse_name")
        section_from = props.get("von")
        section_to = props.get("nach")
        start = props.get("baubeginn")
        end = props.get("bauende")
        events.append(
            {
                # Kanonische englische Namen (Muster koeln_arcgis).
                "description": description,
                "sector": sector,
                "restriction": restriction,
                "street": street,
                "section_from": section_from,
                "section_to": section_to,
                "start": start,
                "end": end,
                "lat": feat_lat,
                "lon": feat_lon,
            }
        )
    return {"slug": slug, "events": events}
