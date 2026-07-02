"""Köln-Radzählstellen-Adapter ``fetch_koeln_radzaehl`` (DATA-40, Tier A).

Liefert je Kölner Radzählstelle den Jahres-Summenwert 2022 keylos aus der offenen
CSV des städtischen Open-Data-Portals (DL-DE/Zero 2.0, Stadt Köln,
[VERIFIED 2026-07-02]):

  offenedaten-koeln.de/dataset/fahrrad-verkehrsdaten-koeln-2022

Bewusst die PORTAL-CSV (nicht das Eco-Counter-/Eco-Visio-Dashboard): die CSV liegt
direkt auf dem Stadtportal und ist eindeutig DL-DE/Zero lizenziert; damit bleibt
die Owner-Entscheidung 2026-06-23 (kein Eco-Counter, Lizenz ungeklärt) unberührt.
Schwächster bike-counts-Datensatz (nur Jahreswerte, Stand 2022; Stundenwerte nur
über Eco-Counter = ausgeschlossen), analog Stuttgart.

Format: ``;``-getrennt, cp1252-kodiert, WEIT (Kopfzeile = leere Zelle + je Station
ein Spaltenkopf, Datenzeilen = Monat + Monatswert je Station, deutsche Tausender-
Punkte "88.423"). Der Jahreswert ist die Summe der Monatswerte je Station. KEINE
Koordinaten -> ``lat``/``lon`` None.

Sicherheit (T-9-02 SSRF): Host + Pfad hartkodiert. DoS-/Datenfehler-Schutz:
``raise_for_status()`` (5xx -> STALE-ON-ERROR der Fassade); Felder defensiv.
"""

from __future__ import annotations

import csv
import io

import httpx

# Dateiname ist auf dem Portal doppelt URL-kodiert (%2520 = literales %20 im
# Dateinamen); die URL daher verbatim übernehmen, NICHT erneut kodieren.
_CSV_URL = (
    "https://www.offenedaten-koeln.de/sites/default/files/distribution/"
    "Radverkehr%2520f%25C3%25BCr%2520Offene%2520Daten%2520K%25C3%25B6ln%25202022.csv"
)
_ENCODING = "cp1252"
_YEAR = "2022"


def _to_int(cell: str) -> int | None:
    """Parst einen deutschen Ganzzahl-Zellwert ("88.423") defensiv (sonst None)."""
    digits = (cell or "").strip().replace(".", "").replace(" ", "")
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


async def fetch_koeln_radzaehl(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float,
    lon: float,
    radius_km: float = 30.0,
) -> dict:
    """Holt je Kölner Zählstelle den Jahres-Summenwert 2022 aus der Portal-CSV.

    GET der CSV (cp1252, weites Format), je Stations-Spalte die Summe aller
    gültigen Monatswerte. ``lat``/``lon``/``radius_km`` sind vertragskonform Teil
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

    # Kopfzeile: erste Zelle leer, danach je Station ein Name.
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
