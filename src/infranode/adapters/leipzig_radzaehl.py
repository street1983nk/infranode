"""Leipzig-Radzählstellen-Adapter ``fetch_leipzig_radzaehl`` (DATA-40, Tier A).

Liefert die Stunden-Radzählwerte der Leipziger Dauerzählstellen (~26 Stationen)
keylos als kanonisches Zählstellen-dict. Zwei OpenData-WFS-Layer der Stadt Leipzig
(beide DL-DE/BY 2.0, "Stadt Leipzig", [VERIFIED 2026-06-23]) werden gejoint:

1. Standorte (``OpenData:radverkehr_dauerzaehlstelle_standort_statisch``,
   ``outputFormat=application/json``, ``srsName=EPSG:4326``): Stationsname,
   ``stationid`` und Koordinaten (Point, WGS84).
2. Stundenwerte (``OpenData:radverkehr_dauerzaehlstelle_anzahl_stunde_zeitreihe``,
   ``outputFormat=csv``, rollierendes 31-Tage-Fenster, ~4 MB): Felder
   ``stationid``/``phenomenontime``/``count``. Je Station wird die Zeile des
   jüngsten ``phenomenontime`` (= frischster Stundenwert) genommen.

Join über ``stationid``. ENCODING [VERIFIED 2026-06-29]: beide Antworten sind
echtes UTF-8 (Content-Type ``charset=utf-8``, Bytes ``c3 9f`` = "ß"); sie werden
als ``utf-8`` dekodiert. (Frühere Annahme cp1252 war falsch und erzeugte live
Mojibake in Stationsnamen wie "Manetstraße".)

Sicherheit (T-9-02 SSRF): Host ``geodienste.leipzig.de`` hartkodiert in ``_BASE``;
keine Upstream-gelieferte Ziel-URL. DoS-/Datenfehler-Schutz: ``raise_for_status()``
(5xx -> STALE-ON-ERROR der Fassade); jeder Feldzugriff ``.get()``-defensiv. Ohne
Standorte (WFS leer) wird kein CSV geladen (-> no_data im Endpunkt).
"""

from __future__ import annotations

import csv
import io
import json

import httpx

_BASE = "https://geodienste.leipzig.de/l3/OpenData/wfs"
_TYPE_STANDORT = "OpenData:radverkehr_dauerzaehlstelle_standort_statisch"
_TYPE_WERTE = "OpenData:radverkehr_dauerzaehlstelle_anzahl_stunde_zeitreihe"
# Quelle ist echtes UTF-8 (live verifiziert 2026-06-29); cp1252 erzeugte Mojibake.
_ENCODING = "utf-8"


async def _fetch_standorte(http: httpx.AsyncClient) -> dict[str, dict]:
    """Holt die Stationsstammdaten (stationid -> name/lat/lon) als GeoJSON (WGS84)."""
    resp = await http.get(
        _BASE,
        params={
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeName": _TYPE_STANDORT,
            "outputFormat": "application/json",
            "srsName": "EPSG:4326",
        },
    )
    resp.raise_for_status()
    body = json.loads(resp.content.decode(_ENCODING, errors="replace"))
    features = body.get("features", []) if isinstance(body, dict) else []
    out: dict[str, dict] = {}
    for feature in features:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties") or {}
        sid = props.get("stationid")
        if not sid:
            continue
        geom = feature.get("geometry") or {}
        coords = geom.get("coordinates") if isinstance(geom, dict) else None
        lat = lon = None
        if isinstance(coords, list) and len(coords) >= 2:
            try:
                lon, lat = float(coords[0]), float(coords[1])
            except (TypeError, ValueError):
                lat = lon = None
        out[str(sid)] = {
            "station": props.get("stationname"),
            "lat": lat,
            "lon": lon,
        }
    return out


def _latest_counts(text: str) -> dict[str, dict]:
    """Je ``stationid`` die Zeile des jüngsten ``phenomenontime`` (count/period)."""
    reader = csv.DictReader(io.StringIO(text))
    latest: dict[str, dict] = {}
    for row in reader:
        sid = (row.get("stationid") or "").strip()
        t = (row.get("phenomenontime") or "").strip()
        if not sid or not t:
            continue
        if sid not in latest or t > latest[sid]["period"]:
            try:
                value = int(str(row.get("count")).strip())
            except (TypeError, ValueError):
                value = None
            latest[sid] = {"value": value, "period": t}
    return latest


async def fetch_leipzig_radzaehl(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float,
    lon: float,
    radius_km: float = 30.0,
) -> dict:
    """Holt die Leipziger Rad-Stundenzählwerte (Standort-GeoJSON + Werte-CSV).

    Step 1: Standorte (stationid -> name/Koordinaten). Ohne Standorte -> leeres
    Ergebnis (kein CSV-Fetch). Step 2: Stundenwert-CSV laden (cp1252), je Station
    den jüngsten ``phenomenontime`` extrahieren. Join über ``stationid``.

    ``lat``/``lon``/``radius_km`` sind vertragskonform Teil der Signatur (alle
    Stadt-Adapter teilen sie); Leipzig liefert den kompletten Stadt-Datensatz.

    Rückgabe-Keys (exakt das, was ``map_leipzig_radzaehl`` erwartet): ``slug``,
    ``stations`` (je Station name/lat/lon/value/period) und ``as_of`` (jüngster
    ``phenomenontime`` als ISO-String oder None).
    """
    standorte = await _fetch_standorte(http)
    if not standorte:
        return {"slug": slug, "stations": [], "as_of": None}

    werte_resp = await http.get(
        _BASE,
        params={
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeName": _TYPE_WERTE,
            "outputFormat": "csv",
        },
    )
    werte_resp.raise_for_status()
    latest = _latest_counts(werte_resp.content.decode(_ENCODING, errors="replace"))

    as_of: str | None = None
    stations: list[dict] = []
    for sid, meta in standorte.items():
        values = latest.get(sid) or {}
        period = values.get("period")
        if period and (as_of is None or period > as_of):
            as_of = period
        stations.append(
            {
                "station": meta["station"],
                "station_id": sid,
                "lat": meta["lat"],
                "lon": meta["lon"],
                "value": values.get("value"),
                "period": period,
            }
        )

    return {"slug": slug, "stations": stations, "as_of": as_of}
