"""Keyloser DWD-Waldbrand-/Graslandfeuerindex-Adapter fetch_fire_danger.

Lädt den taeglichen Waldbrandgefahrenindex (WBI) und den Graslandfeuerindex
(GLFI) des Deutschen Wetterdienstes ueber einen oeffentlichen ArcGIS-
FeatureServer und waehlt je Stadt die naechste DWD-Station aus. Das Ergebnis ist
ein flaches raw-dict, das der reine ``map_fire_danger``-Mapper erwartet.

Quelle/Lizenz: Die Daten stammen vom Deutschen Wetterdienst (Attribution
``accessInformation`` = "Deutscher Wetterdienst (DWD)", GeoNutzV, freie Nutzung
mit Quellenangabe -> Tier A). Der FeatureServer ist ein Re-Host der DWD-Daten
(betrieben vom Landkreis Nienburg/Weser auf ArcGIS Online); InfraNode nennt als
Datenbasis bewusst den DWD, nicht den Re-Host. Layer 3 = Waldbrandgefahrenindex,
Layer 1 = Graslandfeuerindex; beide tragen je Punkt-Station ``wbi_tag`` (Stufe
1..5), Koordinaten (``geoBreite``/``geoLaenge``, WGS84), ``Stationsname``,
``Bundesland`` und ``tag`` (Vorhersagedatum als Epoch-ms).

KRITISCH (Ehrlichkeit, Pitfall 4): Der Index ist STATIONS-genau, NICHT
stadtgenau. Der raw-dict weist die getroffene Station + Distanz aus, damit der
Mapper das ehrlich im Payload spiegeln kann. Die Stationsauswahl nutzt eine
breitengrad-korrigierte Grad-Distanz (kein Haversine, Don't-Hand-Roll, vgl.
``uba._deg_distance``).

Sicherheit (T-07-IN, SSRF): Der Host ``base_url`` ist operator-konfigurierbar
(``INFRANODE_DWD_FIRE_BASE_URL``), aber kein User-Input; die Layer-IDs und
``outFields`` sind hartkodiert. Der GLFI-Abruf ist best-effort (ein Ausfall
laesst den WBI unberuehrt); der WBI-Abruf nutzt ``raise_for_status`` (5xx ->
``httpx.HTTPError`` -> STALE-ON-ERROR der Fassade).

Der Adapter ist rein gegenueber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import httpx

# Operator-konfigurierbarer FeatureServer-Host (T-07-IN: kein User-Input). Default
# ist der oeffentliche DWD-Daten-Re-Host (Layer 3 WBI, Layer 1 GLFI).
_BASE = "https://services2.arcgis.com/7wuv6DH7DYhDuwvU/ArcGIS/rest/services/DWD/FeatureServer"

# Layer-IDs (hartkodiert): aktuelle Punkt-Stationen je Index.
_LAYER_WBI = 3
_LAYER_GLFI = 1

# Felder, die der Adapter aus den ArcGIS-Attributen liest (hartkodierte
# outFields halten die Antwort klein und schuetzen vor Feld-Injection).
_OUT_FIELDS = ",".join(
    (
        "Stations_ID",
        "Stationsname",
        "Bundesland",
        "geoBreite",
        "geoLaenge",
        "wbi_tag",
        "tag",
        "aktualisierung_DWD",
    )
)


def _deg_distance(alat: float, alon: float, blat: float, blon: float) -> float:
    """Einfache breitengrad-korrigierte Grad-Distanz fuer die Stationsauswahl.

    Bewusst KEIN Haversine (Don't-Hand-Roll, vgl. ``uba._deg_distance``): fuer die
    grobe Auswahl der naechsten Station reicht eine euklidische Grad-Distanz mit
    ``cos(lat)``-korrigierter Laengen-Achse.
    """
    cos_lat = math.cos(math.radians(alat))
    dlat = blat - alat
    dlon = (blon - alon) * cos_lat
    return math.hypot(dlat, dlon)


def _km(alat: float, alon: float, blat: float, blon: float) -> float:
    """Grobe Distanz in km (1 Grad ~ 111 km), nur zur Transparenz-Anzeige."""
    return round(_deg_distance(alat, alon, blat, blon) * 111.0, 1)


def _pick_nearest(features: list[dict], lat: float, lon: float) -> dict | None:
    """Waehlt das Stations-Feature mit der kleinsten Grad-Distanz zu (lat, lon).

    ``features`` ist die ArcGIS-``features``-Liste (je Eintrag ``attributes``).
    Stationen ohne gueltige Koordinaten oder ohne Stufe (``wbi_tag``) werden
    uebersprungen. Gibt ``None``, wenn keine brauchbare Station existiert
    (graceful no_data statt Crash, T-07-IN).
    """
    best: dict | None = None
    best_dist = float("inf")
    for feat in features:
        attrs = feat.get("attributes") if isinstance(feat, dict) else None
        if not isinstance(attrs, dict):
            continue
        if attrs.get("wbi_tag") is None:
            continue
        try:
            slat = float(attrs["geoBreite"])
            slon = float(attrs["geoLaenge"])
        except (KeyError, TypeError, ValueError):
            continue
        dist = _deg_distance(lat, lon, slat, slon)
        if dist < best_dist:
            best_dist = dist
            best = {
                **attrs,
                "_lat": slat,
                "_lon": slon,
                "_distance_km": _km(lat, lon, slat, slon),
            }
    return best


def _epoch_ms_to_date(value: object) -> str | None:
    """Wandelt ein ArcGIS-Epoch-ms-Feld defensiv in ein ISO-Datum (YYYY-MM-DD)."""
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, UTC).date().isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


async def _query_layer(
    http: httpx.AsyncClient, base_url: str, layer: int
) -> list[dict]:
    """Fragt einen FeatureServer-Layer ab und gibt die ``features``-Liste zurueck.

    ``raise_for_status`` schlaegt ein 5xx als ``httpx.HTTPError`` an die Fassade
    durch (STALE-ON-ERROR). Eine wohlgeformte, aber leere Antwort liefert ``[]``.
    """
    resp = await http.get(
        f"{base_url}/{layer}/query",
        params={
            "where": "1=1",
            "outFields": _OUT_FIELDS,
            "returnGeometry": "false",
            "f": "json",
        },
    )
    resp.raise_for_status()
    body = resp.json()
    feats = body.get("features") if isinstance(body, dict) else None
    return feats if isinstance(feats, list) else []


async def fetch_fire_danger(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float,
    lon: float,
    base_url: str = _BASE,
) -> dict:
    """Holt WBI (+ GLFI best-effort) der naechsten DWD-Station einer Stadt.

    Fragt Layer 3 (Waldbrandgefahrenindex) ab und waehlt die naechste Station zu
    (``lat``, ``lon``). Der Graslandfeuerindex (Layer 1) wird best-effort
    nachgeladen (ein Ausfall laesst den WBI unberuehrt). Gibt das flache raw-dict
    zurueck, das ``map_fire_danger`` erwartet.

    Rueckgabe-Keys: ``slug``, ``wbi_level`` (int 1..5 oder None), ``station_name``,
    ``station_id``, ``bundesland``, ``distance_km``, ``forecast_date`` (ISO),
    ``updated_at`` (DWD-Aktualisierung), ``glfi_level`` (int oder None). Findet
    sich keine Station (leerer Feed), bleiben die Werte ``None`` (ehrliches
    no_data, kein Crash). ``raise_for_status`` des WBI-Abrufs schlaegt 5xx als
    ``httpx.HTTPError`` an die Fassade durch.
    """
    wbi_features = await _query_layer(http, base_url, _LAYER_WBI)
    station = _pick_nearest(wbi_features, lat, lon)

    if station is None:
        return {
            "slug": slug,
            "wbi_level": None,
            "station_name": None,
            "station_id": None,
            "bundesland": None,
            "distance_km": None,
            "forecast_date": None,
            "updated_at": None,
            "glfi_level": None,
        }

    # GLFI best-effort: ein Ausfall des zweiten Layers darf den WBI nicht kippen.
    glfi_level: int | None = None
    try:
        glfi_features = await _query_layer(http, base_url, _LAYER_GLFI)
        glfi_station = _pick_nearest(glfi_features, lat, lon)
        if glfi_station is not None:
            raw_glfi = glfi_station.get("wbi_tag")
            glfi_level = int(raw_glfi) if raw_glfi is not None else None
    except (httpx.HTTPError, ValueError, TypeError):
        glfi_level = None

    raw_wbi = station.get("wbi_tag")
    return {
        "slug": slug,
        "wbi_level": int(raw_wbi) if raw_wbi is not None else None,
        "station_name": station.get("Stationsname"),
        "station_id": station.get("Stations_ID"),
        "bundesland": station.get("Bundesland"),
        "distance_km": station.get("_distance_km"),
        "forecast_date": _epoch_ms_to_date(station.get("tag")),
        "updated_at": station.get("aktualisierung_DWD"),
        "glfi_level": glfi_level,
    }
