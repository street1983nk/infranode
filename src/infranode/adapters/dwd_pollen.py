"""Keyloser DWD-Pollen/UV-Adapter fetch_pollen_uv (DATA-14).

Lädt zwei keylose DWD-Open-Data-Dienste der Medizin-Meteorologie über den
gepoolten httpx-Client und bündelt sie in ein flaches raw-dict, das der reine
``map_pollen_uv``-Mapper erwartet:

- ``s31fg.json`` -> Pollenflug-Gefahrenindex, ``content[]`` je DWD-TEILREGION
  (``region_id``/``region_name``/``partregion_id``/``partregion_name``/
  ``Pollen``; [VERIFIED 2026-06-10]: 27 Einträge bei 12 region_ids, d.h. eine
  Großregion hat MEHRERE Partregionen mit unterschiedlichen Werten),
- ``uvi.json`` -> UV-Gefahrenindex, ``content[]`` je UV-Mess-Stadt
  (``city``/``forecast``).

KRITISCH (Pitfall 4, Ehrlichkeit): Die Daten sind REGION-genau, NICHT
stadtgenau. Die 1->1-Zuordnung Stadt -> DWD-Partregion-ID läuft über die
kuratierte, Adapter-lokale Map ``_CITY_POLLEN_REGION`` ([VERIFIED 2026-06-10]
gegen die Live-Antwort, ehrliche Teilabdeckung). Ein Match nur über die
region_id würde für mehrere Städte die FALSCHE Teilregion erwischen (z.B.
Hamburg: 11 Inseln statt 12 Geest); daher matcht ``_pick_region`` gegen
``partregion_id`` mit Fallback auf ``region_id`` für Regionen ohne
Partregionen (``partregion_id == -1``, z.B. Berlin/Brandenburg). Ein
unbekannter Slug (nicht in der Map) liefert ``region_id=None`` und ehrliche
leere Pollen-Daten statt eines Crashs.

Sicherheit (T-07-IN, SSRF/Tampering): Die Hosts ``_POLLEN``/``_UVI`` sind
hartkodiert; die Partregion-ID stammt ausschließlich aus der kuratierten Map
(nie User-Input), der ``slug`` kommt aus der Register-Allowlist.

Der Adapter ist rein gegenüber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade). ``resp.raise_for_status()`` ist Pflicht,
damit ein 5xx als ``httpx.HTTPError`` an die Fassade durchschlägt und der
STALE-ON-ERROR-Pfad greift.
"""

from __future__ import annotations

import httpx

# Hosts hartkodiert (T-07-IN SSRF): nur diese beiden öffentlichen DWD-Dienste.
_POLLEN = "https://opendata.dwd.de/climate_environment/health/alerts/s31fg.json"
_UVI = "https://opendata.dwd.de/climate_environment/health/alerts/uvi.json"

