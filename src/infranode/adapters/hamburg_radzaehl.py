"""Hamburg-Radzählstelle-Adapter ``fetch_hamburg_radzaehl`` (DATA-40, Tier A).

Liefert den jüngsten Stundenwert der Hamburger Rad-Dauerzählstelle "Gurlittinsel"
(die FHH betreibt aktuell genau diese eine offene Dauerzählstelle) keylos aus dem
Open-Data-CSV-Export (DL-DE/BY 2.0, [VERIFIED 2026-06-23]):

  https://daten-hamburg.de/transport_verkehr/dauerzaehlstellen_rad/export_radverkehr.csv

CSV-Aufbau (UTF-8, [VERIFIED 2026-06-29]: Bytes ``c3 a4`` = "ä"): Zeile 1 =
Stationsname ("Gurlittinsel;;"),
Zeile 2 = Spaltenkopf ``Datum;Zeitraum (von);Anzahl Fahrräder``, danach je Stunde
eine Zeile ``TT.MM.JJJJ;HH:MM Uhr;Anzahl`` (Historie seit 2014). Die LETZTE
Datenzeile ist der frischeste Stundenwert.

Die Koordinate der Station ist statisch eingebettet ([VERIFIED 2026-06-23 via
WFS HH_WFS_Dauerzaehlstellen_Rad, gml:pos 53.559240 10.008480]); der WFS liefert
nur GML (kein JSON) und liegt auf einem Hamburg-Host, der die Produktions-Box-IP
teils blockt -> die statische Koordinate hält den Adapter auf EINEN Host
(daten-hamburg.de) und unabhängig vom GML-Parsing.

Sicherheit (T-9-02 SSRF): Host hartkodiert. DoS-/Datenfehler-Schutz:
``raise_for_status()`` (5xx -> STALE-ON-ERROR der Fassade); Felder defensiv.
"""

from __future__ import annotations

import csv
import io

import httpx

_CSV_URL = (
    "https://daten-hamburg.de/transport_verkehr/dauerzaehlstellen_rad/"
    "export_radverkehr.csv"
)
# Quelle ist echtes UTF-8 (live verifiziert 2026-06-29); cp1252 war falsch.
_ENCODING = "utf-8"
# [VERIFIED 2026-06-23 via WFS gml:pos] Dauerzählstelle "An der Gurlittinsel".
_STATION_LAT = 53.559240
_STATION_LON = 10.008480


def _to_iso(datum: str, zeit: str) -> str | None:
    """``TT.MM.JJJJ`` + ``HH:MM Uhr`` -> ISO ``JJJJ-MM-TTTHH:MM:00`` (sonst None)."""
    datum = (datum or "").strip()
    zeit = (zeit or "").strip().replace("Uhr", "").strip()
    parts = datum.split(".")
    if len(parts) != 3 or not zeit:
        return None
    tag, monat, jahr = (p.strip() for p in parts)
    hhmm = zeit.split(":")
    if len(hhmm) < 2:
        return None
    try:
        return (
            f"{int(jahr):04d}-{int(monat):02d}-{int(tag):02d}"
            f"T{int(hhmm[0]):02d}:{int(hhmm[1]):02d}:00"
        )
    except ValueError:
        return None


async def fetch_hamburg_radzaehl(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float,
    lon: float,
    radius_km: float = 30.0,
) -> dict:
    """Holt den jüngsten Stundenwert der Hamburger Rad-Dauerzählstelle.

    GET des CSV-Exports (cp1252), Stationsname aus Zeile 1, dann die LETZTE
    Datenzeile mit gültiger Anzahl als frischster Stundenwert. ``lat``/``lon``/
    ``radius_km`` sind vertragskonform Teil der Signatur (ungenutzt; eine feste
    Station). Rueckgabe: ``slug``, ``stations`` (0 oder 1) und ``as_of``.
    """
    resp = await http.get(_CSV_URL)
    resp.raise_for_status()
    lines = resp.content.decode(_ENCODING, errors="replace").splitlines()
    if len(lines) < 3:
        return {"slug": slug, "stations": [], "as_of": None}

    station_name = lines[0].split(";", 1)[0].strip() or "Gurlittinsel"
    reader = csv.reader(io.StringIO("\n".join(lines[1:])), delimiter=";")
    next(reader, None)  # Spaltenkopf überspringen
    last: tuple[str, int] | None = None  # (iso_period, value)
    for row in reader:
        if len(row) < 3:
            continue
        period = _to_iso(row[0], row[1])
        try:
            value = int(str(row[2]).strip())
        except (TypeError, ValueError):
            continue
        if period:
            last = (period, value)

    if last is None:
        return {"slug": slug, "stations": [], "as_of": None}

    period, value = last
    station = {
        "station": station_name,
        "station_id": "gurlittinsel",
        "lat": _STATION_LAT,
        "lon": _STATION_LON,
        "value": value,
        "period": period,
    }
    return {"slug": slug, "stations": [station], "as_of": period}
