"""ParkenDD-Adapter fetch_parkendd (DATA-40, Live-Parkhaus-Belegung, Tier C).

ParkenDD (https://api.parkendd.de, https://github.com/ParkenDD) ist ein offener
Aggregator, der die Parkhaus-Belegung vieler deutscher Städte aus deren
amtlichen Parkleitsystemen bündelt und keylos als JSON bereitstellt. Ein einziger
Adapter erschließt damit viele InfraNode-Städte gleichzeitig (Dedup-Prinzip:
EIN Parking-Endpunkt mit ParkenDD als bevorzugter Live-Quelle, statt je Stadt ein
eigener Connector).

LIZENZ (B-1, GOV-01): ParkenDD aggregiert heterogen lizenzierte Stadt-Quellen und
deklariert KEINE einheitliche Lizenz. Die Lizenz wird daher PRO STADT am echten
Ursprung verifiziert (``mappers/parkendd._PARKENDD_LICENSE``). Nur Städte mit
offener Standardlizenz werden überhaupt ausgeliefert (Owner-Entscheidung
2026-06-23: keine Tier-B/C-/NC-Auslieferung), die übrigen sind aus
``PARKENDD_CITIES`` entfernt und damit not_covered. Reine Live-Daten -> KEIN Archiv.

Sicherheit (T-9-02 SSRF): Host hartkodiert in ``_BASE``. Die Stadt-ID stammt aus
der hartkodierten ``PARKENDD_CITIES``-Map (kein roher Nutzer-Input in der URL).

DoS-/Datenfehler-Schutz: ``resp.raise_for_status()`` (5xx -> HTTPError -> STALE-
ON-ERROR der Fassade); jeder Feldzugriff defensiv per ``.get()`` mit None-Fallback.
"""

from __future__ import annotations

import httpx

_BASE = "https://api.parkendd.de"

# InfraNode-Slug -> ParkenDD-Stadt-ID (Pfadsegment). NUR die 13 Städte, deren
# Parkdaten-Ursprung eine OFFENE Standardlizenz führt (Lizenz-Recherche je Ursprung
# 2026-06-23, Owner-Entscheidung: keine Tier-B/C-/NC-Auslieferung). Die übrigen 9
# ParkenDD-Städte wurden bewusst ENTFERNT (-> automatisch not_covered): bonn ist
# CC BY-NC (kommerziell verboten!), hanau/ingolstadt/nuernberg proprietaer/
# zugangsbeschränkt, luebeck/magdeburg/mannheim/regensburg/wiesbaden ohne
# auffindbare Lizenz. Eine neue Stadt nur ergänzen, NACHDEM ihre Lizenz am
# Ursprung als offen verifiziert + in ``_PARKENDD_LICENSE`` (mappers/parkendd.py)
# eingetragen wurde.
PARKENDD_CITIES: dict[str, str] = {
    "aachen": "Aachen",
    "dortmund": "Dortmund",
    "dresden": "Dresden",
    "freiburg-im-breisgau": "Freiburg",
    "hamburg": "Hamburg",
    "heidelberg": "Heidelberg",
    "heilbronn": "Heilbronn",
    "kaiserslautern": "Kaiserslautern",
    "karlsruhe": "Karlsruhe",
    "koeln": "Koeln",
    "muenster": "Muenster",
    "oldenburg": "Oldenburg",
    "ulm": "Ulm",
}


async def fetch_parkendd(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float,
    lon: float,
    radius_km: float = 30.0,
) -> dict:
    """Holt die Live-Parkhaus-Belegung einer Stadt von ParkenDD.

    GET ``{_BASE}/{city_id}`` (city_id aus ``PARKENDD_CITIES[slug]``), dann je Lot
    ein schlankes dict (Name, Adresse, Koordinaten, frei/gesamt, Zustand, Typ).
    ``resp.raise_for_status()`` (5xx -> Fassade STALE-ON-ERROR). Felder defensiv.

    ``lat``/``lon``/``radius_km`` sind vertragskonform Teil der Signatur (alle
    Stadt-Adapter teilen sie), werden hier aber nicht zur Filterung genutzt
    (ParkenDD liefert den kompletten Stadt-Datensatz).

    Rückgabe-Keys (exakt das, was ``map_parkendd`` erwartet): ``slug``,
    ``facilities`` und ``as_of`` (Datenstand ISO-String oder None).
    """
    city_id = PARKENDD_CITIES[slug]
    resp = await http.get(f"{_BASE}/{city_id}")
    resp.raise_for_status()

    body = resp.json()
    lots = body.get("lots", []) if isinstance(body, dict) else []
    as_of = body.get("last_updated") if isinstance(body, dict) else None

    facilities: list[dict] = []
    for lot in lots:
        if not isinstance(lot, dict):
            continue
        coords = lot.get("coords") or {}
        try:
            f_lat = float(coords["lat"]) if coords.get("lat") is not None else None
            f_lon = float(coords["lng"]) if coords.get("lng") is not None else None
        except (TypeError, ValueError):
            f_lat = f_lon = None
        # H8 (Null-Regel): free:-1 zusammen mit state nodata/closed ist ein
        # Kein-Daten-Sentinel von ParkenDD, keine echte Belegung. Als None
        # ausweisen statt eine irreführende negative Zahl durchzureichen.
        state = lot.get("state")
        free = lot.get("free")
        total = lot.get("total")
        if (isinstance(free, (int, float)) and free < 0) or state in {
            "nodata",
            "closed",
        }:
            free = None
        # MITTEL-Fix (Audit 2026-06-29): free > total ist physikalisch unmöglich
        # (Live Köln Philharmonie free:252/total:247 = Sensor-Drift) -> unplausibel,
        # keine erfundene Belegung ausliefern. Nur bei echter Kapazität (total>0).
        elif (
            isinstance(free, (int, float))
            and isinstance(total, (int, float))
            and total > 0
            and free > total
        ):
            free = None
        facilities.append(
            {
                "name": lot.get("name"),
                "address": lot.get("address"),
                "lat": f_lat,
                "lon": f_lon,
                "free": free,
                "total": total,
                "state": state,
                "lot_type": lot.get("lot_type"),
            }
        )

    return {"slug": slug, "facilities": facilities, "as_of": as_of}
