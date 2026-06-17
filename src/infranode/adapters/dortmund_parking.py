"""Keyloser Dortmund-Parken-Adapter ``fetch_dortmund_parking`` (DATA-09, Tier A).

Direkter Zugang zum offenen Parkleitsystem der Stadt Dortmund ueber die
Opendatasoft-Explore-API (KEIN Mobilithek-mTLS, KEIN Key, live verifiziert
2026-06-13: Feld ``zeitstempel_status`` "Daten 2 Minuten alt"):

- GET ``/api/v1/catalog/datasets/parkhauser/records?limit=100`` liefert je
  Einrichtung (Parkhaus + Park&Ride) ein flaches Record mit ``id``/``name``/
  ``type``/``frei``/``capacity``/``parkeinrichtung``/``zeitstempel``.

Rueckgabe ist das raw-dict, das ``map_dortmund_parking`` erwartet: ``slug`` =
"dortmund", ``as_of`` (juengster ``zeitstempel`` aller Records) und ``facilities``
(je Einrichtung ein schlankes dict mit facility_id/name/type/free/capacity/
occupancy/status/observed_at). Der Adapter baut KEINEN ``CanonicalRecord`` und
kennt KEIN Cache/Breaker (das liefert die Resilienz-Fassade).
``resp.raise_for_status()`` ist Pflicht, damit ein 5xx als ``httpx.HTTPError``
durchschlaegt und der STALE-ON-ERROR-Pfad greift.

Lizenz: Datenlizenz Deutschland Zero 2.0 (govdata.de/dl-de/zero-2-0) = Tier A
(permissiv lizenziert, keine Attributionspflicht; Projektkonvention nennt die
Quelle dennoch). Siehe ``mappers/mobilithek_parken.map_dortmund_parking``.

Sicherheit:
- T-05-08 (SSRF): Der Host ist in ``_BASE`` hartkodiert; es fliesst kein
  User-Input in die URL (fixer Datensatz-Pfad, fixe Query).
"""

from __future__ import annotations

import httpx

# Host + Datensatz-Pfad hartkodiert (SSRF-Schutz, T-05-08).
_BASE = "https://open-data.dortmund.de/api/explore/v2.1"
_DATASET = "parkhauser"
# Die Stadt liefert ~24 Einrichtungen; 100 deckt sie mit Reserve ab (1 Request).
_LIMIT = 100


def _occupancy(free: int | None, capacity: int | None) -> float | None:
    """Auslastung 0..1 aus free/capacity (rein); unplausible Werte -> None."""
    if not isinstance(free, int) or not isinstance(capacity, int) or capacity <= 0:
        return None
    used = capacity - free
    if used < 0:
        return None
    return round(used / capacity, 4)


def _facility(rec: dict) -> dict:
    """Bildet ein Opendatasoft-Record auf ein schlankes facility-dict ab (rein)."""
    free = rec.get("frei")
    capacity = rec.get("capacity")
    return {
        "facility_id": rec.get("id"),
        "name": rec.get("name"),
        "type": rec.get("type"),
        "free": free,
        "capacity": capacity,
        "occupancy": _occupancy(free, capacity),
        "status": rec.get("parkeinrichtung"),
        "observed_at": rec.get("zeitstempel"),
    }


async def fetch_dortmund_parking(http: httpx.AsyncClient) -> dict:
    """Holt die Live-Parkbelegung Dortmund und liefert das raw-dict fuer den Mapper.

    Rueckgabe-Keys (exakt das, was ``map_dortmund_parking`` erwartet): ``slug``
    ("dortmund"), ``as_of`` (juengster ``zeitstempel``, ISO-String, oder None) und
    ``facilities`` (Liste schlanker dicts). ``raise_for_status`` ist Pflicht
    (5xx -> Fassade STALE-ON-ERROR).
    """
    url = f"{_BASE}/catalog/datasets/{_DATASET}/records"
    resp = await http.get(url, params={"limit": _LIMIT})
    resp.raise_for_status()
    body = resp.json()

    records = body.get("results", []) or []
    facilities = [_facility(rec) for rec in records]
    timestamps = [rec.get("zeitstempel") for rec in records if rec.get("zeitstempel")]
    as_of = max(timestamps) if timestamps else None

    return {"slug": "dortmund", "as_of": as_of, "facilities": facilities}