# Kuratierte Stadt -> DWD-Partregion-ID-Map ([VERIFIED 2026-06-10] gegen die
# Live-Antwort s31fg.json, 27 Teilregionen). Pitfall 4: ehrliche Teilabdeckung,
# NICHT stadtgenau. Werte sind partregion_ids; Regionen OHNE Partregionen
# (partregion_id == -1) tragen die region_id (50 Brandenburg/Berlin, 20
# Mecklenburg-Vorpommern). Ein unbekannter Slug -> None -> leere Pollen-Daten.
_CITY_POLLEN_REGION: dict[str, int] = {
    "berlin": 50,  # Brandenburg und Berlin (keine Partregionen)
    "hamburg": 12,  # Geest, Schleswig-Holstein und Hamburg (NICHT 11 Inseln)
    "muenchen": 121,  # Allgaeu/Oberbayern/Bay. Wald
    "koeln": 41,  # Rhein.-Westfäl. Tiefland
    "frankfurt-am-main": 92,  # Rhein-Main (NICHT 91 Nordhessen)
    "stuttgart": 112,  # Hohenlohe/mittlerer Neckar/Oberschwaben
    "duesseldorf": 41,  # Rhein.-Westfäl. Tiefland
    "dortmund": 41,  # Rhein.-Westfäl. Tiefland
    "essen": 41,  # Rhein.-Westfäl. Tiefland
    "leipzig": 81,  # Tiefland Sachsen
    "bremen": 31,  # Westl. Niedersachsen/Bremen
    "dresden": 81,  # Tiefland Sachsen
    "hannover": 32,  # Östl. Niedersachsen
    "nuernberg": 123,  # Bayern nördl. der Donau
    "duisburg": 41,  # Rhein.-Westfäl. Tiefland
    "bochum": 41,  # Rhein.-Westfäl. Tiefland
    "wuppertal": 43,  # Mittelgebirge NRW (Bergisches Land)
    "bielefeld": 42,  # Ostwestfalen
    "bonn": 41,  # Rhein.-Westfäl. Tiefland
    "muenster": 41,  # Rhein.-Westfäl. Tiefland
    "wiesbaden": 92,  # Rhein-Main
    "kiel": 12,  # Geest, Schleswig-Holstein und Hamburg
    "mainz": 101,  # Rhein, Pfalz, Nahe und Mosel
    "magdeburg": 61,  # Tiefland Sachsen-Anhalt
    "erfurt": 71,  # Tiefland Thüringen
    "potsdam": 50,  # Brandenburg und Berlin (keine Partregionen)
    "saarbruecken": 103,  # Saarland
    "schwerin": 20,  # Mecklenburg-Vorpommern (keine Partregionen)
}

