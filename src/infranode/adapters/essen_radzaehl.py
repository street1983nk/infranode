"""Essen-Radzählstellen-Adapter ``fetch_essen_radzaehl`` (DATA-40, Tier A).

Liefert je Essener Radzählstelle den Jahres-Summenwert keylos aus der offenen
Jahres-CSV ("kumuliert") des städtischen Open-Data-Portals (DL-DE/BY 2.0, Stadt
Essen, [VERIFIED 2026-07-02]):

  opendata.essen.de/dataset/radverkehrszählungen

Format: ``;``-getrennt, utf-8 mit BOM, WEIT (Kopf = ``Datum`` + je Station ein
Spaltenkopf, Datenzeilen = Tageswert je Station als plain int). Der Jahreswert ist
die Summe der Tageswerte je Station. KEINE Koordinaten -> ``lat``/``lon`` None.
Schwächster bike-counts-Datensatz (nur Jahreswerte), analog Stuttgart/Köln.

Sicherheit (T-9-02 SSRF): Host + Pfad hartkodiert. DoS-/Datenfehler-Schutz:
``raise_for_status()`` (5xx -> STALE-ON-ERROR der Fassade); Felder defensiv.
"""

from __future__ import annotations

import csv
import io

import httpx

# Jüngste vollständige Jahres-CSV ("kumuliert"); die Quartals-Dateien des
# laufenden Jahres bleiben aussen vor (unvollständig). URL verbatim (Leer-/
# Umlaut-Zeichen sind bereits url-kodiert).
_CSV_URL = (
    "https://opendata.essen.de/sites/default/files/"
    "Radverkehrsz%C3%A4hlung%202025%20kumuliert.csv"
)
_ENCODING = "utf-8-sig"
_YEAR = "2025"


def _to_int(cell: str) -> int | None:
    """Parst einen Ganzzahl-Zellwert defensiv (leer/Unsinn -> None)."""
    digits = (cell or "").strip()
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


async def fetch_essen_radzaehl(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float,
    lon: float,
    radius_km: float = 30.0,
) -> dict:
    """Holt je Essener Zählstelle den Jahres-Summenwert aus der kumulierten CSV.

    GET der CSV (utf-8-sig, weites Format), je Stations-Spalte die Summe aller
    gültigen Tageswerte. ``lat``/``lon``/``radius_km`` sind vertragskonform Teil
    der Signatur (ungenutzt; die Quelle liefert keine Koordinaten). Rückgabe:
    ``slug``, ``stations`` (je Station name/value/period=Jahr, Koordinaten None)
    und ``as_of`` (None: Jahreswert hat keinen Stundenzeitstempel).
    """
    resp = await http.get(_CSV_URL)
    resp.raise_for_status()
    reader = csv.reader(
        io.StringIO(resp.content.decode(_ENCODING, errors="replace")), delimiter=";"
    )
    rows = list(reader)
    if not rows:
        return {"slug": slug, "stations": [], "as_of": None}

    # Kopfzeile: erste Spalte "Datum", danach je Station ein Name.
    names = [h.strip() for h in rows[0][1:]]
    totals: list[int | None] = [None] * len(names)
    for row in rows[1:]:
        for idx in range(len(names)):
            value = _to_int(row[idx + 1]) if idx + 1 < len(row) else None
            if value is None:
                continue
            totals[idx] = (totals[idx] or 0) + value

    stations = [
        {
            "station": name,
            "station_id": name,
            "lat": None,
            "lon": None,
            "value": total,
            "period": _YEAR,
        }
        for name, total in zip(names, totals, strict=False)
        if name and total is not None
    ]
    return {"slug": slug, "stations": stations, "as_of": None}
