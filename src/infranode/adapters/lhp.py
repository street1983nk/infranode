"""Keyloser LHP-Hochwasser-Adapter fetch_flood (DATA-12, Tier A).

Laedt Hochwasser-Warnstufen vom keylosen Webservice der
Laenderuebergreifenden Hochwasserportale (LHP, www.hochwasserzentralen.de) ueber
den gepoolten httpx-Client in zwei Schritten [VERIFIED 2026-06-10]:

1. GET auf die Homepage: dort steht das dynamische Session-Token ``ki`` im
   HTML als ``addLagePegel(<ki>)``. Ohne ``ki`` antwortet der Webservice mit
   HTTP 200 und LEEREM Body (kein JSON!).
2. ``POST get_infospegel.php`` mit ``pgnr`` + ``ki`` je kuratiertem Pegel. Die
   Antwort ist EIN FLACHES dict je Pegel (KEIN PEGEL-Array, KEIN STAND-Feld):
   ``{"PN": "Muenchen", "GW": "Isar", "HW": "0", "HW_TXT": "Keine Meldestufe",
   "ZEIT": "Heute, 18:00 Uhr", "W": "108 cm", "Q": "38,5 m3/s", ...}``.

Die 1->N-Zuordnung Stadt -> Pegel loest der Adapter ueber eine kuratierte,
Adapter-lokale Map (``_CITY_PEGEL``, analog ``autobahn._CITY_ROADS``). Ein
unbekannter Slug liefert ein leeres Tuple -> leere ``warnings`` (ehrliche
Teilabdeckung, KEIN Fehler).

Sicherheit (T-07-IN, SSRF/Tampering): Die Hosts sind in ``_HOME``/``_BASE``
hartkodiert; die ``pgnr`` stammt ausschliesslich aus der kuratierten
``_CITY_PEGEL``-Map (nie User-Input), das ``ki`` ausschliesslich aus dem per
Regex extrahierten Homepage-HTML. ``resp.raise_for_status()`` ist Pflicht, damit
ein 5xx als ``httpx.HTTPError`` an die Fassade durchschlaegt und der
STALE-ON-ERROR-Pfad greift.

Datenfehler-Schutz (T-07-IN): Ein fehlendes ``ki``-Token (Markup-Aenderung) und
ein leerer/nicht-JSON-Body (z.B. abgelaufenes Token) werden defensiv abgefangen
-> leere ``warnings`` statt JSONDecodeError/500er. Felder werden per ``.get()``
mit None-Fallback gelesen.

Der Adapter ist rein gegenueber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade).
"""

from __future__ import annotations

import re

import httpx

# Hosts hartkodiert (T-07-IN SSRF): nur diese eine oeffentliche LHP-Instanz.
_HOME = "https://www.hochwasserzentralen.de/"
_BASE = "https://www.hochwasserzentralen.de/webservices/get_infospegel.php"

# [VERIFIED 2026-06-10] Das dynamische ki-Token steht im Homepage-HTML als
# addLagePegel(<ki>). Kein Match -> leere warnings (Graceful Degradation).
_KI_RE = re.compile(r"addLagePegel\((\d+)\)")

# Kuratierte Stadt -> Pegel-Map (T-07-IN): Adapter-lokal, kein neues
# Register-Feld. Nur diese foederalen Pegelkennungen gelangen in den POST-Body
# (nie User-Input). Ein unbekannter Slug -> leeres Tuple -> leere warnings
# (ehrliche Teilabdeckung). [VERIFIED 2026-06-10] via POST get_lagepegel.php
# (1724 Pegel, Spalten PGNR/PGNAME): max 1 Pegel je Register-Stadt, konservativ
# nur eindeutige Treffer (PGNAME traegt den Stadtnamen). Staedte ohne
# eindeutigen Stadt-Pegel (z.B. Stuttgart, Bremen, Kiel) bleiben bewusst aussen.
_CITY_PEGEL: dict[str, tuple[str, ...]] = {
    "berlin": ("BE_586290",),  # Berlin-Koepenick / Spree-Oder-Wasserstrasse
    "hamburg": ("SH_5952050",),  # Hamburg St. Pauli / Elbe
    "muenchen": ("BY_16005701",),  # Muenchen / Isar
    "koeln": ("NW_2730010",),  # Koeln / Rhein
    "frankfurt-am-main": ("HE_24700404",),  # Frankfurt-Osthafen / Main
    "duesseldorf": ("NW_2750010",),  # Duesseldorf / Rhein
    "essen": ("NW_2769720000200",),  # Essen-Hespertal / Hesperbach
    "leipzig": ("SN_578110",),  # Leipzig-Thekla / Parthe
    "dresden": ("SN_501060",),  # Dresden / Elbe
    "nuernberg": ("BY_24225000",),  # Nuernberg Lederersteg / Pegnitz
    "duisburg": ("NW_2770010",),  # Duisburg-Ruhrort / Rhein
    "bonn": ("NW_2710080",),  # Bonn / Rhein
    "mainz": ("RP_25100100",),  # Mainz / Rhein
    "erfurt": ("TH_57421.0",),  # Erfurt-Moebisburg / Gera
}


