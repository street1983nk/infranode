"""StaDa-Station-Data-Adapter ``fetch_all_stations`` (DATA-36, Live, Tier A).

Bahnhofs-Stammdaten der Deutschen Bahn aus der offenen StaDa-API (DB API
Marketplace, Produkt "StaDa - Station Data", CC BY 4.0 = Tier A). Holt die
KOMPLETTE bundesweite Bahnhofsliste in einem Abruf und normalisiert sie zu
schlanken dicts. Die Zuordnung Bahnhof -> Stadt erfolgt NICHT hier, sondern in
der Route ueber den amtlichen Gemeindeschluessel (StaDa ``municipalityCode`` ==
Stadt-``ags``); deshalb wird die Liste EINMAL geholt + via Resilienz-Fassade lange
gecacht und je Stadt gefiltert (ein Abruf bedient alle 84 Staedte).

Je Bahnhof wird die Haupt-EVA (``isMain``, sonst die erste) samt Geokoordinate
extrahiert; Bahnhoefe ohne EVA werden uebersprungen (ohne EVA kein Board).

Sicherheit:
- T-05-08 (SSRF): Host hartkodiert (DB-API-Marketplace-Gateway); kein User-Input
  in der URL (eine feste Listen-URL).
- T-08-CRED: Client-Id/Api-Key gehen NUR in die Request-Header, nie in
  Cache-Key/Response/Log.

Der Adapter ist rein gegenueber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` und kennt KEIN Cache/Breaker (Resilienz-Fassade in der Route).
``raise_for_status`` ist Pflicht (5xx -> STALE-ON-ERROR).
"""

from __future__ import annotations

import httpx

# Host hartkodiert (SSRF, T-05-08): der DB-API-Marketplace-Gateway, Produkt StaDa.
_BASE = "https://apis.deutschebahn.com/db-api-marketplace/apis/station-data/v2/stations"
# StaDa liefert bundesweit ~5400 Bahnhoefe; ein grosszuegiges Limit holt alle in
# einem Abruf (die API deckelt selbst bei 10000).
_LIMIT = 10000


def _main_eva(station: dict) -> dict | None:
    """Waehlt die Haupt-EVA (``isMain``, sonst die erste); None ohne EVA."""
    evas = station.get("evaNumbers") or []
    if not evas:
        return None
    for eva in evas:
        if eva.get("isMain"):
            return eva
    return evas[0]


def _normalize(station: dict) -> dict | None:
    """Bildet ein StaDa-Bahnhofsobjekt auf ein schlankes dict ab; None ohne EVA."""
    eva = _main_eva(station)
    if eva is None or eva.get("number") is None:
        return None
    coords = (eva.get("geographicCoordinates") or {}).get("coordinates") or []
    lat = coords[1] if len(coords) == 2 else None
    lon = coords[0] if len(coords) == 2 else None
    addr = station.get("mailingAddress") or {}
    return {
        "eva": str(eva["number"]),
        "name": station.get("name"),
        "category": station.get("category"),
        "lat": lat,
        "lon": lon,
        "zip": addr.get("zipcode"),
        # Amtlicher Gemeindeschluessel = Zuordnungsschluessel zur Stadt (== ags).
        "ags": station.get("municipalityCode"),
    }


async def fetch_all_stations(
    http: httpx.AsyncClient,
    *,
    client_id: str,
    api_key: str,
) -> dict:
    """Holt die komplette StaDa-Bahnhofsliste und normalisiert sie.

    Rueckgabe: ``{"stations": [ {eva, name, category, lat, lon, zip, ags}, ... ]}``
    (bundesweit, ungefiltert). Die Stadt-Filterung (``ags``) macht die Route.
    ``raise_for_status`` Pflicht (Resilienz-Fassade).
    """
    headers = {
        "DB-Client-Id": client_id,
        "DB-Api-Key": api_key,
        "Accept": "application/json",
    }
    resp = await http.get(_BASE, params={"limit": _LIMIT}, headers=headers)
    resp.raise_for_status()
    body = resp.json()
    result = body.get("result", []) if isinstance(body, dict) else []
    stations = [s for s in (_normalize(st) for st in result) if s is not None]
    return {"stations": stations}
