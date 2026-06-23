"""Muenchen-Raddauerzaehlstellen-Adapter ``fetch_muenchen_radzaehl`` (DATA-40, Tier A).

Liefert die Tages-Radzaehlwerte der Muenchner Dauerzaehlstellen (6 Stationen,
z.B. Erhardt/Olympia/Hirsch) keylos als kanonisches Zaehlstellen-dict. Zwei
Open-Data-Quellen der Landeshauptstadt Muenchen werden gejoint (beide
DL-DE/BY 2.0, [VERIFIED 2026-06-23]):

1. Standort-WFS (``geoportal.muenchen.de``, ``mor_wfs:raddauerzaehlstellen``):
   Stationsname (``zaehlstelle``), Lang-Name/Adresse, ``latitude``/``longitude``,
   Richtungslabels (``richtung_1``/``richtung_2``). Eine GeoJSON-Anfrage.
2. Tageswert-CSV (CKAN ``opendata.muenchen.de``, Paket
   ``daten-der-raddauerzaehlstellen-muenchen-<JAHR>``): je Monat eine
   ``rad_JJJJ_MM_tage.csv`` mit Spalten ``datum,...,zaehlstelle,richtung_1,
   richtung_2,gesamt,...``. Es wird die lexikografisch JUENGSTE ``*_tage``-CSV
   gewaehlt und daraus je Station die Zeile des juengsten ``datum`` (= frischster
   Tageswert) genommen. Jahres-Rollover-robust: das aktuelle Jahr steckt im
   CKAN-Paketnamen, daher wird das Paket aus dem ``retrieved_at``-Jahr abgeleitet
   (Adapter bleibt rein: das Jahr kommt als Parameter, nicht aus der Systemuhr).

Sicherheit (T-9-02 SSRF): beide Hosts hartkodiert (``_CKAN_BASE``/``_WFS_HOST``);
die in Step 2a entdeckte Ressourcen-URL MUSS auf ``opendata.muenchen.de`` zeigen
(Allowlist, genesis.py-Muster), sonst ``ValueError`` und KEIN Request.

DoS-/Datenfehler-Schutz: ``raise_for_status()`` (5xx -> STALE-ON-ERROR der
Fassade); jeder Feldzugriff ``.get()``-defensiv. Ist die CSV nicht erreichbar/
leer, werden dennoch die Stationen aus dem WFS (mit ``value=None``) geliefert
(ehrlicher Teil-Datenstand statt Crash).
"""

from __future__ import annotations

import csv
import io
from urllib.parse import urlsplit

import httpx

_CKAN_BASE = "https://opendata.muenchen.de"
_WFS_HOST = "geoportal.muenchen.de"
_WFS_URL = "https://geoportal.muenchen.de/geoserver/mor_wfs/ows"
_ALLOWED_RESOURCE_HOSTS = {"opendata.muenchen.de"}

# CKAN-Paketname der jaehrlichen Raddauerzaehl-Tageswerte (Jahr wird angehaengt).
_PACKAGE_PREFIX = "daten-der-raddauerzaehlstellen-muenchen-"


async def _fetch_stations(http: httpx.AsyncClient) -> list[dict]:
    """Holt die Stationsstammdaten (Name, Koordinaten, Richtungslabels) per WFS."""
    resp = await http.get(
        _WFS_URL,
        params={
            "service": "WFS",
            "version": "1.0.0",
            "request": "GetFeature",
            "typeName": "mor_wfs:raddauerzaehlstellen",
            "outputFormat": "application/json",
            "srsName": "EPSG:4326",
        },
    )
    resp.raise_for_status()
    body = resp.json()
    features = body.get("features", []) if isinstance(body, dict) else []
    stations: list[dict] = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties") or {}
        name = props.get("zaehlstelle")
        if not name:
            continue
        try:
            lat = (
                float(props["latitude"]) if props.get("latitude") is not None else None
            )
            lon = (
                float(props["longitude"])
                if props.get("longitude") is not None
                else None
            )
        except (TypeError, ValueError):
            lat = lon = None
        stations.append(
            {
                "zaehlstelle": name,
                "name_long": props.get("zaehlstelle_lang"),
                "lat": lat,
                "lon": lon,
                "direction_1": props.get("richtung_1"),
                "direction_2": props.get("richtung_2"),
            }
        )
    return stations


