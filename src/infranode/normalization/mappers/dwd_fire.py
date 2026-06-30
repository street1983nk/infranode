"""Reiner DWD-Waldbrand-/Graslandfeuerindex-Mapper map_fire_danger.

Uebersetzt das flache raw-dict aus ``fetch_fire_danger`` deterministisch in einen
``CanonicalRecord`` mit ``FireDangerPayload``. Die Funktion ist rein: kein HTTP,
kein Logging, kein ``datetime.now()``. Der ``retrieved_at``-Zeitstempel wird
keyword-only injiziert, damit Tests deterministisch bleiben.

KRITISCH (GOV-03, Pitfall 5): DWD-Daten sind aufbereitet (Stationsauswahl), daher
traegt die Attribution ``modified=True`` und den wortgenauen GeoNutzV-Hinweis
"Datenbasis: Deutscher Wetterdienst, eigene Elemente ergänzt" (identisch zu
``map_weather``/``map_pollen_uv``). Lizenz und Tier sind hartkodiert (GeoNutzV,
Tier A).

KRITISCH (Pitfall 4, Ehrlichkeit): Der Index ist STATIONS-genau, NICHT stadtgenau.
``station_name``/``distance_km`` weisen die getroffene Station ehrlich im Payload
aus; ``geo`` bleibt ``None`` (keine vorgetaeuschte Stadt-Koordinate).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    FireDangerPayload,
    LicenseId,
    LicenseTier,
    SourceId,
)

_GEONUTZV_URL = (
    "https://www.dwd.de/DE/service/rechtliche_hinweise/rechtliche_hinweise.html"
)

# DWD-Waldbrandgefahrenindex: 5 Stufen (1=sehr gering ... 5=sehr hoch).
_WBI_LABELS: dict[int, str] = {
    1: "sehr geringe Gefahr",
    2: "geringe Gefahr",
    3: "mittlere Gefahr",
    4: "hohe Gefahr",
    5: "sehr hohe Gefahr",
}


def _label(level: int | None) -> str | None:
    """Mappt eine Gefahrenstufe (1..5) auf das deutsche Klartext-Label (oder None)."""
    if level is None:
        return None
    return _WBI_LABELS.get(level)


def map_fire_danger(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe DWD-Waldbrandindex-Daten auf einen ``CanonicalRecord`` ab.

    ``observed_at`` bleibt ``None`` (DWD liefert einen Tagesindex je Station, keinen
    Messzeitpunkt). Der ``retrieved_at``-Zeitstempel wird injiziert (kein
    ``datetime.now()`` im Mapper), damit das Ergebnis deterministisch ist. Die
    Join-Keys ``ags``/``wikidata_qid`` werden aus dem Register durchgereicht
    (Default ``None``). ``geo=None`` (Pitfall 4: stationsnah, nicht stadtgenau).
    """
    wbi_level = raw.get("wbi_level")
    glfi_level = raw.get("glfi_level")
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.DWD_FIRE,
        license_id=LicenseId.GEONUTZV,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Datenbasis: Deutscher Wetterdienst, eigene Elemente ergänzt",
            license_url=_GEONUTZV_URL,
            modified=True,
        ),
        payload=FireDangerPayload(
            wbi_level=wbi_level,
            wbi_label=_label(wbi_level),
            glfi_level=glfi_level,
            glfi_label=_label(glfi_level),
            station_name=raw.get("station_name"),
            station_id=raw.get("station_id"),
            bundesland=raw.get("bundesland"),
            distance_km=raw.get("distance_km"),
            forecast_date=raw.get("forecast_date"),
            updated_at=raw.get("updated_at"),
        ),
    )
