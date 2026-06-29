"""Reiner Zensus-Gitter-Mapper map_population_density (DATA-OSM-Tier-2).

Errechnet aus dem aggregierten raw-dict (Summe Einwohner + Zahl der bewohnten
100m-Zellen) die bewohnte Fläche (Zellen * 0.01 km2) und die Einwohnerdichte
(Einwohner je km2 über die bewohnte Fläche). Rein, deterministisch (kein now()).
Lizenz DL-DE/BY 2.0 (Tier A), Quelle Zensus 2022 (Statistische Ämter).
"""

from __future__ import annotations

from datetime import datetime

from infranode.normalization import (
    Attribution,
    CanonicalRecord,
    LicenseId,
    LicenseTier,
    PopulationDensityPayload,
    SourceId,
)

_DL_DE_BY_URL = "https://www.govdata.de/dl-de/by-2-0"
_CELL_AREA_KM2 = 0.01  # 100m x 100m = 0.01 km2


def map_population_density(
    raw: dict,
    *,
    retrieved_at: datetime,
    ags: str | None = None,
    wikidata_qid: str | None = None,
) -> CanonicalRecord:
    """Bildet das aggregierte Zensus-Gitter-raw-dict auf einen ``CanonicalRecord`` ab.

    ``populated_area_km2`` = bewohnte Zellen * 0.01; ``density_per_km2`` = Einwohner
    / bewohnte Fläche (None, wenn keine bewohnten Zellen). Werte sind statisch
    (Zensus-Stichtag), daher ``observed_at=None``; ``retrieved_at`` wird injiziert.
    """
    cells = raw.get("populated_cells", 0) or 0
    population = raw.get("population")
    area = round(cells * _CELL_AREA_KM2, 4) if cells else None
    density = (
        round(population / area, 1)
        if population is not None and area and area > 0
        else None
    )

    return CanonicalRecord(
        city_slug=raw["slug"],
        geo=None,
        observed_at=None,
        retrieved_at=retrieved_at,
        source=SourceId.ZENSUS_GRID,
        license_id=LicenseId.DL_DE_BY_2_0,
        license_tier=LicenseTier.A,
        ags=ags,
        wikidata_qid=wikidata_qid,
        attribution=Attribution(
            text="© Statistische Ämter des Bundes und der Länder, Zensus 2022",
            license_url=_DL_DE_BY_URL,
        ),
        payload=PopulationDensityPayload(
            population=population,
            populated_cells=cells,
            populated_area_km2=area,
            density_per_km2=density,
        ),
    )
