"""Keyloser Hamburg-Verkehrslage-Adapter ``fetch_hamburg_verkehrslage`` (DATA-26).

Direkter, keyloser Zugang zur Echtzeit-Verkehrslage der Freien und Hansestadt
Hamburg über die OGC API Features (OAF, GeoJSON) der Urban Data Platform (KEIN
Mobilithek-mTLS, KEIN Key; live verifiziert 2026-06-13: ~22.300 Streckenabschnitte
mit ``zustandsklasse`` je 5-Minuten-Schnappschuss):

- GET ``/datasets/v1/verkehrslage/collections/verkehrslage/items`` liefert je
  Straßenabschnitt ein ``Feature`` (LineString CRS84 = [lon, lat]) mit den
  Properties ``zustandsklasse`` ("fliessend"/"dicht"/"zäh"/"gestaut"),
  ``zeitstempel``/``zeitstempel_utc`` (Datenstand) und ``strassenklasse``.

22.300 Abschnitte sind zu viel für eine Antwort. Der Adapter ruft daher je
Zustandsklasse genau einmal mit OAF-Property-Filter (``?zustandsklasse=...``) ab
und liest pro Antwort ``numberMatched`` als Zählung. Für die fließenden
Abschnitte genügt die Zählung (``limit=1``); für die nicht-fließenden
("dicht"/"zäh"/"gestaut") werden zusätzlich bis ``_SEGMENT_CAP`` Abschnitte als
schlanke Punkt-dicts (Mittelpunkt des LineString) zurückgegeben. So entsteht ein
kompaktes Bild: eine Netz-Zusammenfassung (Zählung je Klasse) plus die konkreten
Stauabschnitte, ohne das gesamte Straßennetz zu übertragen.

Rückgabe ist das raw-dict, das ``map_hamburg_verkehrslage`` erwartet: ``slug`` =
"hamburg", ``as_of`` (jüngster Datenstand, ISO-UTC, oder None), ``summary``
(``total`` + ``by_state``) und ``segments`` (gekappte nicht-fließende Abschnitte,
Priorität gestaut > zäh > dicht). Der Adapter baut KEINEN ``CanonicalRecord`` und
kennt KEIN Cache/Breaker (das liefert die Resilienz-Fassade).
``resp.raise_for_status()`` ist Pflicht, damit ein 5xx als ``httpx.HTTPError``
durchschlägt und der STALE-ON-ERROR-Pfad greift.

Lizenz: Datenlizenz Deutschland Namensnennung 2.0 (govdata.de/dl-de/by-2-0) =
Tier A; Attribution "Freie und Hansestadt Hamburg" (wortgenau wie hamburg_baustellen).

Sicherheit:
- T-26-SSRF: Host + Collection-Pfad sind in ``_ITEMS_URL`` hartkodiert; es fließt
  kein User-Input in die URL (nur fixe Query-Parameter + die fixen Klassen-Namen).
- T-26-DOS: ``_SEGMENT_CAP`` deckelt die je Klasse gezogenen Features; die
  Zählung kommt aus ``numberMatched`` und nicht aus einem Voll-Abzug.
"""

from __future__ import annotations

import httpx

# Host + Collection hartkodiert (T-26-SSRF): die OAF-Items der Hamburger
# Verkehrslage-Collection (Urban Data Platform, [VERIFIED 2026-06-13]).
_ITEMS_URL = (
    "https://api.hamburg.de/datasets/v1/verkehrslage/collections/verkehrslage/items"
)

# Vollständiges Klassen-Vokabular der Quelle ([VERIFIED 2026-06-13]: nur diese
# vier; Summe der numberMatched == Gesamtzahl). "fliessend" = frei, sonst Stau.
_FLOWING_STATE = "fliessend"
# Nicht-fließende Klassen in absteigender Priorität (Stau zuerst).
_NOTABLE_STATES = ("gestaut", "zäh", "dicht")
_ALL_STATES = (_FLOWING_STATE, *_NOTABLE_STATES)

# T-26-DOS: harter Deckel je gezogener Stauklasse UND für die Gesamt-Segmentliste
# der Antwort (Netz hat ~1.100 nicht-fließende Abschnitte; 250 zeigt die
# relevantesten ohne das Netz zu übertragen).
_SEGMENT_CAP = 250


def _iso_utc(raw_ts: object) -> str | None:
    """Normalisiert ``zeitstempel_utc`` ("2026-06-13 20:40:00") zu ISO-UTC (rein).

    Die Quelle liefert die UTC-Beobachtungszeit leerzeichen-getrennt; daraus wird
    ein sauberes ISO-Z. Fehlender/unplausibler Wert -> ``None`` (ehrlich).
    """
    if not isinstance(raw_ts, str) or not raw_ts.strip():
        return None
    text = raw_ts.strip().replace(" ", "T")
    return text if text.endswith("Z") else f"{text}Z"


