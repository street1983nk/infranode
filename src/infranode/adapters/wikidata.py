"""Keyloser Wikidata-Adapter fetch_city_base (DATA-01).

Laedt ``Special:EntityData/{QID}.json`` ueber den gepoolten httpx-Client und
extrahiert P1082 (Einwohner), P2046 (Flaeche, nur km2) und P625 (Koordinaten)
robust aus der verschachtelten Claim-Struktur. Rueckgabe ist das flache raw-dict
mit den Keys ``slug``/``lat``/``lon``/``population``/``area``, das der bestehende
reine ``map_wikidata_city`` erwartet.

Der Adapter ist rein gegenueber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade). ``resp.raise_for_status()`` ist Pflicht,
damit ein 5xx als ``httpx.HTTPError`` an die Fassade durchschlaegt und der
STALE-ON-ERROR-Pfad greift.

Sicherheit (T-04-03): Der Host ist in ``ENTITY_URL`` hartkodiert; die qid wird
nur in den Pfad interpoliert und ist bereits per ``CityRegistryEntry.qid``-Pattern
``^Q\\d+$`` validiert (kein SSRF, kein User-kontrollierter Host).
"""

from __future__ import annotations

import httpx

ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"

# QID der Einheit "Quadratkilometer". Nur P2046-Werte mit dieser Einheit werden
# als Flaeche in km2 akzeptiert (Pitfall 1: andere Einheiten -> None).
_KM2_UNIT = "http://www.wikidata.org/entity/Q712226"


def _choose(claims: dict, prop: str) -> dict | None:
    """Waehlt das relevante Statement: preferred-rank vor erstem nicht-deprecated.

    Liefert das ausgewaehlte Statement-dict oder ``None``, falls die Eigenschaft
    fehlt oder nur deprecated-Statements vorliegen.
    """
    stmts = claims.get(prop, [])
    for stmt in stmts:
        if stmt.get("rank") == "preferred":
            return stmt
    for stmt in stmts:
        if stmt.get("rank") != "deprecated":
            return stmt
    return None


def _quantity(claims: dict, prop: str) -> int | None:
    """Extrahiert eine ganzzahlige Quantity (z.B. P1082 Einwohner) oder None."""
    chosen = _choose(claims, prop)
    if chosen is None:
        return None
    amount = chosen["mainsnak"]["datavalue"]["value"]["amount"]
    return int(float(amount))


def _area_km2(claims: dict) -> float | None:
    """Extrahiert P2046 nur bei km2-Einheit (Q712226), sonst None (Pitfall 1)."""
    chosen = _choose(claims, "P2046")
    if chosen is None:
        return None
    value = chosen["mainsnak"]["datavalue"]["value"]
    if value.get("unit") != _KM2_UNIT:
        return None
    return float(value["amount"])


def _coord(claims: dict, axis: str) -> float | None:
    """Extrahiert lat/lon aus P625; robust gegen fehlendes P625 (Pitfall 3)."""
    stmts = claims.get("P625", [])
    if not stmts:
        return None
    value = stmts[0]["mainsnak"]["datavalue"]["value"]
    key = "latitude" if axis == "lat" else "longitude"
    return value[key]


async def fetch_city_base(http: httpx.AsyncClient, *, slug: str, qid: str) -> dict:
    """Holt Wikidata-Stammdaten zur ``qid`` und liefert das flache raw-dict.

    Rueckgabe-Keys (exakt das, was ``map_wikidata_city`` erwartet): ``slug``,
    ``lat``, ``lon``, ``population``, ``area``. Der Adapter macht KEINEN
    Register-Fallback fuer fehlendes P625 (lat/lon bleiben None); den Geo-Fallback
    auf ``entry.geo`` uebernimmt die Route in Plan 04-03 vor dem Mapper-Aufruf.
    """
    resp = await http.get(ENTITY_URL.format(qid=qid))
    resp.raise_for_status()
    entity = resp.json()["entities"][qid]
    claims = entity["claims"]
    return {
        "slug": slug,
        "lat": _coord(claims, "lat"),
        "lon": _coord(claims, "lon"),
        "population": _quantity(claims, "P1082"),
        "area": _area_km2(claims),
    }