# Kuratierte Stadt -> UV-Mess-Stadt-Map (uvi.json ist nach 38 UV-Mess-Stationen
# gegliedert, nicht nach Pollen-Großregionen; T-07-IN). Fehlt der Slug, bleibt
# uv_index None (ehrliche Teilabdeckung, kein Crash).
#
# Erweitert auf ALLE 84 Städte (Audit 2026-06-29, Finding 157, vorher nur 4):
# Exakt-Namens-Match wo die Stadt selbst Messstation ist, sonst die NÄCHSTE
# Tiefland-Station (Haversine gegen die Stationskoordinaten). Pitfall 4: NICHT
# stadtgenau, sondern die Region der nahesten Station (UV variiert räumlich
# gering). Die vier DWD-Höhenstationen (Zugspitze 2962 m, Großer Arber 1456 m,
# Kahler Asten 840 m, Weinbiet 554 m) sind als Nearest-Ziel BEWUSST
# ausgeschlossen: Höhe verfälscht den UV-Index stark, eine Tiefland-Stadt darf
# ihn nicht erben. Trailing-Kommentar = Station + Distanz zur Methoden-Transparenz.
_CITY_UVI_NAME: dict[str, str] = {
    "aachen": "Düsseldorf",  # ~70 km
    "augsburg": "München",  # ~56 km
    "bergisch-gladbach": "Bonn",  # ~28 km
    "berlin": "Berlin",  # exakt
    "bielefeld": "Osnabrück",  # ~43 km
    "bochum": "Düsseldorf",  # ~42 km
    "bonn": "Bonn",  # exakt
    "bottrop": "Düsseldorf",  # ~34 km
    "braunschweig": "Wernigerode",  # ~52 km
    "bremen": "Bremen",  # exakt
    "bremerhaven": "Bremen",  # ~54 km
    "chemnitz": "Dresden",  # ~62 km
    "cottbus": "Cottbus",  # exakt
    "darmstadt": "Frankfurt/Main",  # ~27 km
    "dortmund": "Düsseldorf",  # ~58 km
    "dresden": "Dresden",  # exakt
    "duesseldorf": "Düsseldorf",  # exakt
    "duisburg": "Düsseldorf",  # ~23 km
    "erfurt": "Weimar",  # ~21 km
    "erlangen": "Nürnberg",  # ~17 km
    "essen": "Düsseldorf",  # ~30 km
    "frankfurt-am-main": "Frankfurt/Main",  # exakt
    "freiburg-im-breisgau": "Freiburg",  # exakt
    "fuerth": "Nürnberg",  # ~7 km
    "gelsenkirchen": "Düsseldorf",  # ~38 km
    "goettingen": "Kassel",  # ~39 km
    "guetersloh": "Osnabrück",  # ~48 km
    "hagen": "Düsseldorf",  # ~51 km
    "halle-saale": "Leipzig",  # ~32 km
    "hamburg": "Hamburg",  # exakt
    "hamm": "Osnabrück",  # ~68 km
    "hanau": "Frankfurt/Main",  # ~17 km
    "hannover": "Hannover",  # exakt
    "heidelberg": "Frankfurt/Main",  # ~78 km
    "heilbronn": "Stuttgart",  # ~41 km
    "herne": "Düsseldorf",  # ~47 km
    "hildesheim": "Hannover",  # ~29 km
    "ingolstadt": "Regensburg",  # ~56 km
    "jena": "Weimar",  # ~19 km
    "kaiserslautern": "Hahn",  # ~67 km
    "karlsruhe": "Stuttgart",  # ~63 km
    "kassel": "Kassel",  # exakt
    "kiel": "Kiel",  # exakt
    "koblenz": "Hahn",  # ~52 km
    "koeln": "Bonn",  # ~24 km
    "krefeld": "Düsseldorf",  # ~19 km
    "leipzig": "Leipzig",  # exakt
    "leverkusen": "Düsseldorf",  # ~26 km
    "ludwigshafen-am-rhein": "Frankfurt/Main",  # ~72 km
    "luebeck": "Hamburg",  # ~58 km
    "magdeburg": "Magdeburg",  # exakt
    "mainz": "Frankfurt/Main",  # ~34 km
    "mannheim": "Frankfurt/Main",  # ~71 km
    "moenchengladbach": "Düsseldorf",  # ~24 km
    "moers": "Düsseldorf",  # ~28 km
    "muelheim-an-der-ruhr": "Düsseldorf",  # ~23 km
    "muenchen": "München",  # exakt
    "muenster": "Osnabrück",  # ~45 km
    "neuss": "Düsseldorf",  # ~6 km
    "nuernberg": "Nürnberg",  # exakt
    "oberhausen": "Düsseldorf",  # ~27 km
    "offenbach-am-main": "Frankfurt/Main",  # ~6 km
    "oldenburg": "Bremen",  # ~40 km
    "osnabrueck": "Osnabrück",  # exakt
    "paderborn": "Kassel",  # ~67 km
    "pforzheim": "Stuttgart",  # ~37 km
    "potsdam": "Berlin",  # ~27 km
    "recklinghausen": "Düsseldorf",  # ~52 km
    "regensburg": "Regensburg",  # exakt
    "remscheid": "Düsseldorf",  # ~30 km
    "reutlingen": "Stuttgart",  # ~33 km
    "rostock": "Rostock",  # exakt
    "saarbruecken": "Hahn",  # ~81 km
    "salzgitter": "Wernigerode",  # ~46 km
    "schwerin": "Rostock",  # ~69 km
    "siegen": "Bonn",  # ~66 km
    "solingen": "Düsseldorf",  # ~23 km
    "stuttgart": "Stuttgart",  # exakt
    "trier": "Hahn",  # ~50 km
    "ulm": "Ulm",  # exakt
    "wiesbaden": "Frankfurt/Main",  # ~32 km
    "wolfsburg": "Wernigerode",  # ~65 km
    "wuerzburg": "Würzburg",  # exakt
    "wuppertal": "Düsseldorf",  # ~26 km
}