def _midpoint(geometry: object) -> tuple[float | None, float | None]:
    """Repraesentativer Punkt (lat, lon) als Mittel-Koordinate des LineString (rein).

    Defensiv gegen fehlende/malformierte Geometrie -> ``(None, None)`` statt Fehler.
    """
    if not isinstance(geometry, dict):
        return (None, None)
    coords = geometry.get("coordinates")
    if not isinstance(coords, list) or not coords:
        return (None, None)
    mid = coords[len(coords) // 2]
    if (
        isinstance(mid, list)
        and len(mid) >= 2
        and isinstance(mid[0], int | float)
        and isinstance(mid[1], int | float)
    ):
        return (float(mid[1]), float(mid[0]))  # CRS84 [lon, lat] -> (lat, lon)
    return (None, None)


def _segment(feature: dict) -> dict:
    """Bildet ein Verkehrslage-Feature auf ein schlankes Abschnitts-dict ab (rein)."""
    props = feature.get("properties") or {}
    lat, lon = _midpoint(feature.get("geometry"))
    return {
        "state": props.get("zustandsklasse"),
        "road_class": props.get("strassenklasse"),
        "lat": lat,
        "lon": lon,
        "observed_at": _iso_utc(props.get("zeitstempel_utc")),
    }


async def _fetch_state(
    http: httpx.AsyncClient, state: str, *, limit: int
) -> tuple[int, list[dict], str | None]:
    """Holt einen Zustandsklassen-Filter; gibt (count, features, collection_ts) zurück.

    ``count`` aus ``numberMatched`` (Netz-Zählung, kein Voll-Abzug), ``features``
    bis ``limit``, ``collection_ts`` der Collection-Level-``timeStamp`` (Fallback
    für ``as_of``). ``raise_for_status`` ist Pflicht (5xx -> Fassade STALE-ON-ERROR).
    """
    resp = await http.get(
        _ITEMS_URL,
        params={"f": "json", "limit": limit, "zustandsklasse": state},
    )
    resp.raise_for_status()
    body = resp.json()
    if not isinstance(body, dict):
        return (0, [], None)
    count = body.get("numberMatched")
    features = body.get("features") or []
    return (
        int(count) if isinstance(count, int) else 0,
        [f for f in features if isinstance(f, dict)],
        body.get("timeStamp"),
    )


async def fetch_hamburg_verkehrslage(http: httpx.AsyncClient) -> dict:
    """Holt die Live-Verkehrslage Hamburg und liefert das raw-dict für den Mapper.

    Je Zustandsklasse ein Filter-Request: ``fliessend`` nur zur Zählung
    (``limit=1``), die nicht-fließenden Klassen zur Zählung UND für bis
    ``_SEGMENT_CAP`` konkrete Abschnitte. Daraus die Netz-Zusammenfassung
    (``total`` + ``by_state``) und die priorisierte, global gedeckelte
    Stau-Segmentliste. Rückgabe-Keys (exakt das, was
    ``map_hamburg_verkehrslage`` erwartet): ``slug`` ("hamburg"), ``as_of``
    (jüngster Datenstand ISO-UTC oder None), ``summary`` und ``segments``.
    """
    by_state: dict[str, int] = {}
    notable_features: dict[str, list[dict]] = {}
    observed: list[str] = []
    collection_ts: str | None = None

    for state in _ALL_STATES:
        limit = _SEGMENT_CAP if state in _NOTABLE_STATES else 1
        count, features, ts = await _fetch_state(http, state, limit=limit)
        by_state[state] = count
        collection_ts = collection_ts or ts
        if state in _NOTABLE_STATES:
            notable_features[state] = features
        # as_of-Kandidaten aus JEDEM Feature (auch dem einen fließenden).
        for feat in features:
            iso = _iso_utc((feat.get("properties") or {}).get("zeitstempel_utc"))
            if iso:
                observed.append(iso)

    # Priorisierte, global gedeckelte Segmentliste (gestaut > zäh > dicht).
    segments: list[dict] = []
    truncated = False
    for state in _NOTABLE_STATES:
        for feat in notable_features.get(state, []):
            if len(segments) >= _SEGMENT_CAP:
                truncated = True
                break
            segments.append(_segment(feat))
        if truncated:
            break

    summary = {
        "total": sum(by_state.values()),
        "by_state": by_state,
        "segment_cap": _SEGMENT_CAP,
        "segments_truncated": truncated,
    }
    as_of = max(observed) if observed else collection_ts
    return {
        "slug": "hamburg",
        "as_of": as_of,
        "summary": summary,
        "segments": segments,
    }
