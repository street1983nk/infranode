"""Stuttgart-Radzaehlstellen-Adapter ``fetch_stuttgart_radzaehl`` (DATA-40, Tier A).

Liefert je Stuttgarter Radzaehlstelle den JUENGSTEN Jahres-Summenwert keylos aus
der offenen CSV (CC BY 4.0, Landeshauptstadt Stuttgart, [VERIFIED 2026-06-23]):

  opendata.stuttgart.de/.../radfahrende_nach_zahlstelleund_jahr.csv

Schwaechster bike-counts-Datensatz (nur Jahreswerte, 2 Zaehlstellen, Stand bis
2022; Stundenwerte gibt es nur ueber Eco-Counter = ausgeschlossen). CSV ist
``;``-getrennt und cp1252-kodiert; Spalten ``Jahr;Zählstelle;Anzahl Radfahrende``
(Wert "NA" = kein Datum). KEINE Koordinaten -> ``lat``/``lon`` None.

Sicherheit (T-9-02 SSRF): Host hartkodiert. DoS-/Datenfehler-Schutz:
``raise_for_status()`` (5xx -> STALE-ON-ERROR der Fassade); Felder defensiv.
"""

from __future__ import annotations

import csv
import io

import httpx

_CSV_URL = (
    "https://opendata.stuttgart.de/dataset/151063a6-8367-4ef4-bbdf-a1120e97335e/"
    "resource/f1815117-5d64-44be-83f9-f9bf6f67a300/download/"
    "radfahrende_nach_zahlstelleund_jahr.csv"
)
_ENCODING = "cp1252"


async def fetch_stuttgart_radzaehl(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float,
    lon: float,
    radius_km: float = 30.0,
) -> dict:
    """Holt je Stuttgarter Zaehlstelle den juengsten Jahres-Summenwert.

    GET der CSV (cp1252), je ``Zählstelle`` die Zeile mit dem groessten ``Jahr``
    und gueltigem (nicht "NA") Zaehlwert. ``lat``/``lon``/``radius_km`` sind
    vertragskonform Teil der Signatur (ungenutzt). Rueckgabe: ``slug``,
    ``stations`` (je Station name/value/period=Jahr, Koordinaten None) und
    ``as_of`` (None: Jahreswert hat keinen Stundenzeitstempel).
    """
    resp = await http.get(_CSV_URL)
    resp.raise_for_status()
    reader = csv.DictReader(
        io.StringIO(resp.content.decode(_ENCODING, errors="replace")), delimiter=";"
    )
    # Je Station die juengste Zeile mit gueltigem Wert merken: name -> (jahr, value).
    latest: dict[str, tuple[int, int]] = {}
    for row in reader:
        name = (row.get("Zählstelle") or "").strip()
        jahr_raw = (row.get("Jahr") or "").strip()
        wert_raw = (row.get("Anzahl Radfahrende") or "").strip()
        if not name or not jahr_raw:
            continue
        try:
            jahr = int(jahr_raw)
            value = int(wert_raw)
        except ValueError:
            continue  # "NA"/leer -> ueberspringen
        if name not in latest or jahr > latest[name][0]:
            latest[name] = (jahr, value)

    stations = [
        {
            "station": name,
            "station_id": name,
            "lat": None,
            "lon": None,
            "value": value,
            "period": str(jahr),
        }
        for name, (jahr, value) in latest.items()
    ]
    return {"slug": slug, "stations": stations, "as_of": None}
