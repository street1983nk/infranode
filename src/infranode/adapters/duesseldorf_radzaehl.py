"""Düsseldorf-Radzählstellen-Adapter ``fetch_duesseldorf_radzaehl`` (DATA-40, Tier A).

Liefert je Düsseldorfer Dauerzählstelle den Jahres-Summenwert 2025 keylos aus den
offenen Stunden-CSVs des städtischen Open-Data-Portals (DL-DE/BY 2.0,
Landeshauptstadt Düsseldorf, [VERIFIED 2026-07-04]):

  opendata.duesseldorf.de/dataset/wetterabhängige-jahresübersicht-der-
  dauerzählstellen-radverkehr-2025

Befund [VERIFIED 2026-07-04]: 23 Stations-CSVs (je Station eine Datei), alle
HTTP 200 ohne Redirect, Content-Type text/csv, utf-8 OHNE BOM, ``;``-getrennt,
CRLF. Kopf = ``Zeit`` + 1-2 Richtungsspalten + Wetterspalten (ab ``Symbol
Wetter``); Datenzeilen = Stundenwerte als plain int (8759 Zeilen = Jahr 2025).
Der Jahreswert je Station ist die Summe aller gültigen Stundenwerte über alle
Richtungsspalten (Aggregation -> Veränderungshinweis nach DL-DE/BY 2.0 im
Mapper, ``attribution.modified=True``). Ein DKAN-Datastore existiert nur je
Einzel-Resource (keine gebündelte Abfrage), daher je-Station-CSVs mit Semaphore.

Koordinaten: Das separate Standorte-Dataset (DL-DE/Zero 2.0) matcht namentlich
NICHT trivial auf die Jahrgangs-CSVs (19 abweichend benannte Zeilen für 23
Stationen, teils je Fahrtrichtung) -> ``lat``/``lon`` None wie Köln/Essen.

Eco-Visio/Eco-Counter (data.eco-counter.com, idOrganisme 857) ist auf dem
Portal nur VERLINKT und bleibt bewusst ausgeschlossen (Owner-Entscheidung
2026-06-23: kein Eco-Counter, Lizenz ungeklärt); genutzt wird ausschliesslich
die Portal-CSV-Quelle auf opendata.duesseldorf.de.

Sicherheit (T-9-02 SSRF): Host + Pfade hartkodiert, kein User-Input in URLs.
DoS-Schutz (T-Q-02): max. 5 parallele GETs; das Gesamtergebnis wird von der
Fassade unter EINEM Cache-Key gehalten (TTL 86400/2592000 -> max. 1 Upstream-
Lauf pro Tag). Datenfehler (T-Q-03): defensives ``_to_int``; einzelne tote
Datei -> Station überspringen (kein Total-Fail); erst wenn KEINE Datei
erreichbar ist, wird der erste Fehler geworfen (5xx -> STALE-ON-ERROR).
"""

from __future__ import annotations

import asyncio
import csv
import io

import httpx

_BASE = "https://opendata.duesseldorf.de/sites/default/files/"

# Je Station (Portal-Name, finale Download-URL). URLs verbatim aus dem
# DCAT-Katalog (/data.json), Umlaute bereits url-kodiert, KEINE Redirects
# [VERIFIED 2026-07-04].
_STATION_URLS: tuple[tuple[str, str], ...] = (
    ("Bilker Allee", _BASE + "Bilker_Allee_IN_OUT_2025_0.csv"),
    ("Christophstraße", _BASE + "Christophstra%C3%9Fe_IN_OUT_2025.csv"),
    ("Elisabethstraße", _BASE + "Elisabethstra%C3%9Fe_2025.csv"),
    ("Fleher Deich", _BASE + "Fleher_Deich_IN_OUT_2025.csv"),
    (
        "Fleher Deich Ost stromaufwärts",
        _BASE + "Fleher_Deich_ost_stromaufw%C3%A4rts_2025.csv",
    ),
    ("Fleher Deich Rampe", _BASE + "Fleher_Deich_Rampe_IN_OUT_2025.csv"),
    (
        "Fleher Deich West stromabwärts",
        _BASE + "Fleher_Deich_west_stromabw%C3%A4rts_2025.csv",
    ),
    ("Friedrichstraße", _BASE + "Friedrichstra%C3%9Fe_2025.csv"),
    ("Hofgartenrampe Oederallee", _BASE + "Hofgartenrampe_Oederallee_IN_OUT_2025.csv"),
    ("Kirchfeldstraße", _BASE + "Kirchfeldstra%C3%9Fe_IN_OUT_2025.csv"),
    ("KÖ Steinstraße", _BASE + "K%C3%96_Steinstra%C3%9Fe_IN_OUT_2025.csv"),
    (
        "Koblenzer einwärts nach TLS",
        _BASE + "Koblenzer_einw%C3%A4rts_nach_TLS_IN_OUT_2025.csv",
    ),
    (
        "Koblenzer einwärts vor TLS",
        _BASE + "Koblenzer_einw%C3%A4rts_vor_TLS_IN_OUT_2025.csv",
    ),
    ("Koblenzer stadtauswärts", _BASE + "Koblenzer_stadtausw%C3%A4rts_2025.csv"),
    (
        "Kölner Straße 186 Radweg",
        _BASE + "K%C3%B6lner_Stra%C3%9Fe_186_Radweg_IN_OUT_2025.csv",
    ),
    ("Lohauser Deich", _BASE + "Lohauser_Deich_IN_OUT_2025.csv"),
    ("Luegallee", _BASE + "Luegallee_IN_OUT_2025.csv"),
    ("Mannesmannufer", _BASE + "Mannesmannufer_IN_OUT_2025.csv"),
    (
        "Münchner Ickerswarder Straße",
        _BASE + "M%C3%BCnchner_Ickerswarder_Stra%C3%9Fe_IN_OUT_2025.csv",
    ),
    ("Oberkasseler Brücke", _BASE + "Oberkasseler_Br%C3%BCcke_IN_OUT_2025.csv"),
    ("OKB Nord", _BASE + "OKB_Nord_IN_OUT_2025_0.csv"),
    ("OKB Süd", _BASE + "OKB_S%C3%BCd_IN_OUT_2025.csv"),
    (
        "Pempelforter Straße 42 Mischverkehr",
        _BASE + "Pempelforter_Stra%C3%9Fe_42_Mischverkehr_IN_OUT_2025.csv",
    ),
)

