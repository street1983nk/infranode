"""Muenchen-CKAN-2-Step-Adapter fetch_muenchen_road_events (DATA-15, Tier A).

Korrektur [VERIFIED 2026-06-10]: der alte Direkt-Aufruf
``datastore_search?resource_id=baustellen-muenchen`` lieferte IMMER 404 (der
Adapter hat nie Daten geliefert). Die echte Quelle ist das CKAN-Paket
``baustellen_4_weeks_opendata`` auf ``opendata.muenchen.de``; der Adapter folgt
jetzt dem zweistufigen CKAN-Pfad (package_show -> GeoJSON-Ressourcen-URL ->
Daten-Fetch, analog zum hamburg_transparenz-Adapter / Plan 09-03). Die
GeoJSON-Ressource ist ein WFS auf ``geoportal.muenchen.de``
(``typeName=mor_wfs:baustellen_opendata``, ``outputFormat=application/json``);
WICHTIG: ``srsName=EPSG:4326`` wird angehaengt, sonst liefert der GeoServer
EPSG:25832 (UTM).

Properties [VERIFIED 2026-06-10] per Live-Probe: ``art``, ``beschreibung``,
``beginn_datum_kombiniert``/``ende_datum_kombiniert`` (statt von/bis),
``strasse_hausnr`` (statt strasse), ``betroffene_bereiche`` (statt abschnitt).
Die Geometrie ist Polygon ODER MultiPolygon; fuer ``lat``/``lon`` wird defensiv
die erste Ring-Koordinate als repraesentativer Punkt genommen (Koordinaten
[lon, lat] dank ``srsName=EPSG:4326``).

Sicherheit (T-9-02 SSRF, Tampering): Der CKAN-Host ist in ``_BASE`` hartkodiert.
Die in Step 1 entdeckte Ressourcen-URL ist Upstream-gelieferter Input; ihr Host
MUSS in der hartkodierten Allowlist ``_ALLOWED_HOSTS`` liegen
(``opendata.muenchen.de`` + ``geoportal.muenchen.de``), sonst ``ValueError``
(genesis.py-Muster) und es ergeht KEIN Request gegen einen fremden Host.

DoS-Schutz (T-9-DOS): ``resp.raise_for_status()`` in beiden Steps, damit ein 5xx
als ``httpx.HTTPError`` an die Fassade durchschlaegt und der STALE-ON-ERROR-Pfad
greift.

Datenfehler-Schutz (T-9-02): Jeder Zugriff ist ``.get()``/``[]``-defensiv mit
None-Fallback, daher kein ``KeyError`` bei fehlenden oder anders benannten
Feldern; die Punkt-Extraktion faengt jede abweichende Geometrie-Struktur ab.

Der Adapter ist rein gegenueber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade).
"""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx

# CKAN-Host hartkodiert (T-9-02 SSRF): nur das Muenchner Open-Data-Portal.
_BASE = "https://opendata.muenchen.de"

# Hartkodierte Allowlist der erlaubten Ressourcen-Hosts (genesis.py-Muster,
# T-9-02): die in Step 1 entdeckte Ressourcen-URL MUSS auf einen dieser Hosts
# zeigen, sonst raise ValueError (kein roher Upstream-Host als Ziel-URL).
# geoportal.muenchen.de [VERIFIED 2026-06-10]: Host des WFS (GeoServer), auf den
# die GeoJSON-Ressource des CKAN-Pakets zeigt.
_ALLOWED_HOSTS = {
    "opendata.muenchen.de",
    "geoportal.muenchen.de",
}

# [VERIFIED 2026-06-10] CKAN-Paket der Muenchner Baustellen (package_show
# bestaetigt, license_id dl-by-de/2.0, Mobilitaetsreferat). Die alte
# datastore_search-Ressourcen-ID "baustellen-muenchen" war tot (404).
_PACKAGE_ID = "baustellen_4_weeks_opendata"

# [VERIFIED 2026-06-10] Format-Match: das Paket fuehrt genau eine Ressource mit
# format "GeoJSON" (WFS-GetFeature mit outputFormat=application/json).
_RESOURCE_FORMAT = "geojson"

# [VERIFIED 2026-06-10] WICHTIG: die Ressourcen-URL traegt KEIN srsName; ohne
# diesen Param liefert der GeoServer EPSG:25832 (UTM) statt WGS84.
_SRS_PARAM = "srsName=EPSG:4326"

# [VERIFIED 2026-06-10]-properties-Feldnamen per Live-Probe gegen den WFS.
# Defensiv per .get() gelesen -> None-Fallback statt KeyError (T-9-02).
_FIELD_STRASSE = "strasse_hausnr"  # [VERIFIED 2026-06-10] Strasse + Hausnummern
_FIELD_BEREICHE = "betroffene_bereiche"  # [VERIFIED 2026-06-10] z. B. "Fahrbahn"
_FIELD_ART = "art"  # [VERIFIED 2026-06-10] z. B. "Baumassnahme"
_FIELD_BESCHREIBUNG = "beschreibung"  # [VERIFIED 2026-06-10] Beschreibungstext
_FIELD_VON = "beginn_datum_kombiniert"  # [VERIFIED 2026-06-10] z. B. "15.06.2026"
_FIELD_BIS = "ende_datum_kombiniert"  # [VERIFIED 2026-06-10] z. B. "17.07.2026"


