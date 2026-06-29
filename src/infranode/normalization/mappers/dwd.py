"""Reiner DWD/Bright-Sky-Wetter-Mapper map_weather (DATA-03, GOV-03).

Übersetzt das flache Bright-Sky-raw-dict deterministisch in einen
``CanonicalRecord`` mit ``WeatherPayload``. Die Funktion ist rein: kein HTTP,
kein Logging, kein ``datetime.now()``. Der ``retrieved_at``-Zeitstempel wird
keyword-only injiziert, damit Tests deterministisch bleiben.

KRITISCH (GOV-03, Pitfall 3): DWD-Daten sind aufbereitet, daher trägt die
Attribution ``modified=True`` und den wortgenauen GeoNutzV-Hinweis
"Datenbasis: Deutscher Wetterdienst, eigene Elemente ergänzt". Lizenz und Tier
sind hartkodiert (GeoNutzV, Tier A: permissiv lizenziert).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    GeoPoint,
    LicenseId,
    LicenseTier,
    SourceId,
    WeatherPayload,
)

_GEONUTZV_URL = (
    "https://www.dwd.de/DE/service/rechtliche_hinweise/rechtliche_hinweise.html"
)


def map_weather(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe Bright-Sky-Wetterdaten auf einen ``CanonicalRecord`` ab.

    ``observed_at`` kommt aus dem Bright-Sky-Zeitstempel des Messwerts. Der
    ``retrieved_at``-Zeitstempel wird injiziert (kein ``datetime.now()`` im
    Mapper), damit das Ergebnis deterministisch und voll testbar bleibt. Die
    Join-Keys ``ags``/``wikidata_qid`` werden aus dem Register durchgereicht
    (Default ``None``); ``WeatherPayload.station_id`` wird aus
    ``raw["dwd_station_id"]`` (echte DWD-Mess-Stations-ID) gesetzt und dient als
    fachlicher Schlüssel für ``record_id`` (ARCH-02).
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=GeoPoint(lat=raw["lat"], lon=raw["lon"]),
        observed_at=raw.get("observed_at"),
        retrieved_at=retrieved_at,
        source=SourceId.DWD,
        license_id=LicenseId.GEONUTZV,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Datenbasis: Deutscher Wetterdienst, eigene Elemente ergänzt",
            license_url=_GEONUTZV_URL,
            modified=True,
        ),
        payload=WeatherPayload(
            station_id=raw.get("dwd_station_id"),
            temperature_c=raw.get("temperature_c"),
            humidity=raw.get("humidity"),
            wind_speed=raw.get("wind_speed"),
            condition=raw.get("condition"),
        ),
    )
