"""Keyloser Wikidata-Adapter fetch_city_base (DATA-01).

Lädt ``Special:EntityData/{QID}.json`` über den gepoolten httpx-Client und
extrahiert P1082 (Einwohner), P2046 (Fläche, nur km2) und P625 (Koordinaten)
robust aus der verschachtelten Claim-Struktur. Rückgabe ist das flache raw-dict
mit den Keys ``slug``/``lat``/``lon``/``population``/``area``, das der bestehende
reine ``map_wikidata_city`` erwartet.

Der Adapter ist rein gegenüber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade). ``resp.raise_for_status()`` ist Pflicht,
damit ein 5xx als ``httpx.HTTPError`` an die Fassade durchschlägt und der
STALE-ON-ERROR-Pfad greift.

Sicherheit (T-04-03): Der Host ist in ``ENTITY_URL`` hartkodiert; die qid wird
nur in den Pfad interpoliert und ist bereits per ``CityRegistryEntry.qid``-Pattern
``^Q\\d+$`` validiert (kein SSRF, kein User-kontrollierter Host).
"""

from __future__ import annotations

import httpx

ENTITY_URL = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"

# QID der Einheit "Quadratkilometer". Nur P2046-Werte mit dieser Einheit werden
# als Fläche in km2 akzeptiert (Pitfall 1: andere Einheiten -> None).
_KM2_UNIT = "http://www.wikidata.org/entity/Q712226"


def _choose(claims: dict, prop: str) -> dict | None:
    """Waehlt das relevante Statement: preferred-rank vor erstem nicht-deprecated.

    Liefert das ausgewählte Statement-dict oder ``None``, falls die Eigenschaft
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


# Wikidata-SPARQL-Endpunkt (keylos). Host hartkodiert (T-04-03, kein User-Host).
_SPARQL_URL = "https://query.wikidata.org/sparql"

# QID "Krankenhaus" (hospital). Krankenhaus-Treffer = instance-of (P31) einer
# Unterklasse (P279*) von Q16917, located in administrative territorial entity
# (P131, DIREKT) der Stadt-QID. P131 DIREKT (NICHT transitiv P131*): live
# verifiziert 2026-06-29 liefert die transitive Variante 504 (zu teuer), die
# direkte ist schnell + korrekt für kreisfreie Staedte/Stadtstaaten (Berlin
# Q64 -> 64 Treffer, Hamburg Q1055 -> 12 Treffer).
_HOSPITAL_QID = "Q16917"

# SPARQL-Query-Template. {qid} ist bereits per Register-Pattern ^Q\d+$ validiert
# (kein Injection-Vektor), wird nur in die fixe Query interpoliert.
_HOSPITAL_SPARQL = (
    "SELECT ?hospital ?hospitalLabel ?coord WHERE {{ "
    "?hospital wdt:P31/wdt:P279* wd:" + _HOSPITAL_QID + " . "
    "?hospital wdt:P131 wd:{qid} . "
    "OPTIONAL {{ ?hospital wdt:P625 ?coord . }} "
    'SERVICE wikibase:label {{ bd:serviceParam wikibase:language "de,en" . }} '
    "}}"
)


async def fetch_hospitals_wikidata(
    http: httpx.AsyncClient, *, slug: str, qid: str
) -> dict:
    """Holt Krankenhäuser einer Stadt keylos via Wikidata-SPARQL (H3-Fallback).

    H3-Fix (Audit 2026-06-29): Fallback für ``/cities/{slug}/health``, wenn GENESIS
    deaktiviert/credential-los ist (Prod-Realität) und das Krankenhausverzeichnis
    sonst still ``hospital:null`` liefert. Fragt keylos den öffentlichen
    Wikidata-SPARQL-Endpunkt (``https://query.wikidata.org/sparql``, Host
    hartkodiert, T-04-03) per POST ab: Krankenhäuser (``P31/P279* Q16917``), die
    direkt in der Stadt-QID liegen (``P131 wd:{qid}``).

    Die ``qid`` ist bereits per Register-Pattern ``^Q\\d+$`` validiert (kein
    Injection-Vektor). Rückgabe-Keys (exakt das, was ``map_hospital`` erwartet):
    ``slug``, ``count`` (Trefferzahl), ``hospitals`` (Liste mit ``name`` je
    Krankenhaus, Geo wenn vorhanden), ``reference_date`` (None: Wikidata führt
    keinen einheitlichen Stand). Ein 5xx schlägt via ``raise_for_status()`` als
    ``httpx.HTTPError`` durch (STALE-ON-ERROR-Pfad der Fassade).
    """
    resp = await http.post(
        _SPARQL_URL,
        data={"query": _HOSPITAL_SPARQL.format(qid=qid), "format": "json"},
        headers={"Accept": "application/sparql-results+json"},
    )
    resp.raise_for_status()
    body = resp.json()
    bindings = (
        body.get("results", {}).get("bindings", []) if isinstance(body, dict) else []
    )

    hospitals: list[dict] = []
    for b in bindings:
        if not isinstance(b, dict):
            continue
        label = b.get("hospitalLabel", {}).get("value")
        if not label:
            continue
        entry: dict = {"name": label}
        qid_uri = b.get("hospital", {}).get("value")
        if qid_uri:
            entry["wikidata"] = qid_uri.rsplit("/", 1)[-1]
        hospitals.append(entry)

    return {
        "slug": slug,
        "count": len(hospitals),
        "hospitals": hospitals,
        "reference_date": None,  # Wikidata führt keinen einheitlichen Stand.
    }


async def fetch_city_base(http: httpx.AsyncClient, *, slug: str, qid: str) -> dict:
    """Holt Wikidata-Stammdaten zur ``qid`` und liefert das flache raw-dict.

    Rückgabe-Keys (exakt das, was ``map_wikidata_city`` erwartet): ``slug``,
    ``lat``, ``lon``, ``population``, ``area``. Der Adapter macht KEINEN
    Register-Fallback für fehlendes P625 (lat/lon bleiben None); den Geo-Fallback
    auf ``entry.geo`` übernimmt die Route in Plan 04-03 vor dem Mapper-Aufruf.
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