def _representative_point(geometry: dict) -> tuple[float | None, float | None]:
    """Liefert (lon, lat) als repraesentativen Punkt einer GeoJSON-Geometrie.

    [VERIFIED 2026-06-10]: der WFS liefert Polygon ODER MultiPolygon. Es wird
    defensiv in die verschachtelten Koordinaten-Listen abgestiegen, bis die
    erste ``[lon, lat]``-Koordinate erreicht ist (erste Ringkoordinate).
    Abweichende Strukturen -> (None, None) statt Crash (T-9-02).
    """
    node = geometry.get("coordinates") if isinstance(geometry, dict) else None
    # Maximal 4 Ebenen (MultiPolygon): Polygone -> Ringe -> Koordinaten -> Zahl.
    for _ in range(4):
        if not (isinstance(node, list) and node):
            return None, None
        if isinstance(node[0], int | float):
            if len(node) >= 2 and isinstance(node[1], int | float):
                return float(node[0]), float(node[1])
            return None, None
        node = node[0]
    return None, None


async def fetch_muenchen_road_events(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float,
    lon: float,
    radius_km: float = 30.0,
) -> dict:
    """Holt Muenchen-Baustellen/Sperrungen ueber den CKAN-2-Step-Pfad.

    Step 1: GET ``{_BASE}/api/3/action/package_show?id={_PACKAGE_ID}`` und aus
    ``result.resources`` per ``format``-Match die GeoJSON-Ressource waehlen,
    deren ``url`` lesen ([VERIFIED 2026-06-10]: WFS auf geoportal.muenchen.de,
    ``typeName=mor_wfs:baustellen_opendata``). Step 2: die entdeckte ``url``
    gegen ``_ALLOWED_HOSTS`` pruefen (genesis.py-Muster, sonst ``ValueError``,
    T-9-02), ``srsName=EPSG:4326`` anhaengen (sonst UTM!), dann GET und aus
    ``features`` je ``properties`` ein schlankes Event-dict bauen (Felder
    defensiv per ``.get()`` mit None-Fallback). ``resp.raise_for_status()`` in
    beiden Steps.

    ``lat``/``lon``/``radius_km`` sind Vertrags-konform Teil der Signatur (alle
    Stadt-Adapter teilen sie); Muenchen liefert den kompletten Stadt-Datensatz,
    daher werden sie hier nicht zur serverseitigen Filterung benutzt.

    Rueckgabe-Keys (exakt das, was ``map_muenchen_road_events`` erwartet):
    ``slug`` und ``events``.
    """
    # Step 1: CKAN package_show -> Ressourcen-Metadaten ([VERIFIED 2026-06-10]).
    pkg_resp = await http.get(
        f"{_BASE}/api/3/action/package_show",
        params={"id": _PACKAGE_ID},
    )
    pkg_resp.raise_for_status()

    body = pkg_resp.json()
    result = body.get("result") if isinstance(body, dict) else None
    resources = result.get("resources") if isinstance(result, dict) else None
    if not isinstance(resources, list):
        resources = []

    # GeoJSON-Ressource per Format-Match waehlen ([VERIFIED 2026-06-10]).
    # Defensiv: erste Ressource, deren format den Match-Substring (case-
    # insensitiv) enthaelt.
    resource_url: str | None = None
    for resource in resources:
        if not isinstance(resource, dict):
            continue
        fmt = str(resource.get("format") or "").lower()
        url = resource.get("url")
        if _RESOURCE_FORMAT in fmt and isinstance(url, str) and url:
            resource_url = url
            break

    if not resource_url:
        # Kein passendes Format gefunden -> leere Event-Liste statt Crash.
        return {"slug": slug, "events": []}

    # T-9-02 SSRF: die entdeckte Ressourcen-URL gegen die Allowlist pruefen
    # (genesis.py-Muster). Fremder Host -> ValueError, KEIN Request.
    discovered_host = urlsplit(resource_url).hostname
    if discovered_host not in _ALLOWED_HOSTS:
        raise ValueError(
            f"entdeckte Ressourcen-URL nicht in der Allowlist: {resource_url!r}"
        )

    # [VERIFIED 2026-06-10]: srsName=EPSG:4326 anhaengen, sonst kommt das
    # Service-CRS EPSG:25832 (UTM) und lat/lon waeren Unsinn.
    if "srsname=" not in resource_url.lower():
        separator = "&" if "?" in resource_url else "?"
        resource_url = f"{resource_url}{separator}{_SRS_PARAM}"

    # Step 2: GET der entdeckten WFS-GeoJSON-Ressource.
    data_resp = await http.get(resource_url)
    data_resp.raise_for_status()

    geo = data_resp.json()
    features = geo.get("features", []) if isinstance(geo, dict) else []
    events: list[dict] = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        feature_lon, feature_lat = _representative_point(geometry)
        # T-9-02: fehlendes Feld -> None (kein KeyError).
        events.append(
            {
                "strasse_hausnr": props.get(_FIELD_STRASSE),
                "betroffene_bereiche": props.get(_FIELD_BEREICHE),
                "art": props.get(_FIELD_ART),
                "beschreibung": props.get(_FIELD_BESCHREIBUNG),
                "von": props.get(_FIELD_VON),
                "bis": props.get(_FIELD_BIS),
                "lat": feature_lat,
                "lon": feature_lon,
            }
        )

    return {"slug": slug, "events": events}