def _pick_region(content: list[dict], partregion_id: int | None) -> dict | None:
    """Waehlt den ``content[]``-Eintrag der gewünschten Teilregion (oder None).

    [VERIFIED 2026-06-10]: ``content[]`` hat 27 Einträge bei 12 region_ids;
    der Match MUSS gegen ``partregion_id`` laufen, sonst gewinnt die erste
    (falsche) Teilregion einer Großregion. Fallback für Regionen ohne
    Partregionen (``partregion_id == -1``): Match gegen ``region_id``.

    Pitfall 4: ``partregion_id is None`` (unbekannter Slug) liefert ehrlich
    ``None`` statt eines beliebigen Eintrags. Defensive ``.get`` gegen
    fehlerhafte Einträge.
    """
    if partregion_id is None:
        return None
    for item in content:
        if item.get("partregion_id") == partregion_id:
            return item
    # Fallback: Großregionen ohne Partregionen (partregion_id == -1) werden
    # in der Map über ihre region_id adressiert (z.B. 50 Brandenburg/Berlin).
    for item in content:
        if item.get("partregion_id") == -1 and item.get("region_id") == partregion_id:
            return item
    return None


def _pick_uv(content: list[dict], slug: str) -> float | None:
    """Liest den heutigen UV-Index der UV-Mess-Stadt der gewünschten Stadt.

    Defensiv (T-07-IN): unbekannter Slug oder fehlende Felder -> ``None`` statt
    Crash. Der ``forecast.today``-Wert wird nach ``float`` gecastet.
    """
    name = _CITY_UVI_NAME.get(slug)
    if name is None:
        return None
    for item in content:
        if item.get("city") == name:
            today = (item.get("forecast") or {}).get("today")
            return float(today) if today is not None else None
    return None


async def fetch_pollen_uv(http: httpx.AsyncClient, *, slug: str) -> dict:
    """Holt Pollenflug + UV-Index der DWD-Teilregion einer Stadt.

    Fragt beide keylosen DWD-Dienste ab (``s31fg.json`` Pollen, ``uvi.json`` UV),
    ordnet den Slug über die kuratierte ``_CITY_POLLEN_REGION``-Map einer
    Teilregion zu ([VERIFIED 2026-06-10], Pitfall 4: NICHT stadtgenau) und gibt
    das flache raw-dict zurück, das ``map_pollen_uv`` erwartet.

    Rückgabe-Keys: ``slug``, ``region_id``, ``region_name``, ``pollen`` (dict je
    Pollenart), ``uv`` (float oder None). ``region_id``/``region_name`` tragen
    die getroffene Teilregion (bei Regionen ohne Partregionen die Großregion).
    Ein unbekannter Slug liefert ``region_id=None`` und leere Pollen-Daten
    (kein Crash). ``raise_for_status`` schlägt 5xx als ``httpx.HTTPError`` an
    die Fassade durch.
    """
    pollen_resp = await http.get(_POLLEN)
    pollen_resp.raise_for_status()
    uvi_resp = await http.get(_UVI)
    uvi_resp.raise_for_status()

    wanted = _CITY_POLLEN_REGION.get(slug)
    region = _pick_region(pollen_resp.json().get("content", []), wanted)
    pollen = region.get("Pollen", {}) if region else {}
    # Ehrliche Teilregion ausweisen: bei Regionen ohne Partregionen
    # (partregion_id == -1) greifen region_id/region_name der Großregion.
    region_id: int | None = None
    region_name: str | None = None
    if region:
        part_id = region.get("partregion_id", -1)
        region_id = part_id if part_id != -1 else region.get("region_id")
        region_name = region.get("partregion_name") or region.get("region_name")

    uv_index = _pick_uv(uvi_resp.json().get("content", []), slug)

    return {
        "slug": slug,
        "region_id": region_id,
        "region_name": region_name,
        "pollen": pollen,
        "uv": uv_index,
    }