async def fetch_flood(http: httpx.AsyncClient, *, slug: str) -> dict:
    """Holt Hochwasser-Warnstufen je kuratiertem Pegel der Stadt als raw-dict.

    2-Step [VERIFIED 2026-06-10]: erst die Homepage laden und das dynamische
    ``ki``-Token per Regex (``addLagePegel(<ki>)``) extrahieren, dann je Pegel
    aus ``_CITY_PEGEL.get(slug, ())`` ein ``POST get_infospegel.php`` mit
    ``data={"pgnr": ..., "ki": ...}``. Jede Antwort ist EIN FLACHES dict je
    Pegel: Warnstufe aus ``HW`` (Integer-String) + ``HW_TXT``, Zeitstempel aus
    ``ZEIT``, Pegelname ``PN``, Gewaesser ``GW``. ``stand`` haelt den zuletzt
    gesehenen ``ZEIT``-Text (Attributions-Pflicht, Pitfall 6).

    Rueckgabe-Keys (exakt das, was ``map_flood`` erwartet): ``slug``,
    ``warnings`` (Liste der Pegel-Records) und ``stand`` (Zeitstempel-Text oder
    ``None``). Defensiv (T-07-IN): unbekannter Slug, fehlendes ki-Token oder
    ein leerer/nicht-JSON-Body liefern leere ``warnings`` ohne Crash; die Hosts
    sind hartkodiert (SSRF-Schutz), ``resp.raise_for_status()`` ist Pflicht
    (STALE-ON-ERROR-Pfad).
    """
    warnings: list[dict] = []
    stand: str | None = None

    pegel_nrs = _CITY_PEGEL.get(slug, ())
    if not pegel_nrs:
        return {"slug": slug, "warnings": warnings, "stand": stand}

    # Schritt 1: dynamisches ki-Token aus dem Homepage-HTML extrahieren.
    home = await http.get(_HOME)
    home.raise_for_status()
    match = _KI_RE.search(home.text)
    if match is None:
        # Markup-Aenderung: kein Token -> leere warnings statt Crash (T-07-IN).
        return {"slug": slug, "warnings": warnings, "stand": stand}
    ki = match.group(1)

    # Schritt 2: je Pegel das flache Info-dict holen.
    for pegel in pegel_nrs:
        resp = await http.post(_BASE, data={"pgnr": pegel, "ki": ki})
        resp.raise_for_status()
        try:
            body = resp.json()
        except ValueError:
            # Leerer/nicht-JSON-Body (z.B. abgelaufenes ki-Token): Pegel
            # ueberspringen statt JSONDecodeError -> 500er (T-07-IN).
            continue
        if not isinstance(body, dict):
            continue
        # Unbekannte Pegelnummer: der Webservice liefert ein dict ohne
        # Pegel-Felder -> kein Eintrag (ehrliche Teilabdeckung).
        if body.get("PN") is None and body.get("HW") is None:
            continue

        # ZEIT-Zeitstempel defensiv lesen (Pflicht-Attribution, Pitfall 6).
        # Letzter vorhandener Zeitstempel gewinnt.
        zeit = body.get("ZEIT")
        if zeit:
            stand = zeit

        # Warnstufe HW ist ein Integer-String ("0" = keine Meldestufe).
        try:
            warnstufe = int(body["HW"]) if body.get("HW") is not None else None
        except (TypeError, ValueError):
            warnstufe = None

        warnings.append(
            {
                "pgnr": pegel,
                "pegel": body.get("PN"),
                "gewaesser": body.get("GW"),
                "warnstufe": warnstufe,
                "warnstufe_text": body.get("HW_TXT"),
                "wasserstand": body.get("W"),
                "abfluss": body.get("Q"),
                "zeit": zeit,
            }
        )

    return {"slug": slug, "warnings": warnings, "stand": stand}
