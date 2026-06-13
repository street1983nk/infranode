"""Stadt-Register-Modell mit Cross-Walk-IDs (CORE-03).

Definiert ``CityRegistryEntry`` als gefrorenes Wert-Objekt (Pitfall 2:
``frozen=True`` gegen Manipulation, T-02-06). Pflicht-Cross-Walk-IDs sind die
Wikidata-QID und die OSM-Relation; DWD-Station und GTFS-Stop sind optionale
Felder (Slots vorhanden, leer/None), die erst Phase 5/6 befuellt. ``slug`` ist
ASCII (muenchen), ``name_de`` traegt korrekte Umlaute (München).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from infranode.normalization import GeoPoint


class CityRegistryEntry(BaseModel):
    """Ein validierter Stadt-Eintrag mit stabilen Cross-Walk-Kennungen.

    QID und OSM-Relation sind per SPARQL verifiziert und Pflicht. Die
    DWD-/GTFS-Felder existieren als Slots (CORE-03 verlangt die Spalten),
    bleiben in Phase 2 aber leer/None.

    ``ags`` ist der amtliche 8-stellige Gemeindeschluessel und dient als
    dim_city-Join-Anker gegen Zensus/Wahlen/MaStR (ARCH-02). ``state`` ist das
    bereits vorhandene Bundesland-Kuerzel und dient ebenfalls als Join-Anker
    (kein neues Feld noetig).
    """

    model_config = ConfigDict(frozen=True)

    slug: str
    name_de: str
    state: str
    ags: str = Field(pattern=r"^\d{8}$")
    is_state_capital: bool
    qid: str = Field(pattern=r"^Q\d+$")
    osm_relation: int = Field(gt=0)
    geo: GeoPoint
    population: int | None = None
    dwd_station_ids: tuple[str, ...] = ()
    gtfs_stop_ref: str | None = None
    # Abdeckungsgrad (Expansion 2026-06): "full" = handverifizierte Kern-Stadt mit
    # allen Quellen inkl. hand-kuratierter Maps (LHP-Pegel, DWD-Pollen-Region,
    # DIVI-Kreis, Stadt-Baustellen-Connector); "auto" = ueber 100k-EW-Stadt, die
    # NUR von den AGS-/geo-automatischen Tier-A-Quellen bedient wird, hand-
    # kuratierte Quellen liefern ehrliches no_data. Default "full" (Kern-Register).
    coverage: str = Field(default="full", pattern=r"^(full|auto)$")
