"""SMARD-Adapter: Tageswerte der Bundesnetzagentur-Strommarktdaten (Tier A, CC BY 4.0).

``fetch_smard`` holt den jüngsten verfügbaren Tageswert einer SMARD-Zeitreihe
(``filter_id`` + ``region``) über die keylose ``chart_data``-API: erst der
Tages-Index (Liste der Datei-Buckets), dann der jüngste Bucket, daraus der letzte
Datenpunkt mit Wert (``None``-Werte am Reihenende werden übersprungen).

Damit deckt InfraNode die Verbrauchs- und Preis-Seite ab (Ergänzung zu MaStR =
installierte Erzeugung): Filter 410 = Stromverbrauch (Netzlast), 4169 =
Day-ahead-Großhandelspreis. Verbrauch liegt je Regelzone vor (50Hertz/Amprion/
TenneT/TransnetBW), der Preis bundesweit (Gebotszone DE/LU).

Sicherheit (T-05-08 SSRF): Der Host ist in ``_BASE`` hartkodiert. ``filter_id``
und ``region`` stammen aus festen Allowlists des Aufrufers (City->Zone-Map in
der Route), NIE aus User-Input; der Adapter prüft sie defensiv erneut, bevor er
sie in den Pfad interpoliert. ``raise_for_status`` nach jedem Call ist Pflicht,
damit ein 5xx als ``httpx.HTTPError`` an die Resilienz-Fassade durchschlägt.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx

# Host hartkodiert (SSRF-Schutz, T-05-08).
_BASE = "https://www.smard.de/app/chart_data"

# Feste Allowlists (Argument-Guard): nur diese Kennzahlen/Regionen sind erlaubt.
ALLOWED_FILTERS = {
    "410": "Stromverbrauch: Gesamt (Netzlast)",
    "4169": "Großhandelspreis Day-ahead",
}
ALLOWED_REGIONS = {"DE", "50Hertz", "Amprion", "TenneT", "TransnetBW"}


async def fetch_smard(http: httpx.AsyncClient, *, filter_id: str, region: str) -> dict:
    """Jüngster Tageswert einer SMARD-Zeitreihe als flaches raw-dict.

    Rückgabe: ``{filter_id, region, value, series_date}``. ``value`` ist ``None``
    (und ``series_date`` ``None``), wenn die Reihe leer ist; der Mapper/Aufrufer
    behandelt das als ``no_data``.
    """
    if filter_id not in ALLOWED_FILTERS:
        raise ValueError(f"unzulaessiger SMARD-Filter: {filter_id!r}")
    if region not in ALLOWED_REGIONS:
        raise ValueError(f"unzulaessige SMARD-Region: {region!r}")

    empty = {
        "filter_id": filter_id, "region": region, "value": None, "series_date": None,
    }

    index = await http.get(f"{_BASE}/{filter_id}/{region}/index_day.json")
    index.raise_for_status()
    timestamps = (index.json() or {}).get("timestamps") or []
    if not timestamps:
        return empty

    bucket = timestamps[-1]
    url = f"{_BASE}/{filter_id}/{region}/{filter_id}_{region}_day_{bucket}.json"
    data = await http.get(url)
    data.raise_for_status()
    series = [
        (t, v) for t, v in ((data.json() or {}).get("series") or []) if v is not None
    ]
    if not series:
        return empty

    ts, value = series[-1]
    day = datetime.fromtimestamp(ts / 1000, UTC).date().isoformat()
    return {
        "filter_id": filter_id,
        "region": region,
        "value": float(value),
        "series_date": day,
    }
