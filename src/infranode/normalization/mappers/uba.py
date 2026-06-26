"""Reiner UBA-Luft-Mapper map_air_uba (DATA-10, GOV-01/03, Tier A).

Uebersetzt das flache UBA-raw-dict deterministisch in einen ``CanonicalRecord``
mit dem WIEDERVERWENDETEN ``AirQualityPayload`` (kind=air_quality, kein neues
Air-Payload). Die Funktion ist rein: kein HTTP, kein Logging, kein
``datetime.now()``. Der ``retrieved_at``-Zeitstempel wird keyword-only injiziert,
damit Tests deterministisch bleiben.

KRITISCH (Lizenz-Klassifikation GOV-02): UBA ist Tier A (offene Lizenz),
``license_id=DL_DE_BY_2_0``, ``license_tier=A``. Der UBA-Record wird ueber die
Route ``/air-uba`` (Tier-A-Bestand) ausgeliefert.

KRITISCH (GOV-03): UBA-Daten unter Datenlizenz Deutschland Namensnennung 2.0 sind
NICHT aufbereitet (anders als DWD-Wetter), daher traegt die Attribution KEIN
``modified`` (Default ``False``) und die wortgenaue Namensnennung
"Umweltbundesamt".
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    AirQualityPayload,
    Attribution,
    CanonicalRecord,
    GeoPoint,
    LicenseId,
    LicenseTier,
    SourceId,
)

_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"


def map_air_uba(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe UBA-Luftdaten auf einen ``CanonicalRecord`` (Tier A) ab.

    ``observed_at`` kommt aus dem UBA-Messzeitpunkt (``raw["observed_at"]``); der
    ``retrieved_at``-Zeitstempel wird injiziert (kein ``datetime.now()`` im
    Mapper), damit das Ergebnis deterministisch bleibt. Die Join-Keys
    ``ags``/``wikidata_qid`` werden aus dem Register durchgereicht (Default
    ``None``). Der Payload nutzt das bestehende ``AirQualityPayload``; die
    UBA-Station-ID dient als fachlicher Schluessel fuer die ``record_id``
    (ARCH-02). Die Attribution traegt KEIN ``modified`` (DL-DE/BY, GOV-03).
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=GeoPoint(lat=raw["lat"], lon=raw["lon"]),
        observed_at=raw.get("observed_at"),
        retrieved_at=retrieved_at,
        source=SourceId.UBA,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Umweltbundesamt",
            license_url=_DL_DE_BY_URL,
        ),
        payload=AirQualityPayload(
            station_id=raw.get("station_id"),
            pm10=raw.get("pm10"),
            pm25=raw.get("pm25"),
            no2=raw.get("no2"),
            o3=raw.get("o3"),
            so2=raw.get("so2"),
        ),
    )
