"""Keyloser Zensus-2022-Gitter-Adapter fetch_population_density (DATA-OSM-Tier-2).

Der Zensus 2022 ist als 100m-Gitter ueber einen oeffentlichen ArcGIS-FeatureServer
abfragbar (DL-DE/BY 2.0). JEDE Gitterzelle traegt die Gemeinde-AGS, daher laesst
sich die Einwohnerdichte EXAKT je Stadt aggregieren, mit EINER Server-seitigen
Statistik-Query (SUM(Einwohner) + COUNT der bewohnten Zellen ueber ``ags=<AGS>``),
ohne den grossen Gitter-Datensatz herunterzuladen.

Sicherheit (T-SSRF/Injection): Host ist hartkodiert (``_BASE``); die ``ags`` stammt
aus dem validierten Register und wird zusaetzlich auf reine Ziffern geprueft, bevor
sie in die ``where``-Klausel gelangt. Rein (kein Cache/Breaker, das liefert die
Fassade); ``resp.raise_for_status()`` ist Pflicht (STALE-ON-ERROR).
"""

from __future__ import annotations

import httpx

# ArcGIS-FeatureServer des Zensus-2022-100m-Gitters (Layer 0), hartkodiert (SSRF).
_BASE = (
    "https://services2.arcgis.com/jUpNdisbWqRpMo35/arcgis/rest/services/"
    "Zensus2022_grid_final/FeatureServer/0/query"
)

# Server-seitige Aggregation: Summe Einwohner + Zahl der (bewohnten) Zellen.
_OUT_STATISTICS = (
    '[{"statisticType":"sum","onStatisticField":"Einwohner",'
    '"outStatisticFieldName":"pop"},'
    '{"statisticType":"count","onStatisticField":"OBJECTID",'
    '"outStatisticFieldName":"n"}]'
)


async def fetch_population_density(
    http: httpx.AsyncClient,
    *,
    slug: str,
    ags: str,
) -> dict:
    """Aggregiert die Zensus-2022-Gitterzellen einer Stadt (AGS) server-seitig.

    Liefert das raw-dict mit ``slug``, ``population`` (Summe Einwohner, None wenn
    der Server nichts liefert) und ``populated_cells`` (Zahl der Zellen). Eine
    nicht-ziffrige AGS loest ein ``ValueError`` aus (Injection-Schutz), bevor eine
    Query laeuft. ``map_population_density`` errechnet daraus Flaeche + Dichte.
    """
    if not ags or not ags.isdigit():
        raise ValueError(f"Ungueltige AGS (nur Ziffern erlaubt): {ags!r}")

    params = {
        "where": f"ags='{ags}'",
        "outStatistics": _OUT_STATISTICS,
        "f": "json",
    }
    resp = await http.get(_BASE, params=params)
    resp.raise_for_status()
    body = resp.json()

    features = body.get("features") if isinstance(body, dict) else None
    attrs = (
        features[0].get("attributes", {})
        if isinstance(features, list) and features
        else {}
    )
    pop = attrs.get("pop")
    cells = attrs.get("n") or 0
    return {
        "slug": slug,
        "population": int(pop) if isinstance(pop, (int, float)) else None,
        "populated_cells": int(cells) if isinstance(cells, (int, float)) else 0,
    }
