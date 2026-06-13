"""Keyloser DWD-Adapter fetch_weather ueber Bright Sky (DATA-03).

Laedt aktuelle Wetterdaten von der keylosen Bright-Sky-API
(``current_weather``) ueber den gepoolten httpx-Client und liefert ein flaches
raw-dict mit den Keys ``slug``/``lat``/``lon``/``temperature_c``/``humidity``/
``wind_speed``/``condition``/``observed_at``/``dwd_station_id``, das der reine
``map_weather``-Mapper erwartet. ``dwd_station_id`` stammt aus dem Bright-Sky-Feld
``sources[0].dwd_station_id`` und wird als stabile Mess-Stations-ID an die
``WeatherPayload.station_id`` durchgereicht (ARCH-02 Join-Key); fehlt die Quelle,
bleibt der Wert ``None``.

Der Adapter ist rein gegenueber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade). ``resp.raise_for_status()`` ist Pflicht,
damit ein 5xx als ``httpx.HTTPError`` an die Fassade durchschlaegt und der
STALE-ON-ERROR-Pfad greift.

Sicherheit (T-05-03, SSRF): Der Host ist in ``_BASE`` hartkodiert; lat/lon
stammen aus dem validierten Register (``entry.geo``) und werden nur als
Query-Parameter uebergeben. Es wird ausschliesslich der lat/lon-Weg genutzt,
``dwd_station_ids`` werden NICHT befuellt (A3).
"""

from __future__ import annotations

import httpx

_BASE = "https://api.brightsky.dev/current_weather"


async def fetch_weather(
    http: httpx.AsyncClient, *, slug: str, lat: float, lon: float
) -> dict:
    """Holt aktuelle DWD/Bright-Sky-Wetterdaten und liefert das flache raw-dict.

    Rueckgabe-Keys (exakt das, was ``map_weather`` erwartet): ``slug``, ``lat``,
    ``lon``, ``temperature_c``, ``humidity``, ``wind_speed``, ``condition``,
    ``observed_at``, ``dwd_station_id``. Der Host ist hartkodiert (SSRF-Schutz,
    T-05-03); lat/lon fliessen nur als Query-Parameter ein. ``dwd_station_id``
    kommt robust aus ``sources[0].dwd_station_id`` (fehlt das Feld -> ``None``).
    """
    resp = await http.get(_BASE, params={"lat": lat, "lon": lon})
    resp.raise_for_status()
    body = resp.json()
    w = body["weather"]
    sources = body.get("sources") or []
    dwd_station_id = sources[0].get("dwd_station_id") if sources else None
    return {
        "slug": slug,
        "lat": lat,
        "lon": lon,
        "temperature_c": w.get("temperature"),
        "humidity": w.get("relative_humidity"),
        "wind_speed": w.get("wind_speed"),
        "condition": w.get("condition"),
        "observed_at": w.get("timestamp"),
        "dwd_station_id": dwd_station_id,
    }