async def _latest_daily_csv_url(http: httpx.AsyncClient, *, year: int) -> str | None:
    """Ermittelt die URL der juengsten ``*_tage``-CSV des Jahres-CKAN-Pakets."""
    resp = await http.get(
        f"{_CKAN_BASE}/api/3/action/package_show",
        params={"id": f"{_PACKAGE_PREFIX}{year}"},
    )
    # Paket des Jahres existiert evtl. noch nicht (Jahresanfang) -> kein CSV.
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    body = resp.json()
    result = body.get("result") if isinstance(body, dict) else None
    resources = result.get("resources") if isinstance(result, dict) else None
    if not isinstance(resources, list):
        return None
    # Kandidaten: Ressourcen, deren Download-URL auf "_tage.csv" endet. Die
    # lexikografisch groesste rad_JJJJ_MM_tage.csv ist der juengste Monat.
    candidates: list[str] = []
    for resource in resources:
        if not isinstance(resource, dict):
            continue
        url = resource.get("url")
        if isinstance(url, str) and url.lower().endswith("_tage.csv"):
            candidates.append(url)
    if not candidates:
        return None
    return max(candidates, key=lambda u: u.rsplit("/", 1)[-1])


def _parse_latest_day(text: str) -> dict[str, dict]:
    """Parst die Tages-CSV und liefert je Station die Zeile des juengsten Datums.

    Rueckgabe: ``{zaehlstelle: {value, direction_1_value, direction_2_value,
    datum}}``. ``gesamt``/``richtung_*`` werden defensiv zu int geparst (sonst
    None). Komma-getrennt, UTF-8 (BOM wird von ``utf-8-sig`` entfernt).
    """
    reader = csv.DictReader(io.StringIO(text))
    by_station_date: dict[str, dict] = {}
    latest_datum = ""
    for row in reader:
        datum = (row.get("datum") or "").strip()
        if not datum:
            continue
        if datum > latest_datum:
            latest_datum = datum
    if not latest_datum:
        return {}
    # zweiter Durchlauf: nur die Zeilen des juengsten Datums (CSV ist klein).
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        if (row.get("datum") or "").strip() != latest_datum:
            continue
        station = (row.get("zaehlstelle") or "").strip()
        if not station:
            continue

        def _int(value: object) -> int | None:
            try:
                return int(str(value).strip())
            except (TypeError, ValueError):
                return None

        by_station_date[station] = {
            "value": _int(row.get("gesamt")),
            "direction_1_value": _int(row.get("richtung_1")),
            "direction_2_value": _int(row.get("richtung_2")),
            "datum": latest_datum,
        }
    return by_station_date


async def fetch_muenchen_radzaehl(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float,
    lon: float,
    radius_km: float = 30.0,
    year: int,
) -> dict:
    """Holt die Muenchner Rad-Tageszaehlwerte (WFS-Standorte + juengste Tages-CSV).

    Step 1: WFS-Standorte (Name/Koordinaten/Richtungslabels). Step 2a: juengste
    ``*_tage``-CSV-URL aus dem Jahres-CKAN-Paket ermitteln (SSRF-Allowlist-Pruefung
    der entdeckten URL), Step 2b: CSV laden und je Station die Zeile des juengsten
    ``datum`` extrahieren. Join ueber den Stationsnamen (``zaehlstelle``). Fehlt der
    CSV-Wert (nicht erreichbar/Station nicht in CSV), bleibt ``value=None``.

    ``lat``/``lon``/``radius_km`` sind vertragskonform Teil der Signatur (alle
    Stadt-Adapter teilen sie), Muenchen liefert den kompletten Stadt-Datensatz.
    ``year`` (keyword-only) waehlt das Jahres-CKAN-Paket (kommt aus ``retrieved_at``,
    damit der Adapter rein bleibt).

    Rueckgabe-Keys (exakt das, was ``map_muenchen_radzaehl`` erwartet): ``slug``,
    ``stations`` (je Station Stammdaten + Tageswert) und ``as_of`` (juengstes
    Datum als ISO-String oder None).
    """
    stations = await _fetch_stations(http)
    # Ohne Stationen (WFS leer) gibt es nichts zu joinen -> kein CSV-Fetch noetig
    # (der Endpunkt liefert dann ehrlich no_data).
    if not stations:
        return {"slug": slug, "stations": [], "as_of": None}

    daily: dict[str, dict] = {}
    csv_url = await _latest_daily_csv_url(http, year=year)
    if csv_url:
        discovered_host = urlsplit(csv_url).hostname
        if discovered_host not in _ALLOWED_RESOURCE_HOSTS:
            raise ValueError(
                f"entdeckte Ressourcen-URL nicht in der Allowlist: {csv_url!r}"
            )
        csv_resp = await http.get(csv_url)
        csv_resp.raise_for_status()
        daily = _parse_latest_day(
            csv_resp.content.decode("utf-8-sig", errors="replace")
        )

    as_of: str | None = None
    enriched: list[dict] = []
    for station in stations:
        values = daily.get(station["zaehlstelle"]) or {}
        if values.get("datum"):
            as_of = values["datum"]
        enriched.append({**station, **values})

    return {"slug": slug, "stations": enriched, "as_of": as_of}
