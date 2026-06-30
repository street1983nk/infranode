"""Keyloser EEA-Badegewaesser-Adapter fetch_bathing_water (Badegewaesserqualitaet).

Laedt die Badegewaesserqualitaet (EU-Badegewaesserrichtlinie 2006/7/EG) aus dem
oeffentlichen ArcGIS-REST-Dienst der Europaeischen Umweltagentur (EEA DiscoMap)
und filtert die Badestellen auf einen Umkreis um eine Stadt. Das Ergebnis ist ein
flaches raw-dict, das der reine ``map_bathing_water``-Mapper erwartet.

Quelle/Lizenz: EEA DiscoMap, CC-BY 4.0 (Tier A); Attribution nennt sowohl die EEA
als auch die EU-Richtlinie 2006/7/EG. Layer 3 ("Bathing water quality (point)")
des Jahres-MapServers traegt je Badestelle ``bathingWaterName``, ``qualityStatus``
(Excellent/Good/Sufficient/Poor), ``bwWaterCategory`` (Lake/Coastal/River),
``longitude``/``latitude`` (WGS84), ``bathingWaterIdentifier`` und
``bwProfileLink``.

KRITISCH (Ehrlichkeit, Pitfall 4): Badegewaesser liegen ORTSNAH (Seen/Kueste im
Umland), NICHT im Stadtzentrum. Der raw-dict weist je Stelle ``distance_km`` aus.
Inland-Staedte ohne Badegewaesser im Umkreis liefern ehrlich ``count=0`` (kein
Crash). Die Bbox-Grenzen sind nummerisch (kein User-Input, T-07-IN); der Host ist
operator-konfigurierbar (``INFRANODE_EEA_BATHING_BASE_URL``).

Der Adapter ist rein gegenueber Pydantic/Resilienz (kein CanonicalRecord, kein
Cache/Breaker). ``raise_for_status`` schlaegt ein 5xx als ``httpx.HTTPError`` an
die Fassade durch (STALE-ON-ERROR).
"""

from __future__ import annotations

import math

import httpx

# Operator-konfigurierbarer EEA-Jahres-MapServer-Layer (Punkt-Layer 3). Der Jahres-
# Teil (_2025) wird jaehrlich nachgezogen, sobald die EEA die neue Saison bewertet.
_BASE = (
    "https://water.discomap.eea.europa.eu/arcgis/rest/services/BathingWater/"
    "BathingWater_Dyna_WM_2025/MapServer/3"
)

# Umkreis um die Stadt: ~0.27 Grad Breite (~30 km) und ~0.40 Grad Laenge
# (cos-korrigiert auf ~51 Grad N ebenfalls ~28 km). Bewusst grob (Badegewaesser
# liegen im Umland), kein Haversine.
_LAT_DELTA = 0.27
_LON_DELTA = 0.40

_OUT_FIELDS = ",".join(
    (
        "bathingWaterName",
        "qualityStatus",
        "bwWaterCategory",
        "longitude",
        "latitude",
        "bathingWaterIdentifier",
        "bwProfileLink",
    )
)

# Obergrenze der zurueckgelieferten Stellen (DoS-/Payload-Schutz); echte Zahl via
# ``count`` + ``truncated``-Flag (Audit-Muster K9, Ehrlichkeit).
_MAX_SITES = 60


def _km(alat: float, alon: float, blat: float, blon: float) -> float:
    """Grobe Distanz in km (breitengrad-korrigierte Grad-Distanz x 111)."""
    cos_lat = math.cos(math.radians(alat))
    dlat = blat - alat
    dlon = (blon - alon) * cos_lat
    return round(math.hypot(dlat, dlon) * 111.0, 1)


async def fetch_bathing_water(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float,
    lon: float,
    season_year: int,
    base_url: str = _BASE,
) -> dict:
    """Holt die Badegewaesserqualitaet im Umkreis einer Stadt (EEA).

    Fragt den EEA-Punkt-Layer mit ``countryCode='DE'`` und einer nummerischen
    Bounding-Box um (``lat``, ``lon``) ab, sortiert die Stellen nach Distanz und
    deckelt auf ``_MAX_SITES``. Gibt das flache raw-dict zurueck, das
    ``map_bathing_water`` erwartet.

    Rueckgabe-Keys: ``slug``, ``season_year``, ``count`` (Gesamtzahl im Umkreis),
    ``truncated`` (ob gedeckelt), ``counts`` (je Qualitaetsklasse), ``sites``
    (je Stelle name/quality/category/lat/lon/distance_km/identifier/profile_url).
    Keine Stelle im Umkreis -> ``count=0`` (ehrliches no_data, kein Crash).
    ``raise_for_status`` schlaegt 5xx als ``httpx.HTTPError`` durch.
    """
    where = (
        f"countryCode='DE' "
        f"AND longitude BETWEEN {lon - _LON_DELTA:.4f} AND {lon + _LON_DELTA:.4f} "
        f"AND latitude BETWEEN {lat - _LAT_DELTA:.4f} AND {lat + _LAT_DELTA:.4f}"
    )
    resp = await http.get(
        f"{base_url}/query",
        params={
            "where": where,
            "outFields": _OUT_FIELDS,
            "returnGeometry": "false",
            "f": "json",
        },
    )
    resp.raise_for_status()
    body = resp.json()
    features = body.get("features") if isinstance(body, dict) else None
    if not isinstance(features, list):
        features = []

    sites: list[dict] = []
    counts: dict[str, int] = {}
    for feat in features:
        attrs = feat.get("attributes") if isinstance(feat, dict) else None
        if not isinstance(attrs, dict):
            continue
        try:
            slat = float(attrs["latitude"])
            slon = float(attrs["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        quality = attrs.get("qualityStatus")
        key = str(quality).lower() if quality else "not_classified"
        counts[key] = counts.get(key, 0) + 1
        sites.append(
            {
                "name": attrs.get("bathingWaterName"),
                "quality": quality,
                "category": attrs.get("bwWaterCategory"),
                "lat": slat,
                "lon": slon,
                "distance_km": _km(lat, lon, slat, slon),
                "identifier": attrs.get("bathingWaterIdentifier"),
                "profile_url": attrs.get("bwProfileLink"),
            }
        )

    sites.sort(key=lambda s: s["distance_km"])
    total = len(sites)
    truncated = total > _MAX_SITES
    return {
        "slug": slug,
        "season_year": season_year,
        "count": total,
        "truncated": truncated,
        "counts": counts,
        "sites": sites[:_MAX_SITES],
    }
