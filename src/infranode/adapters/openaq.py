"""Keyabhaengiger OpenAQ-Adapter fetch_air (DATA-02, Tier C live-only).

Zweistufiger Zugriff auf die OpenAQ-v3-API:
- GET ``/v3/locations?coordinates={lat},{lon}&radius={r}`` mit ``X-API-Key``-Header
  liefert die Messstationen im Umkreis; gewaehlt wird die erste (naechste) location_id,
- GET ``/v3/locations/{id}/latest`` liefert die aktuellen Messwerte; aus dem
  ``results``-Array werden pm10/no2/pm25/o3/so2 + observed_at robust extrahiert.

Rueckgabe ist ein flaches raw-dict mit den Keys ``slug``/``lat``/``lon``/``pm10``/
``no2``/``pm25``/``o3``/``so2``/``observed_at``/``location_id``, das der reine
``map_openaq_air``-Mapper erwartet. ``location_id`` (die intern ohnehin aus
``results[0].id`` gewaehlte Mess-Station) wird als stabile Stations-ID an die
``AirQualityPayload.station_id`` durchgereicht (ARCH-02 Join-Key). Der Adapter
baut KEINEN ``CanonicalRecord`` und kennt KEIN Cache/Breaker
(das liefert die Resilienz-Fassade). ``resp.raise_for_status()`` ist nach JEDEM Call
Pflicht, damit ein 5xx als ``httpx.HTTPError`` an die Fassade durchschlaegt und der
STALE-ON-ERROR-Pfad greift.

Sicherheit:
- T-05-06 (Information Disclosure): Der API-Key wird ausschliesslich als
  ``X-API-Key``-Header gesendet, NIE geloggt und NIE ins raw-dict aufgenommen.
- T-05-08 (SSRF): Der Host ist in ``_BASE`` hartkodiert; lat/lon stammen aus dem
  validierten Register und fliessen nur als Query-Parameter ein, die location_id
  stammt aus der Upstream-Antwort und wird nur als Pfadsegment interpoliert.
"""

from __future__ import annotations

import asyncio

import httpx

# Host hartkodiert (SSRF-Schutz, T-05-08).
_BASE = "https://api.openaq.org/v3"

# radius ist Pflicht und <= 25000 m (Pitfall 5); 12 km deckt das Stadtgebiet ab.
_DEFAULT_RADIUS_M = 25000
_MAX_RADIUS_M = 25000

# Schadstoff-Parameter, die wir aus dem latest-Array uebernehmen.
_PARAMETERS = ("pm10", "no2", "pm25", "o3", "so2")


async def _get_with_retry(
    http: httpx.AsyncClient,
    url: str,
    *,
    headers: dict,
    params: dict | None = None,
    max_retries: int = 2,
) -> httpx.Response:
    """GET mit 429-Retry (Rate-Limit-aware): respektiert Retry-After (cap 3s).

    OpenAQ rate-limitet pro API-Key. Statt 429 direkt als Fehler durchzureichen
    (-> Breaker/503), wird bis zu max_retries-mal mit Backoff erneut versucht.
    """
    resp = await http.get(url, params=params, headers=headers)
    attempt = 0
    while resp.status_code == 429 and attempt < max_retries:
        ra = resp.headers.get("Retry-After")
        try:
            delay = float(ra) if ra else 1.0
        except ValueError:
            delay = 1.0
        await asyncio.sleep(min(delay, 3.0))
        resp = await http.get(url, params=params, headers=headers)
        attempt += 1
    resp.raise_for_status()
    return resp


async def fetch_air(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float,
    lon: float,
    api_key: str,
    radius_m: int = _DEFAULT_RADIUS_M,
) -> dict:
    """Holt aktuelle OpenAQ-Luftdaten zur Koordinate und liefert das flache raw-dict.

    Rueckgabe-Keys (exakt das, was ``map_openaq_air`` erwartet): ``slug``, ``lat``,
    ``lon``, ``pm10``, ``no2``, ``pm25``, ``o3``, ``so2``, ``observed_at``,
    ``location_id``. Der ``api_key`` wird vom Caller via
    ``SecretStr.get_secret_value()`` uebergeben und NUR als ``X-API-Key``-Header
    verwendet (T-05-06: nie geloggt, nie in der Rueckgabe). ``location_id`` ist die
    gewaehlte naechste Messstation (Open-Data, kein Secret).
    """
    headers = {"X-API-Key": api_key}

    # Stufe 1: naechste Messstation im Umkreis. coordinates+radius sind Pflicht.
    loc_resp = await _get_with_retry(
        http,
        f"{_BASE}/locations",
        params={
            "coordinates": f"{lat},{lon}",
            "radius": min(radius_m, _MAX_RADIUS_M),
        },
        headers=headers,
    )
    results = loc_resp.json().get("results", [])
    if not results:
        # Keine OpenAQ-Messstation im Umkreis: KEIN Upstream-Fehler, sondern
        # schlicht keine Daten (viele kleinere Staedte; UBA/air-uba deckt diese ab).
        # Sentinel mit location_id=None -> Handler liefert 200 source_status=no_data.
        return {
            "slug": slug,
            "lat": lat,
            "lon": lon,
            "pm10": None,
            "no2": None,
            "pm25": None,
            "o3": None,
            "so2": None,
            "observed_at": None,
            "location_id": None,
        }
    location_id = results[0]["id"]

    # Stufe 2: aktuelle Messwerte der gewaehlten Station.
    latest_resp = await _get_with_retry(
        http, f"{_BASE}/locations/{location_id}/latest", headers=headers
    )
    measurements = latest_resp.json().get("results", [])

    values: dict[str, float | None] = {p: None for p in _PARAMETERS}
    observed_at: str | None = None
    for entry in measurements:
        param = entry.get("parameter")
        if param in values:
            values[param] = entry.get("value")
        if observed_at is None:
            observed_at = (entry.get("datetime") or {}).get("utc")

    return {
        "slug": slug,
        "lat": lat,
        "lon": lon,
        "pm10": values["pm10"],
        "no2": values["no2"],
        "pm25": values["pm25"],
        "o3": values["o3"],
        "so2": values["so2"],
        "observed_at": observed_at,
        # location_id ist eine oeffentliche Stations-ID (kein Secret); der API-Key
        # bleibt ausschliesslich im Header (T-05-06).
        "location_id": str(location_id),
    }
