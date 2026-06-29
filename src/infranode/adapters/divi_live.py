"""Klinikscharfer DIVI-Intensivregister-Live-Adapter fetch_icu_live (DATA-25b, Tier C).

Liest die klinikscharfe Intensiv-Live-Lage vom DIVI-Intensivregister über den
gepoolten httpx-Client. Die Zuordnung Stadt -> Kreis löst der Adapter über eine
kuratierte, Adapter-lokale Map (``_CITY_KREIS``, analog ``lhp._CITY_PEGEL`` /
``autobahn._CITY_ROADS``): der 5-stellige AGS-Präfix filtert clientseitig die
``krankenhausStandort.gemeindeschluessel`` der Klinik-Standorte. Ein unbekannter
Slug liefert ein raw-dict mit leeren/``None``-Feldern (ehrliche Teilabdeckung,
KEIN Crash).

[VERIFIED 2026-06-10] Endpunkt + Antwortform (Live-Sweep):
``GET https://www.intensivregister.de/api/public/intensivregister?page=0`` ->
``{"rowCount": 773, "data": [{"krankenhausStandort": {"bezeichnung": ...,
"ort": ..., "gemeindeschluessel": "14612000", ...}, "letzteMeldezeitpunkt": ...,
"maxBettenStatusEinschaetzungHighCare": "VERFUEGBAR|BEGRENZT|NICHT_VERFUEGBAR|
KEINE_ANGABE", "maxBettenStatusEinschaetzungEcmo": ...}, ...], "sum": ...}``.
Der frühere Endpunkt ``/api/public/intensivregister/laender`` liefert HTTP 500
und kannte keinen ``kreis``-Query-Parameter (der alte Adapter hat nie
funktioniert). Es gibt KEINE numerischen betten_frei/betten_belegt mehr, nur
qualitative Status-Einschätzungen je Klinik. Der apex-Host ``intensivregister.de``
antwortet mit 301 auf ``www.intensivregister.de`` (httpx folgt Redirects nicht
automatisch), daher ist der www-Host hartkodiert.

KRITISCH (Datenbank-Schutzrecht, RESEARCH Pitfall 4, T-08-DBR): Die klinikscharfe
DIVI-Live-Lage ist KEINE offene Lizenz. Sie wird ausschließlich live
durchgeleitet (Tier C, live-only). Dieser Adapter baut KEINEN ``CanonicalRecord``
(das macht ``map_icu_live`` in der Route).

Sicherheit (T-08-SSRF, Tampering): Der Host ist in ``_BASE`` hartkodiert; der
AGS-Präfix stammt ausschließlich aus der kuratierten ``_CITY_KREIS``-Map (nie
User-Input). ``resp.raise_for_status()`` ist Pflicht, damit ein 5xx als
``httpx.HTTPError`` an die Fassade durchschlägt und der STALE-ON-ERROR-Pfad
greift (-> Route degradiert ehrlich, kein 5xx-Leak). Die Pagination ist mit
``_MAX_PAGES`` hart gedeckelt (DoS-Schutz, kein unendlicher Page-Loop).
"""

from __future__ import annotations

import httpx

# Host hartkodiert (T-08-SSRF): nur diese eine öffentliche DIVI-Instanz.
# [VERIFIED 2026-06-10] Klinik-Liste mit page-Pagination; /laender ist tot (500).
_BASE = "https://www.intensivregister.de/api/public/intensivregister"

# Harter Pagination-Deckel (DoS-Schutz): nie mehr als 10 Seiten je Fetch.
# [VERIFIED 2026-06-10] page=0 lieferte alle 773 Zeilen in EINER Seite; der Loop
# stoppt zusätzlich defensiv über rowCount bzw. eine leere data-Liste.
_MAX_PAGES = 10

# Fallback-Map Stadt -> 5-stelliger AGS-Präfix (T-08-SSRF): seit Audit 2026-06-29
# (Finding 218) leitet die Route den Kreis-Präfix aus dem Register ab
# (``entry.ags[:5]``, deckt alle 84 Städte ab) und übergibt ihn als ``kreis_ags``.
# Diese Map bleibt nur als Adapter-lokaler Fallback für Aufrufer, die ``kreis_ags``
# nicht setzen (z.B. Bestands-Unit-Tests); ihre Werte sind exakt ``ags[:5]`` der vier
# Städte. Der Präfix filtert clientseitig die 8-stellige
# ``krankenhausStandort.gemeindeschluessel`` (nie User-Input).
_CITY_KREIS: dict[str, str] = {
    "berlin": "11000",
    "hamburg": "02000",
    "muenchen": "09162",
    "koeln": "05315",
}


