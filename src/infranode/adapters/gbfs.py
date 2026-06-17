"""GBFS-Sharing-Adapter ``fetch_sharing`` (DATA-33, Live, Tier A).

Aggregiert Bike-/Scooter-Sharing je Stadt aus offenen GBFS-Feeds (General
Bikeshare Feed Specification). Primaerquelle Nextbike (CC0, Tier A): je Stadt ein
oder mehrere GBFS-Systeme (kuratierte Allowlist ``GBFS_SYSTEMS`` in cities.py,
NIE User-Input -> kein SSRF).

Fail-closed Tier-A (GOV-02/04): die Lizenz wird PRO System aus dem GBFS-eigenen
``system_information.license_id`` gelesen und gegen die Tier-A-Allowlist
``_TIER_A_LICENSES`` geprueft. Ein System ohne anerkannte permissive Lizenz wird
VERWORFEN (nicht aggregiert), damit kein Datensatz mit unklarer/kommerzieller
Lizenz ins System gelangt.

Pro System werden free-floating-Fahrzeuge (``free_bike_status``/``vehicle_status``)
und stationsgebundene Fahrzeuge (``station_information`` + ``station_status``)
gelesen, per Bounding-Box auf das Stadtgebiet gefiltert (Nextbike-Systeme decken
teils ganze Regionen ab, z.B. VRNnextbike Mannheim/Heidelberg/Ludwigshafen) und
zu Stadt-Kennzahlen verdichtet.

Sicherheit:
- T-05-08 (SSRF): Der Host ist in ``_BASE`` hartkodiert; nur die kuratierten
  ``system_id`` aus der Allowlist fliessen in die URL.
- Resilienz: Der Adapter baut KEINEN ``CanonicalRecord`` und kennt KEIN
  Cache/Breaker (das liefert die Resilienz-Fassade). ``raise_for_status`` ist
  Pflicht (5xx -> STALE-ON-ERROR).
"""

from __future__ import annotations

import httpx

from infranode.adapters.autobahn import _within_bbox

# Host hartkodiert (SSRF, T-05-08): die Nextbike-GBFS-Auslieferung.
_BASE = "https://gbfs.nextbike.net"
# Discovery-Pfad je System (GBFS v2). Die system_id stammt NUR aus der kuratierten
# Allowlist (cities.GBFS_SYSTEMS), nie aus User-Input.
_DISCOVERY = "/maps/gbfs/v2/{system_id}/gbfs.json"

# Obergrenze der je Anbieter ausgelieferten Stationsliste (Payload-/Archiv-Groesse:
# Grossstadt-Systeme wie nextbike Berlin haben >1000 Stationen). ``station_count``
# bleibt der WAHRE Gesamtwert; ``stations`` traegt die nach Verfuegbarkeit
# sortierten Top-Stationen (kein stiller Verlust der Kennzahl, nur der Detailliste).
_MAX_STATIONS = 200

# Fail-closed Tier-A-Allowlist (GOV-02/04): GBFS-``license_id`` (SPDX-/Freitext) ->
# unser kanonischer Lizenz-Tag. Ein System mit hier UNBEKANNTER license_id (oder
# ganz ohne) wird verworfen, statt mit unklarer Lizenz aggregiert zu werden. Nur
# permissive Tier-A-Lizenzen. Schluessel case-insensitiv normalisiert (.upper()).
_TIER_A_LICENSES: dict[str, str] = {
    "CC0-1.0": "cc0",
    "CC0": "cc0",
    "CC-BY-4.0": "cc_by_4_0",
    "CC-BY 4.0": "cc_by_4_0",
    "DL-DE-BY-2.0": "dl_de_by_2_0",
    "DL-DE/BY-2.0": "dl_de_by_2_0",
}


def _tier_a_license(license_id: object) -> str | None:
    """Bildet eine GBFS-``license_id`` fail-closed auf einen Tier-A-Tag ab (rein).

    Unbekannte/fehlende Lizenz -> ``None`` (das System wird verworfen, GOV-02/04).
    """
    if not isinstance(license_id, str):
        return None
    return _TIER_A_LICENSES.get(license_id.strip().upper().replace("_", "-"))


def _feeds(discovery: dict) -> dict[str, str]:
    """Liest aus einem GBFS-``gbfs.json`` die ``{feed_name: url}``-Abbildung (rein).

    Die ``data``-Ebene traegt entweder Sprach-Schluessel (``{"de": {"feeds": []}}``,
    GBFS v2) oder direkt ``{"feeds": []}`` (GBFS v3). ``de`` wird bevorzugt, sonst
    die erste vorhandene Sprache.
    """
    data = discovery.get("data") or {}
    if "feeds" in data:  # GBFS v3: keine Sprach-Ebene mehr.
        langs = {"_": data}
    else:
        langs = data
    block = langs.get("de") or (next(iter(langs.values()), {}) if langs else {})
    return {f.get("name"): f.get("url") for f in block.get("feeds", []) if f.get("url")}


async def _get_json(http: httpx.AsyncClient, url: str) -> dict:
    """Holt eine GBFS-JSON-Ressource (``raise_for_status`` Pflicht -> Fassade)."""
    resp = await http.get(url)
    resp.raise_for_status()
    return resp.json()


