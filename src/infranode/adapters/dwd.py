"""Keyloser DWD-Adapter fetch_weather über Bright Sky (DATA-03).

Lädt aktuelle Wetterdaten von der keylosen Bright-Sky-API
(``current_weather``) über den gepoolten httpx-Client und liefert ein flaches
raw-dict mit den Keys ``slug``/``lat``/``lon``/``temperature_c``/``humidity``/
``wind_speed``/``condition``/``observed_at``/``dwd_station_id``, das der reine
``map_weather``-Mapper erwartet. ``dwd_station_id`` stammt aus dem Bright-Sky-Feld
``sources[0].dwd_station_id`` und wird als stabile Mess-Stations-ID an die
``WeatherPayload.station_id`` durchgereicht (ARCH-02 Join-Key); fehlt die Quelle,
bleibt der Wert ``None``.

Der Adapter ist rein gegenüber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade). ``resp.raise_for_status()`` ist Pflicht,
damit ein 5xx als ``httpx.HTTPError`` an die Fassade durchschlägt und der
STALE-ON-ERROR-Pfad greift.

Sicherheit (T-05-03, SSRF): Der Host ist in ``_BASE`` hartkodiert; lat/lon
stammen aus dem validierten Register (``entry.geo``) und werden nur als
Query-Parameter übergeben. Es wird ausschließlich der lat/lon-Weg genutzt,
``dwd_station_ids`` werden NICHT befüllt (A3).
"""

from __future__ import annotations

import httpx

_BASE = "https://api.brightsky.dev/current_weather"


async def fetch_weather(
    http: httpx.AsyncClient, *, slug: str, lat: float, lon: float
) -> dict:
    """Holt aktuelle DWD/Bright-Sky-Wetterdaten und liefert das flache raw-dict.

    Rückgabe-Keys (exakt das, was ``map_weather`` erwartet): ``slug``, ``lat``,
    ``lon``, ``temperature_c``, ``humidity``, ``wind_speed``, ``condition``,
    ``observed_at``, ``dwd_station_id``. Die Windgeschwindigkeit (km/h) kommt aus
    ``wind_speed_10`` mit Fallback ``_30``/``_60`` (Bright Sky liefert kein flaches
    ``wind_speed``, siehe ``_wind_speed``/Audit K3). Der Host ist hartkodiert
    (SSRF-Schutz, T-05-03); lat/lon fließen nur als Query-Parameter ein.
    ``dwd_station_id`` kommt robust aus ``sources[0].dwd_station_id`` (fehlt das
    Feld -> ``None``).
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
        "wind_speed": _wind_speed(w),
        "condition": w.get("condition"),
        "observed_at": w.get("timestamp"),
        "dwd_station_id": dwd_station_id,
    }


def _wind_speed(w: dict) -> float | None:
    """Liest die aktuelle Windgeschwindigkeit (km/h) aus dem Bright-Sky-weather-dict.

    KRITISCH (Audit K3): Bright Sky liefert im ``current_weather`` KEIN flaches
    ``wind_speed``, sondern die Mittelungs-Fenster ``wind_speed_10``/``_30``/``_60``
    (Mittel über die letzten 10/30/60 Minuten, jeweils in km/h). Das früher
    gelesene ``wind_speed`` existiert dort nicht und lieferte für JEDE Stadt
    ``None``. Wir nehmen das kürzeste verfügbare Fenster (``_10`` = aktuellster
    Mittelwert) mit Fallback auf ``_30``/``_60`` und zuletzt auf das historische
    flache ``wind_speed`` (Abwaertskompatibilitaet/aeltere Fixtures).
    """
    for key in ("wind_speed_10", "wind_speed_30", "wind_speed_60", "wind_speed"):
        value = w.get(key)
        if value is not None:
            return value
    return None
