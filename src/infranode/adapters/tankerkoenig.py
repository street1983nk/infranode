"""Tankerkoenig-Adapter ``fetch_fuel_prices`` (DATA-30, Live, Tier A).

Aktuelle Spritpreise je Stadt aus der offenen Tankerkönig-API (MTS-K-Daten der
Markttransparenzstelle für Kraftstoffe), aggregiert von einzelnen Tankstellen
auf eine Stadt-Kennzahl (Durchschnitts- und Minimal-Preis je Sorte im Umkreis):

- GET ``/json/list.php?lat&lng&rad&sort=dist&type=all&apikey=<key>`` liefert je
  Tankstelle im Radius ``rad`` (km) um die Stadtkoordinate ein flaches Record mit
  ``id``/``name``/``brand``/``diesel``/``e5``/``e10``/``isOpen``/``dist``. Die
  Stadtkoordinate stammt aus dem Register (lat/lng), der Key kommt als Parameter
  (NIE in Cache-Key/Response/Log).

Rückgabe ist das raw-dict, das ``map_fuel_prices`` erwartet: ``slug``,
``radius_km``, ``station_count`` (alle Tankstellen im Radius), ``open_count``
(davon geöffnet), die Aggregate ``avg_e5``/``avg_e10``/``avg_diesel`` und
``min_e5``/``min_e10``/``min_diesel`` (nur über geöffnete Tankstellen mit
gültigem Preis) sowie ``stations`` (je Tankstelle ein schlankes dict). Der
Adapter baut KEINEN ``CanonicalRecord`` und kennt KEIN Cache/Breaker (das liefert
die Resilienz-Fassade). ``resp.raise_for_status()`` ist Pflicht (5xx -> Fassade
STALE-ON-ERROR).

Lizenz: CC BY 4.0 (creativecommons.tankerkoenig.de) = Tier A.

Sicherheit:
- T-05-08 (SSRF): Der Host ist in ``_BASE`` hartkodiert; es fließen nur die
  validierten Register-Koordinaten + der feste Radius in die Query.
- T-08-CRED: Der Key geht NUR in den Query-Parameter ``apikey``, nie in
  Rueckgabe/Log; der Cache-Key (Route) trägt ihn nicht.
"""

from __future__ import annotations

import httpx

# Host hartkodiert (SSRF-Schutz, T-05-08).
_BASE = "https://creativecommons.tankerkoenig.de/json"
# Umkreis um die Stadtkoordinate (km). Tankerkönig erlaubt max. 25; 5 km deckt
# das Stadtgebiet der großen Städte mit ausreichend Tankstellen ab.
_RADIUS_KM = 5.0
_FUELS = ("e5", "e10", "diesel")


def _price(value: object) -> float | None:
    """Gibt einen positiven Preis als float zurück, sonst None (rein).

    Tankerkönig liefert fehlende Preise als ``false`` oder ``0`` -> None.
    """
    if isinstance(value, bool):  # ``True``/``False`` ist kein Preis (bool < int!).
        return None
    if isinstance(value, int | float) and value > 0:
        return float(value)
    return None


def _station(rec: dict) -> dict:
    """Bildet ein Tankerkönig-Record auf ein schlankes station-dict ab (rein)."""
    return {
        "station_id": rec.get("id"),
        "name": rec.get("name"),
        "brand": rec.get("brand"),
        "e5": _price(rec.get("e5")),
        "e10": _price(rec.get("e10")),
        "diesel": _price(rec.get("diesel")),
        "is_open": bool(rec.get("isOpen")),
        "dist_km": rec.get("dist"),
    }


def _aggregate(stations: list[dict], fuel: str) -> tuple[float | None, float | None]:
    """Durchschnitt und Minimum eines Kraftstoffpreises über offene Stationen (rein).

    Berücksichtigt nur geöffnete Tankstellen mit gültigem Preis (geschlossene
    führen oft veraltete/leere Preise). Keine gültigen Preise -> (None, None).
    """
    prices = [s[fuel] for s in stations if s["is_open"] and s[fuel] is not None]
    if not prices:
        return None, None
    return round(sum(prices) / len(prices), 3), round(min(prices), 3)


async def fetch_fuel_prices(
    http: httpx.AsyncClient, *, slug: str, lat: float, lon: float, apikey: str
) -> dict:
    """Holt die Live-Spritpreise im Umkreis der Stadt und aggregiert sie.

    Rückgabe-Keys (exakt das, was ``map_fuel_prices`` erwartet): ``slug``,
    ``radius_km``, ``station_count``, ``open_count``, ``avg_e5``/``avg_e10``/
    ``avg_diesel``, ``min_e5``/``min_e10``/``min_diesel`` und ``stations`` (Liste
    schlanker dicts). Keine Tankstelle im Radius -> alle Aggregate None,
    ``station_count`` 0 (die Route mappt das auf ``no_data``). ``raise_for_status``
    ist Pflicht (5xx -> Fassade STALE-ON-ERROR).
    """
    resp = await http.get(
        f"{_BASE}/list.php",
        params={
            "lat": lat,
            "lng": lon,
            "rad": _RADIUS_KM,
            "sort": "dist",
            "type": "all",
            "apikey": apikey,
        },
    )
    resp.raise_for_status()
    body = resp.json()

    records = body.get("stations", []) or []
    stations = [_station(rec) for rec in records if isinstance(rec, dict)]
    open_count = sum(1 for s in stations if s["is_open"])

    raw: dict = {
        "slug": slug,
        "radius_km": _RADIUS_KM,
        "station_count": len(stations),
        "open_count": open_count,
        "stations": stations,
    }
    for fuel in _FUELS:
        avg, low = _aggregate(stations, fuel)
        raw[f"avg_{fuel}"] = avg
        raw[f"min_{fuel}"] = low
    return raw
