"""Keyloser DWD-Pollen/UV-Adapter fetch_pollen_uv (DATA-14).

Laedt zwei keylose DWD-Open-Data-Dienste der Medizin-Meteorologie ueber den
gepoolten httpx-Client und buendelt sie in ein flaches raw-dict, das der reine
``map_pollen_uv``-Mapper erwartet:

- ``s31fg.json`` -> Pollenflug-Gefahrenindex, ``content[]`` je DWD-TEILREGION
  (``region_id``/``region_name``/``partregion_id``/``partregion_name``/
  ``Pollen``; [VERIFIED 2026-06-10]: 27 Eintraege bei 12 region_ids, d.h. eine
  Grossregion hat MEHRERE Partregionen mit unterschiedlichen Werten),
- ``uvi.json`` -> UV-Gefahrenindex, ``content[]`` je UV-Mess-Stadt
  (``city``/``forecast``).

KRITISCH (Pitfall 4, Ehrlichkeit): Die Daten sind REGION-genau, NICHT
stadtgenau. Die 1->1-Zuordnung Stadt -> DWD-Partregion-ID laeuft ueber die
kuratierte, Adapter-lokale Map ``_CITY_POLLEN_REGION`` ([VERIFIED 2026-06-10]
gegen die Live-Antwort, ehrliche Teilabdeckung). Ein Match nur ueber die
region_id wuerde fuer mehrere Staedte die FALSCHE Teilregion erwischen (z.B.
Hamburg: 11 Inseln statt 12 Geest); daher matcht ``_pick_region`` gegen
``partregion_id`` mit Fallback auf ``region_id`` fuer Regionen ohne
Partregionen (``partregion_id == -1``, z.B. Berlin/Brandenburg). Ein
unbekannter Slug (nicht in der Map) liefert ``region_id=None`` und ehrliche
leere Pollen-Daten statt eines Crashs.

Sicherheit (T-07-IN, SSRF/Tampering): Die Hosts ``_POLLEN``/``_UVI`` sind
hartkodiert; die Partregion-ID stammt ausschliesslich aus der kuratierten Map
(nie User-Input), der ``slug`` kommt aus der Register-Allowlist.

Der Adapter ist rein gegenueber Pydantic/Resilienz: er baut KEINEN
``CanonicalRecord`` (das macht der Mapper in der Route) und kennt KEIN
Cache/Breaker (das liefert die Fassade). ``resp.raise_for_status()`` ist Pflicht,
damit ein 5xx als ``httpx.HTTPError`` an die Fassade durchschlaegt und der
STALE-ON-ERROR-Pfad greift.
"""

from __future__ import annotations

import httpx

# Hosts hartkodiert (T-07-IN SSRF): nur diese beiden oeffentlichen DWD-Dienste.
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
    "koeln": 41,  # Rhein.-Westfael. Tiefland
    "frankfurt-am-main": 92,  # Rhein-Main (NICHT 91 Nordhessen)
    "stuttgart": 112,  # Hohenlohe/mittlerer Neckar/Oberschwaben
    "duesseldorf": 41,  # Rhein.-Westfael. Tiefland
    "dortmund": 41,  # Rhein.-Westfael. Tiefland
    "essen": 41,  # Rhein.-Westfael. Tiefland
    "leipzig": 81,  # Tiefland Sachsen
    "bremen": 31,  # Westl. Niedersachsen/Bremen
    "dresden": 81,  # Tiefland Sachsen
    "hannover": 32,  # Oestl. Niedersachsen
    "nuernberg": 123,  # Bayern noerdl. der Donau
    "duisburg": 41,  # Rhein.-Westfael. Tiefland
    "bochum": 41,  # Rhein.-Westfael. Tiefland
    "wuppertal": 43,  # Mittelgebirge NRW (Bergisches Land)
    "bielefeld": 42,  # Ostwestfalen
    "bonn": 41,  # Rhein.-Westfael. Tiefland
    "muenster": 41,  # Rhein.-Westfael. Tiefland
    "wiesbaden": 92,  # Rhein-Main
    "kiel": 12,  # Geest, Schleswig-Holstein und Hamburg
    "mainz": 101,  # Rhein, Pfalz, Nahe und Mosel
    "magdeburg": 61,  # Tiefland Sachsen-Anhalt
    "erfurt": 71,  # Tiefland Thueringen
    "potsdam": 50,  # Brandenburg und Berlin (keine Partregionen)
    "saarbruecken": 103,  # Saarland
    "schwerin": 20,  # Mecklenburg-Vorpommern (keine Partregionen)
}

# Kuratierte Stadt -> UV-Mess-Stadt-Map (uvi.json ist nach UV-Mess-Staedten
# gegliedert, nicht nach Pollen-Grossregionen; T-07-IN). Fehlt der Slug, bleibt
# uv_index None (ehrliche Teilabdeckung, kein Crash).
_CITY_UVI_NAME: dict[str, str] = {
    "frankfurt-am-main": "Frankfurt/Main",
    "hannover": "Hannover",
    "muenchen": "München",
    "bonn": "Bonn",
}


def _pick_region(content: list[dict], partregion_id: int | None) -> dict | None:
    """Waehlt den ``content[]``-Eintrag der gewuenschten Teilregion (oder None).

    [VERIFIED 2026-06-10]: ``content[]`` hat 27 Eintraege bei 12 region_ids;
    der Match MUSS gegen ``partregion_id`` laufen, sonst gewinnt die erste
    (falsche) Teilregion einer Grossregion. Fallback fuer Regionen ohne
    Partregionen (``partregion_id == -1``): Match gegen ``region_id``.

    Pitfall 4: ``partregion_id is None`` (unbekannter Slug) liefert ehrlich
    ``None`` statt eines beliebigen Eintrags. Defensive ``.get`` gegen
    fehlerhafte Eintraege.
    """
    if partregion_id is None:
        return None
    for item in content:
        if item.get("partregion_id") == partregion_id:
            return item
    # Fallback: Grossregionen ohne Partregionen (partregion_id == -1) werden
    # in der Map ueber ihre region_id adressiert (z.B. 50 Brandenburg/Berlin).
    for item in content:
        if item.get("partregion_id") == -1 and item.get("region_id") == partregion_id:
            return item
    return None


def _pick_uv(content: list[dict], slug: str) -> float | None:
    """Liest den heutigen UV-Index der UV-Mess-Stadt der gewuenschten Stadt.

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
    ordnet den Slug ueber die kuratierte ``_CITY_POLLEN_REGION``-Map einer
    Teilregion zu ([VERIFIED 2026-06-10], Pitfall 4: NICHT stadtgenau) und gibt
    das flache raw-dict zurueck, das ``map_pollen_uv`` erwartet.

    Rueckgabe-Keys: ``slug``, ``region_id``, ``region_name``, ``pollen`` (dict je
    Pollenart), ``uv`` (float oder None). ``region_id``/``region_name`` tragen
    die getroffene Teilregion (bei Regionen ohne Partregionen die Grossregion).
    Ein unbekannter Slug liefert ``region_id=None`` und leere Pollen-Daten
    (kein Crash). ``raise_for_status`` schlaegt 5xx als ``httpx.HTTPError`` an
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
    # (partregion_id == -1) greifen region_id/region_name der Grossregion.
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
