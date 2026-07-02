"""Dortmund-Baustellen-Adapter ``fetch_dortmund_road_events`` (DATA-15, Tier A).

Liefert die tagesaktuellen Baustellen der Stadt Dortmund keylos aus dem
Opendatasoft-Portal (GeoJSON-Export, DL-DE/Zero 2.0, [VERIFIED 2026-07-02]):

  open-data.dortmund.de/.../fb66-baustellen-tagesaktuell/exports/geojson

Je Baustelle ein Punkt-Feature (WGS84) mit Maßnahme-Beschreibung, Auftraggeber,
Zeitraum (von/bis) und Stadtbezirk. Die Events wandern als schlanke dicts in den
``RoadEventPayload`` (wie München/Berlin). Datenschema am 09.02.2026 geändert
(laut Portal-Beschreibung), daher Felder defensiv gelesen.

Sicherheit (T-9-02 SSRF): Host + Pfad hartkodiert (kein User-Input). DoS-/Daten-
fehler-Schutz: ``raise_for_status()`` (5xx -> STALE-ON-ERROR der Fassade); Felder
defensiv (fehlend -> None statt KeyError).
"""

from __future__ import annotations

import httpx

_GEOJSON_URL = (
    "https://open-data.dortmund.de/api/explore/v2.1/catalog/datasets/"
    "fb66-baustellen-tagesaktuell/exports/geojson"
)


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


async def fetch_dortmund_road_events(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float | None = None,
    lon: float | None = None,
) -> dict:
    """Holt die tagesaktuellen Dortmunder Baustellen (GeoJSON, keylos).

    ``lat``/``lon`` sind vertragskonform Teil der Signatur (ungenutzt: der Export
    ist bereits stadtscharf). Rückgabe: ``slug`` + ``events`` (je Baustelle ein
    schlankes dict mit Beschreibung/Auftraggeber/Zeitraum/Bezirk + lat/lon).
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
        events.append(
            {
                "beschreibung": props.get("art_der_baumassnahme"),
                "auftraggeber": props.get("auftraggeber"),
                "einschraenkung": props.get("einschrankung"),
                "zeitraum": props.get("zeitraum"),
                "von": props.get("von"),
                "bis": props.get("bis"),
                "stadtbezirk": props.get("stadtbezirk"),
                "lat": feat_lat,
                "lon": feat_lon,
            }
        )
    return {"slug": slug, "events": events}