async def fetch_icu_live(
    http: httpx.AsyncClient, *, slug: str, kreis_ags: str | None = None
) -> dict:
    """Holt die klinikscharfe DIVI-Live-ICU-Lage der Stadt als raw-dict.

    Der 5-stellige Kreis-Präfix wird primär aus ``kreis_ags`` genommen (die Route
    leitet ihn aus dem Register ab, ``entry.ags[:5]`` -> alle 84 Städte abgedeckt,
    Finding 218); fehlt er, fällt der Adapter auf die kuratierte ``_CITY_KREIS``-Map
    zurück (vier Städte, Bestands-Tests). ``kreis_ags`` stammt ausschließlich aus
    dem Register, nie aus User-Input (T-08-SSRF).

    Liegt ein Präfix vor, wird die Klinik-Liste seitenweise (``page``-Parameter,
    hart gedeckelt auf ``_MAX_PAGES``) geholt und clientseitig auf Standorte
    gefiltert, deren ``gemeindeschluessel`` mit dem Präfix beginnt. Je Klinik
    werden ``bezeichnung``, ``ort``, ``letzteMeldezeitpunkt`` und die qualitativen
    Status-Einschätzungen High-Care/ECMO defensiv per ``.get()`` gelesen
    ([VERIFIED 2026-06-10]). Ohne ermittelbaren Präfix liefert die Funktion ein
    raw-dict mit ``None``-Feldern OHNE Live-Call (ehrliche Teilabdeckung).

    Rückgabe-Keys (exakt das, was ``map_icu_live`` erwartet): ``slug``,
    ``kreis_id``, ``kreis_name``, ``beds_free``, ``beds_occupied`` (beide immer
    ``None``: die Live-API liefert keine numerische Belegung mehr),
    ``hospitals`` (Liste je Klinik) und ``datum`` (jüngster Meldezeitpunkt).
    Der Host ist hartkodiert (SSRF-Schutz, T-08-DBR/SSRF),
    ``resp.raise_for_status()`` ist Pflicht (STALE-ON-ERROR-Pfad).

    KRITISCH (T-08-DBR): Die Daten sind Tier C (DB-Schutzrecht) und werden
    ausschließlich live durchgeleitet.
    """
    # Register-Präfix (kreis_ags) bevorzugen, sonst kuratierte Fallback-Map.
    kreis_id = kreis_ags or _CITY_KREIS.get(slug)
    if kreis_id is None:
        # Ehrliche Teilabdeckung: kein ermittelbarer AGS-Präfix -> kein Live-Call.
        return {
            "slug": slug,
            "kreis_id": None,
            "kreis_name": None,
            "beds_free": None,
            "beds_occupied": None,
            "hospitals": [],
            "datum": None,
        }

    hospitals: list[dict] = []
    fetched = 0
    row_count: int | None = None
    for page in range(_MAX_PAGES):
        resp = await http.get(_BASE, params={"page": page})
        resp.raise_for_status()
        body = resp.json()
        if not isinstance(body, dict):
            break
        if row_count is None and isinstance(body.get("rowCount"), int):
            row_count = body["rowCount"]
        rows = body.get("data")
        if not isinstance(rows, list) or not rows:
            break

        fetched += len(rows)
        for row in rows:
            if not isinstance(row, dict):
                continue
            standort = row.get("krankenhausStandort")
            if not isinstance(standort, dict):
                continue
            ags = str(standort.get("gemeindeschluessel") or "")
            if not ags.startswith(kreis_id):
                continue
            hospitals.append(
                {
                    "bezeichnung": standort.get("bezeichnung"),
                    "ort": standort.get("ort"),
                    "letzte_meldung": row.get("letzteMeldezeitpunkt"),
                    "status_high_care": row.get("maxBettenStatusEinschaetzungHighCare"),
                    "status_ecmo": row.get("maxBettenStatusEinschaetzungEcmo"),
                }
            )

        # Defensiver Stopp: alle gemeldeten Zeilen geholt -> keine weitere Seite.
        if row_count is not None and fetched >= row_count:
            break

    # Jüngster Meldezeitpunkt der gefilterten Kliniken als Stand-Datum
    # (ISO-8601-Strings sortieren lexikografisch korrekt).
    datum = max(
        (h["letzte_meldung"] for h in hospitals if h.get("letzte_meldung")),
        default=None,
    )

    return {
        "slug": slug,
        "kreis_id": kreis_id,
        "kreis_name": None,
        "beds_free": None,
        "beds_occupied": None,
        "hospitals": hospitals,
        "datum": datum,
    }