_ENCODING = "utf-8"
_YEAR = "2025"
# Erste Wetterspalte im Kopf; alles zwischen "Zeit" und dieser Spalte sind
# Richtungs-Zählspalten (1-2 je Station) [VERIFIED 2026-07-04].
_WEATHER_COL = "Symbol Wetter"
_MAX_PARALLEL = 5


def _to_int(cell: str) -> int | None:
    """Parst einen Ganzzahl-Zellwert defensiv (leer/Unsinn -> None).

    Stundenwerte sind plain ints; Tausenderpunkte/Leerzeichen werden trotzdem
    defensiv entfernt (deutsche Zahlformate, T-Q-03).
    """
    digits = (cell or "").strip().replace(".", "").replace(" ", "")
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _sum_station_csv(text: str) -> int | None:
    """Summiert alle gültigen Stundenwerte einer Stations-CSV (sonst None).

    Zählspalten = Kopfspalten zwischen ``Zeit`` und ``Symbol Wetter``. Fehlt
    die Wetterspalte (Format-Drift) oder gibt es keine gültige Zelle, wird die
    Station mit None übersprungen (kein Total-Fail, T-Q-03/T-Q-04).
    """
    reader = csv.reader(io.StringIO(text), delimiter=";")
    rows = list(reader)
    if not rows:
        return None
    header = [cell.strip() for cell in rows[0]]
    try:
        weather_idx = header.index(_WEATHER_COL)
    except ValueError:
        return None
    if weather_idx < 2:
        return None
    total: int | None = None
    for row in rows[1:]:
        for idx in range(1, weather_idx):
            value = _to_int(row[idx]) if idx < len(row) else None
            if value is None:
                continue
            total = (total or 0) + value
    return total


async def fetch_duesseldorf_radzaehl(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float,
    lon: float,
    radius_km: float = 30.0,
) -> dict:
    """Holt je Düsseldorfer Zählstelle den Jahres-Summenwert 2025 (23 CSVs).

    Max. 5 parallele GETs (Semaphore); je Station Summe aller gültigen
    Stundenwerte über alle Richtungsspalten. Einzelne tote Datei -> Station
    überspringen; erst wenn ALLE Dateien fehlschlagen, wird der erste Fehler
    geworfen (Fassade -> STALE-ON-ERROR/503). ``lat``/``lon``/``radius_km``
    sind vertragskonform Teil der Signatur (ungenutzt; die Jahrgangs-CSVs
    liefern keine Koordinaten). Rückgabe: ``slug``, ``stations`` (je Station
    name/value/period=Jahr, Koordinaten None) und ``as_of`` (None: Jahreswert
    hat keinen Stundenzeitstempel).
    """
    semaphore = asyncio.Semaphore(_MAX_PARALLEL)

    async def _fetch_one(name: str, url: str) -> tuple[str, int | None]:
        async with semaphore:
            resp = await http.get(url)
            resp.raise_for_status()
        return name, _sum_station_csv(resp.content.decode(_ENCODING, errors="replace"))

    results = await asyncio.gather(
        *(_fetch_one(name, url) for name, url in _STATION_URLS),
        return_exceptions=True,
    )

    stations: list[dict] = []
    fetched = 0
    first_error: BaseException | None = None
    for outcome in results:
        if isinstance(outcome, BaseException):
            if first_error is None:
                first_error = outcome
            continue
        fetched += 1
        name, total = outcome
        if total is None:
            continue
        stations.append(
            {
                "station": name,
                "station_id": name,
                "lat": None,
                "lon": None,
                "value": total,
                "period": _YEAR,
            }
        )
    if fetched == 0 and first_error is not None:
        raise first_error
    return {"slug": slug, "stations": stations, "as_of": None}