def _count_free_floating(
    payload: dict, *, lat: float, lon: float, radius: float
) -> int:
    """Zaehlt verfuegbare free-floating-Fahrzeuge in der BBox (rein).

    GBFS v2 liefert ``data.bikes``, v3 ``data.vehicles``. Nur Fahrzeuge mit
    gueltigen Koordinaten in der BBox, die weder ``is_disabled`` noch
    ``is_reserved`` sind, zaehlen als verfuegbar.
    """
    data = payload.get("data") or {}
    vehicles = data.get("bikes") or data.get("vehicles") or []
    count = 0
    for v in vehicles:
        if not isinstance(v, dict):
            continue
        vlat, vlon = v.get("lat"), v.get("lon")
        if not isinstance(vlat, int | float) or not isinstance(vlon, int | float):
            continue
        if v.get("is_disabled") or v.get("is_reserved"):
            continue
        if _within_bbox(float(vlat), float(vlon), lat, lon, radius):
            count += 1
    return count


def _stations(
    info: dict, status: dict, *, lat: float, lon: float, radius: float
) -> list[dict]:
    """Joint station_information + station_status, BBox-gefiltert (rein).

    Liefert je Station in der BBox ein schlankes dict
    (``station_id``/``name``/``lat``/``lon``/``bikes_available``/``docks_available``).
    Stationen ohne gueltige Koordinaten oder ausserhalb der BBox fallen heraus.
    """
    status_by_id = {
        s.get("station_id"): s
        for s in (status.get("data") or {}).get("stations", [])
        if isinstance(s, dict)
    }
    out: list[dict] = []
    for st in (info.get("data") or {}).get("stations", []):
        if not isinstance(st, dict):
            continue
        slat, slon = st.get("lat"), st.get("lon")
        if not isinstance(slat, int | float) or not isinstance(slon, int | float):
            continue
        if not _within_bbox(float(slat), float(slon), lat, lon, radius):
            continue
        live = status_by_id.get(st.get("station_id"), {})
        out.append(
            {
                "station_id": st.get("station_id"),
                "name": st.get("name"),
                "lat": float(slat),
                "lon": float(slon),
                "bikes_available": live.get("num_bikes_available"),
                "docks_available": live.get("num_docks_available"),
            }
        )
    return out


async def _fetch_system(
    http: httpx.AsyncClient, *, system_id: str, lat: float, lon: float, radius: float
) -> dict | None:
    """Holt EIN GBFS-System und aggregiert es (fail-closed Tier-A, rein gegen Schema).

    Rueckgabe ist ein provider-dict oder ``None``, wenn die Lizenz nicht Tier-A ist
    (fail-closed verworfen). Aggregiert free-floating- + stationsgebundene
    Fahrzeuge in der Stadt-BBox.
    """
    discovery = await _get_json(http, _BASE + _DISCOVERY.format(system_id=system_id))
    feeds = _feeds(discovery)

    info: dict = {}
    if "system_information" in feeds:
        info = await _get_json(http, feeds["system_information"])
    license_tag = _tier_a_license((info.get("data") or {}).get("license_id"))
    if license_tag is None:
        # Fail-closed (GOV-02/04): keine anerkannte permissive Lizenz -> verwerfen.
        return None

    sysdata = info.get("data") or {}
    free_floating = 0
    ff_feed = feeds.get("free_bike_status") or feeds.get("vehicle_status")
    if ff_feed:
        free_floating = _count_free_floating(
            await _get_json(http, ff_feed), lat=lat, lon=lon, radius=radius
        )

    stations: list[dict] = []
    if "station_information" in feeds and "station_status" in feeds:
        stations = _stations(
            await _get_json(http, feeds["station_information"]),
            await _get_json(http, feeds["station_status"]),
            lat=lat,
            lon=lon,
            radius=radius,
        )
    docked = sum(s["bikes_available"] for s in stations if s["bikes_available"])

    # station_count bleibt der wahre Gesamtwert; die ausgelieferte stations-Liste
    # wird nach verfuegbaren Fahrzeugen sortiert und auf _MAX_STATIONS gedeckelt.
    top_stations = sorted(
        stations, key=lambda s: s["bikes_available"] or 0, reverse=True
    )[:_MAX_STATIONS]
    return {
        "provider": sysdata.get("name") or system_id,
        "operator": sysdata.get("operator"),
        "system_id": sysdata.get("system_id") or system_id,
        "license_id": license_tag,
        "free_floating_available": free_floating,
        "docked_available": docked,
        "station_count": len(stations),
        "stations": top_stations,
    }


async def fetch_sharing(
    http: httpx.AsyncClient,
    *,
    slug: str,
    lat: float,
    lon: float,
    systems: tuple[str, ...],
    radius_km: float = 15.0,
) -> dict:
    """Holt + aggregiert die GBFS-Sharing-Daten der kuratierten Systeme einer Stadt.

    Iteriert ueber die kuratierten ``systems`` (NIE User-Input), filtert jedes per
    BBox um (``lat``, ``lon``) und verwirft Systeme ohne Tier-A-Lizenz fail-closed.
    Rueckgabe-Keys (exakt was ``map_sharing`` erwartet): ``slug``, ``radius_km``,
    ``providers`` (Liste der akzeptierten Tier-A-Systeme), sowie die Stadt-Aggregate
    ``vehicles_available``/``free_floating_available``/``docked_available``/
    ``station_count``. Keine akzeptierten Daten -> ``providers == []`` (die Route
    mappt das auf ``no_data``). ``raise_for_status`` ist Pflicht (5xx -> Fassade).
    """
    providers: list[dict] = []
    for system_id in systems:
        provider = await _fetch_system(
            http, system_id=system_id, lat=lat, lon=lon, radius=radius_km
        )
        if provider is not None:
            providers.append(provider)

    free_floating = sum(p["free_floating_available"] for p in providers)
    docked = sum(p["docked_available"] for p in providers)
    return {
        "slug": slug,
        "radius_km": radius_km,
        "providers": providers,
        "free_floating_available": free_floating,
        "docked_available": docked,
        "vehicles_available": free_floating + docked,
        "station_count": sum(p["station_count"] for p in providers),
    }
