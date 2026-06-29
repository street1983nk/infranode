"""Hamburg-Baustellen-Adapter fetch_hamburg_road_events (DATA-15, Tier A).

Korrektur [VERIFIED 2026-06-10]: der alte CKAN-2-Step-Pfad (package_show auf
``suche.transparenz.hamburg.de`` -> GeoJSON-Ressource) hat dauerhaft leere
``events`` geliefert. Das Paket ``baustellen-hamburg`` existiert zwar (Paket-ID
und ``license_id=dl-de-by-2.0`` live bestätigt), seine Ressourcen sind aber
ausschließlich XML/GML/HTML-Archivlinks auf ``archiv.transparenz.hamburg.de``;
der GeoJSON-Format-Match konnte also nie greifen. Die im Paket verlinkten
WFS-Dienste auf ``geodienste.hamburg.de`` (z. B. ``HH_WFS_Baustellen``) sind
ebenfalls tot (404, live geprüft).

Echte GeoJSON-Quelle [VERIFIED 2026-06-10]: die Hamburger Urban Data Platform
liefert denselben Datensatz ("Baustellen Hamburg", Bauweiser-Steckbriefe) als
OGC API Features mit nativem GeoJSON:
``https://api.hamburg.de/datasets/v1/baustellen/collections/baustelle/items``
(``f=json``; Koordinaten CRS84 = [lon, lat], Punkt-Geometrien; live 125
Features). Properties [VERIFIED 2026-06-10]: ``titel``, ``organisation``,
``anlass``, ``umfang``, ``baubeginn``/``bauende`` (deutsches Datumsformat,
z. B. "01.04.2020"), ``internetlink`` u. a.

Sicherheit (T-9-02 SSRF): Die komplette Items-URL ist in ``_BASE`` hartkodiert;
es wird KEINE Upstream-gelieferte URL gefolgt (kein Discovery-Step mehr, daher
entfällt die Allowlist-Prüfung einer entdeckten URL).

DoS-Schutz (T-9-DOS): ``limit=1000`` als harter Cap (live 125 Features);
``resp.raise_for_status()`` ist Pflicht, damit ein 5xx als ``httpx.HTTPError``
an die Fassade durchschlägt und der STALE-ON-ERROR-Pfad greift.

Datenfehler-Schutz (T-9-02): Jeder Zugriff ist ``.get()``/``[]``-defensiv mit
None-Fallback, daher kein ``KeyError`` bei fehlenden oder anders benannten
Feldern.

Der Adapter ist rein gegenüber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade).
"""

from __future__ import annotations

import httpx

# Host + Pfad hartkodiert (T-9-02 SSRF): nur die OGC-API-Features-Collection
# "baustelle" der Hamburger Urban Data Platform ([VERIFIED 2026-06-10]).
_BASE = "https://api.hamburg.de/datasets/v1/baustellen/collections/baustelle/items"

# DoS-Cap (T-9-DOS): harter Feature-Deckel je Abruf (live 125 Features).
_LIMIT = 1000

# [VERIFIED 2026-06-10]-properties-Feldnamen per Live-Probe gegen die OGC API.
# Defensiv per .get() gelesen -> None-Fallback statt KeyError (T-9-02).
_FIELD_TITEL = "titel"  # [VERIFIED 2026-06-10] Titel der Maßnahme
_FIELD_ORGANISATION = "organisation"  # [VERIFIED 2026-06-10] Realisierungsträger
_FIELD_ANLASS = "anlass"  # [VERIFIED 2026-06-10] Anlass/Beschreibung
_FIELD_BEGINN = "baubeginn"  # [VERIFIED 2026-06-10] z. B. "01.04.2020"
_FIELD_ENDE = "bauende"  # [VERIFIED 2026-06-10] z. B. "31.12.2026"


async def fetch_hamburg_road_events(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float,
    lon: float,
    radius_km: float = 30.0,
) -> dict:
    """Holt Hamburg-Baustellen über die OGC API Features (GeoJSON).

    GET ``{_BASE}?f=json&limit={_LIMIT}`` ([VERIFIED 2026-06-10], Host
    hartkodiert, T-9-02) und aus ``features`` je ``properties`` ein schlankes
    Event-dict bauen (Felder defensiv per ``.get()`` mit None-Fallback);
    ``lat``/``lon`` stammen aus der Punkt-Geometrie (``coordinates=[lon, lat]``,
    CRS84). ``resp.raise_for_status()`` ist Pflicht.

    ``lat``/``lon``/``radius_km`` sind Vertrags-konform Teil der Signatur (alle
    Stadt-Adapter teilen sie); Hamburg liefert den kompletten Stadt-Datensatz,
    daher werden sie hier nicht zur serverseitigen Filterung benutzt.

    Rückgabe-Keys (exakt das, was ``map_hamburg_road_events`` erwartet):
    ``slug`` und ``events``.
    """
    resp = await http.get(_BASE, params={"f": "json", "limit": _LIMIT})
    resp.raise_for_status()

    geo = resp.json()
    features = geo.get("features", []) if isinstance(geo, dict) else []
    events: list[dict] = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        coords = geometry.get("coordinates") if isinstance(geometry, dict) else None
        feature_lon, feature_lat = None, None
        if (
            isinstance(coords, list)
            and len(coords) >= 2
            and isinstance(coords[0], int | float)
            and isinstance(coords[1], int | float)
        ):
            feature_lon, feature_lat = float(coords[0]), float(coords[1])
        # T-9-02: fehlendes Feld -> None (kein KeyError).
        events.append(
            {
                "titel": props.get(_FIELD_TITEL),
                "organisation": props.get(_FIELD_ORGANISATION),
                "anlass": props.get(_FIELD_ANLASS),
                "baubeginn": props.get(_FIELD_BEGINN),
                "bauende": props.get(_FIELD_ENDE),
                "lat": feature_lat,
                "lon": feature_lon,
            }
        )

    return {"slug": slug, "events": events}
