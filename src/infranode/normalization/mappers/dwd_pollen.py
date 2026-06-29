"""Reiner DWD-Pollen/UV-Mapper map_pollen_uv (DATA-14, GOV-03).

Übersetzt das flache DWD-raw-dict aus ``fetch_pollen_uv`` deterministisch in
einen ``CanonicalRecord`` mit ``PollenUvPayload``. Die Funktion ist rein: kein
HTTP, kein Logging, kein ``datetime.now()``. Der ``retrieved_at``-Zeitstempel
wird keyword-only injiziert, damit Tests deterministisch bleiben.

KRITISCH (GOV-03, Pitfall 5): DWD-Daten sind aufbereitet, daher trägt die
Attribution ``modified=True`` und den wortgenauen GeoNutzV-Hinweis
"Datenbasis: Deutscher Wetterdienst, eigene Elemente ergänzt" (identisch zu
``map_weather``). Lizenz und Tier sind hartkodiert (GeoNutzV, Tier A).

KRITISCH (Pitfall 4, Ehrlichkeit): Die Daten sind GROSSREGION-genau, NICHT
stadtgenau. ``region_id``/``region_name`` weisen die Großregion ehrlich im
Payload aus; ``geo`` bleibt ``None`` (keine vorgetäuschte Stadt-Koordinate).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    PollenUvPayload,
    SourceId,
)

_GEONUTZV_URL = (
    "https://www.dwd.de/DE/service/rechtliche_hinweise/rechtliche_hinweise.html"
)


def map_pollen_uv(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet rohe DWD-Pollen/UV-Daten auf einen ``CanonicalRecord`` ab.

    ``observed_at`` bleibt ``None`` (DWD liefert Tagesindex je Großregion, keinen
    Messzeitpunkt). Der ``retrieved_at``-Zeitstempel wird injiziert (kein
    ``datetime.now()`` im Mapper), damit das Ergebnis deterministisch ist. Die
    Join-Keys ``ags``/``wikidata_qid`` werden aus dem Register durchgereicht
    (Default ``None``). ``geo=None`` (Pitfall 4: Großregion, nicht stadtgenau).
    """
    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.DWD_POLLEN,
        license_id=LicenseId.GEONUTZV,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="Datenbasis: Deutscher Wetterdienst, eigene Elemente ergänzt",
            license_url=_GEONUTZV_URL,
            modified=True,
        ),
        payload=PollenUvPayload(
            region_id=raw.get("region_id"),
            region_name=raw.get("region_name"),
            pollen=raw.get("pollen", {}),
            uv_index=raw.get("uv"),
        ),
    )
