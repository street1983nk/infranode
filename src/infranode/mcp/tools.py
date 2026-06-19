"""Free-standing async tool functions of the InfraNode MCP server (DX-05).

CALL CONTRACT (Blocker 4): each tool's logic lives here as a free-standing
async module function that ``server.py`` registers thinly via ``@mcp.tool()``.
That keeps the function directly callable as a coroutine, independent of whether
the decorator replaces the callable with a FunctionTool object.

Every function is a thin wrapper: it calls ``client.get_resource`` with the
fixed resource name and returns the normalized JSON 1:1. There is NO mapping or
licensing logic here (that lives solely in the live API). The SSRF/injection
gates (T-12-MCP-SSRF, T-12-MCP-INJECT) sit in ``client.get_resource`` and run
before every request.

All tools are read-only. They return the canonical envelope with ``data`` and
``meta``; ``meta.source_status`` signals whether the upstream source delivered
data (``ok``/``disabled``/``no_data``/``not_covered``/``error``), so a missing
or failing source degrades gracefully instead of raising. City slugs come from
``list_cities``.
"""

from __future__ import annotations

from infranode.mcp import client


async def get_city(slug: str) -> dict:
    """Get base data for a German city (population, area, coordinates).

    Sourced from Wikidata. Read-only. Useful as a first lookup to confirm a city
    exists and get its core attributes.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"berlin"`` or ``"hamburg"``.
    """
    return await client.get_resource(slug, "base")


async def air_quality(slug: str) -> dict:
    """Get official air quality for a German city (PM10, NO2 and more).

    Sourced from the Umweltbundesamt (UBA). Read-only. For live station readings
    use ``air_quality_live`` instead.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"koeln"``.
    """
    return await client.get_resource(slug, "air-uba")


async def air_quality_live(slug: str) -> dict:
    """Get live air quality readings for a German city.

    Sourced from OpenAQ (live-only, no history). Read-only. For official,
    archived values use ``air_quality``.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"muenchen"``.
    """
    return await client.get_resource(slug, "air")


async def weather(slug: str) -> dict:
    """Get current weather observations for a German city.

    Sourced from the Deutscher Wetterdienst (DWD): temperature, wind,
    precipitation and related fields. Read-only, current conditions only (not a
    forecast). For warnings see ``weather_warnings``.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"koeln"``.
    """
    return await client.get_resource(slug, "weather")


async def pois(slug: str, type: str) -> dict:
    """Get points of interest in a German city, filtered by type.

    Sourced from OpenStreetMap. Read-only.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"koeln"``.
        type: POI type from the API allowlist, one of ``"hospital"``,
            ``"school"``, ``"pharmacy"``, ``"restaurant"``, ``"police"`` or
            ``"kindergarten"``.
    """
    return await client.get_resource(slug, "pois", params={"type": type})


async def traffic(slug: str) -> dict:
    """Get motorway roadworks and traffic messages for a city's region.

    Sourced from the Autobahn API. Read-only. For inner-city closures use
    ``road_events``.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"hamburg"``.
    """
    return await client.get_resource(slug, "traffic")


async def transit(slug: str) -> dict:
    """Get public-transport stops for a German city (static).

    Sourced from DELFI/GTFS (HVV in Hamburg). Read-only. For minute-fresh
    departures with delays use ``transit_departures``.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"berlin"``.
    """
    return await client.get_resource(slug, "transit")


async def charging(slug: str) -> dict:
    """Get EV charging-station locations for a German city.

    Sourced from the Bundesnetzagentur. Read-only.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"stuttgart"``.
    """
    return await client.get_resource(slug, "charging")


async def water_level(slug: str) -> dict:
    """Get water levels on federal waterways near a German city.

    Sourced from PEGELONLINE. Read-only. Coverage is partial (only cities on a
    federal waterway return data).

    Args:
        slug: City slug from ``list_cities``, e.g. ``"koeln"``.
    """
    return await client.get_resource(slug, "water-level")


async def flood(slug: str) -> dict:
    """Get flood warning levels for a German city.

    Sourced from the Laenderhochwasserportal. Read-only. Coverage is partial.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"dresden"``.
    """
    return await client.get_resource(slug, "flood")


async def pollen_uv(slug: str) -> dict:
    """Get pollen forecast and UV index for a city's wider region.

    Sourced from the Deutscher Wetterdienst (DWD). Read-only.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"berlin"``.
    """
    return await client.get_resource(slug, "pollen-uv")


async def demographics(slug: str) -> dict:
    """Get demographic indicators for a German city.

    Sourced from GENESIS/Regionalstatistik. Read-only.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"leipzig"``.
    """
    return await client.get_resource(slug, "demographics")


async def energy(slug: str) -> dict:
    """Get energy installation metrics for a German city.

    Sourced from the Marktstammdatenregister (power-generation units). Read-only.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"hamburg"``.
    """
    return await client.get_resource(slug, "energy")


async def geo(slug: str) -> dict:
    """Get geodata and administrative boundaries for a German city.

    Read-only.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"koeln"``.
    """
    return await client.get_resource(slug, "geo")


async def election(slug: str) -> dict:
    """Get election results for a German city.

    Read-only.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"berlin"``.
    """
    return await client.get_resource(slug, "election")


async def holidays(slug: str) -> dict:
    """Get public holidays for a German city's federal state.

    Read-only. Holidays are determined by the city's Bundesland.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"muenchen"``.
    """
    return await client.get_resource(slug, "holidays")


async def health(slug: str) -> dict:
    """Get the hospital directory for a German city.

    Sourced from Regionalstatistik. Read-only.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"essen"``.
    """
    return await client.get_resource(slug, "health")


async def icu_live(slug: str) -> dict:
    """Get live ICU bed occupancy for a German city.

    Sourced from DIVI (intensive-care register). Read-only, current snapshot.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"koeln"``.
    """
    return await client.get_resource(slug, "icu-live")


async def road_events(slug: str) -> dict:
    """Get inner-city roadworks and closures for a German city.

    Read-only. Coverage is partial (selected cities). For motorway traffic use
    ``traffic``.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"koeln"``.
    """
    return await client.get_resource(slug, "road-events")


async def events(slug: str) -> dict:
    """Get public events and happenings for a German city.

    Read-only. Coverage is partial.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"koeln"``.
    """
    return await client.get_resource(slug, "events")


async def webcams(slug: str) -> dict:
    """Get traffic webcams for a city's region.

    Sourced from the Autobahn API. Read-only. Coverage is partial.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"hamburg"``.
    """
    return await client.get_resource(slug, "webcams")


async def power_load(slug: str) -> dict:
    """Get the daily grid load (electricity consumption) for a city's control zone.

    Sourced from SMARD. Read-only, daily value.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"berlin"``.
    """
    return await client.get_resource(slug, "power-load")


async def power_price(slug: str) -> dict:
    """Get the day-ahead wholesale electricity price (nationwide), daily.

    Sourced from SMARD. Read-only. The price is nationwide; the slug only
    anchors the request to a covered city.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"berlin"``.
    """
    return await client.get_resource(slug, "power-price")


async def weather_warnings(slug: str) -> dict:
    """Get official weather warnings for a German city (highest active level).

    Sourced from the Deutscher Wetterdienst (DWD). Read-only.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"muenchen"``.
    """
    return await client.get_resource(slug, "weather-warnings")


async def vehicle_registrations(slug: str) -> dict:
    """Get registered car stock and electric share for a city's registration district.

    Sourced from the Kraftfahrt-Bundesamt (KBA). Read-only.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"stuttgart"``.
    """
    return await client.get_resource(slug, "vehicle-registrations")


async def unemployment(slug: str) -> dict:
    """Get the number of unemployed and the unemployment rate for a city's district.

    Sourced from Regionalstatistik. Read-only.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"dortmund"``.
    """
    return await client.get_resource(slug, "unemployment")


async def tourism(slug: str) -> dict:
    """Get guest overnight stays and arrivals for a city's district.

    Sourced from Regionalstatistik. Read-only.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"muenchen"``.
    """
    return await client.get_resource(slug, "tourism")


async def construction(slug: str) -> dict:
    """Get building permits (residential buildings/dwellings) for a city's district.

    Sourced from Regionalstatistik. Read-only.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"hamburg"``.
    """
    return await client.get_resource(slug, "construction")


async def accidents(slug: str) -> dict:
    """Get road-traffic accidents for a German city (yearly aggregate).

    Sourced from the Unfallatlas. Read-only.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"koeln"``.
    """
    return await client.get_resource(slug, "accidents")


async def fuel_prices(slug: str) -> dict:
    """Get current fuel prices for a German city, aggregated per fuel type.

    Sourced from Tankerkoenig. Returns average and minimum per fuel type
    (E5/E10/diesel). Read-only, near-real-time.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"koeln"``.
    """
    return await client.get_resource(slug, "fuel-prices")


async def sharing(slug: str) -> dict:
    """Get bike/scooter sharing availability for a German city, aggregated.

    Sourced from GBFS feeds (primarily Nextbike). Returns vehicle and station
    counts. Read-only, live. Coverage is partial.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"berlin"``.
    """
    return await client.get_resource(slug, "sharing")


async def indicators(slug: str) -> dict:
    """Get socioeconomic indicators for a German city (district level, latest year).

    Sourced from INKAR/BBSR (~70 curated indicators across labour market,
    economy, income, demography, housing, mobility, health and more). Read-only.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"koeln"``.
    """
    return await client.get_resource(slug, "indicators")


async def land_values(slug: str) -> dict:
    """Get aggregated official land values (Bodenrichtwerte) for a German city.

    Sourced from BORIS (the surveyor committees' land-value information system),
    federated per federal state. Returns a building-land summary
    (residential/mixed/commercial, excluding forest/water/farmland): median, min
    and max land value in EUR/m2, the number of zones, the valuation reference
    date and the bounding-box radius the aggregate was computed over. Read-only.
    Coverage is partial (per state); ``source_status`` is ``not_covered`` for
    states without a BORIS WFS yet.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"berlin"``.
    """
    return await client.get_resource(slug, "land-values")


async def station_departures(slug: str) -> dict:
    """Get live long-distance train departures from a city's major stations.

    Sourced from Deutsche Bahn Timetables, including delays and cancellations.
    Read-only. Covered for metropolitan hubs only (otherwise ``not_covered``).

    Args:
        slug: City slug from ``list_cities``, e.g. ``"berlin"``.
    """
    return await client.get_resource(slug, "station-departures")


async def station_arrivals(slug: str) -> dict:
    """Get live long-distance train arrivals at a city's major stations.

    Sourced from Deutsche Bahn Timetables, including delays and cancellations.
    Read-only. Covered for metropolitan hubs only (otherwise ``not_covered``).

    Args:
        slug: City slug from ``list_cities``, e.g. ``"frankfurt"``.
    """
    return await client.get_resource(slug, "station-arrivals")


async def stations(slug: str) -> dict:
    """List all railway stations in a city (every station, not just the main hub).

    Returns each Deutsche Bahn station in the city with its EVA number, name,
    category, coordinates and ZIP. Use an EVA from here with
    ``station_board_departures``/``station_board_arrivals`` for a live board of any
    station, including local/regional trains. Sourced from DB StaDa. Read-only.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"berlin"``.
    """
    return await client.get_resource(slug, "stations")


async def station_board_departures(eva: str) -> dict:
    """Get live departures for ANY railway station by its EVA number.

    Covers all train categories including local/regional (S/RB/RE) and long
    distance, with real-time delays, cancellations and disruption messages. Get
    the EVA from ``stations``. Read-only.

    Args:
        eva: Station EVA number (digits only), e.g. ``"8011160"`` (Berlin Hbf).
    """
    return await client.get_station_board(eva, "departures")


async def station_board_arrivals(eva: str) -> dict:
    """Get live arrivals for ANY railway station by its EVA number.

    Mirror of ``station_board_departures`` for arriving trains (all categories,
    real-time delays, disruption messages). Get the EVA from ``stations``.
    Read-only.

    Args:
        eva: Station EVA number (digits only), e.g. ``"8000105"`` (Frankfurt Hbf).
    """
    return await client.get_station_board(eva, "arrivals")


async def transit_departures(slug: str, stop_id: str | None = None) -> dict:
    """Get live public-transport departures with real-time delays.

    Sourced from GTFS-RT/HVV/VGN. Unlike ``transit`` (static stops), this returns
    minute-fresh departures including delay. Read-only.

    Args:
        slug: City slug from ``list_cities``, e.g. ``"berlin"`` or ``"hamburg"``.
        stop_id: Optional stop ID; omit it to get the city's available
            departures.
    """
    params = {"stop_id": stop_id} if stop_id else None
    return await client.get_live(slug, "transit/departures", params=params)


async def list_cities() -> dict:
    """List all covered cities (slug, federal state, population, coverage).

    Takes no arguments. Call this first to discover valid city slugs before
    invoking any city-scoped tool. Read-only.
    """
    return await client.get_collection("cities")


async def sources() -> dict:
    """List all data sources with license, attribution and availability.

    Takes no arguments. Shows which upstream sources InfraNode bundles and
    whether each is currently active. Read-only.
    """
    return await client.get_collection("sources")


async def compare(resource: str, cities: str) -> dict:
    """Compare ONE resource across MULTIPLE cities in a single response.

    Fans the resource out over the listed cities and returns a per-city
    ``source_status`` (ok/disabled/no_data/error/not_found), so a missing or
    failing city source does not spoil the whole answer. Read-only.

    Args:
        resource: Resource to compare. Currently supported: ``"weather"`` (DWD)
            or ``"air"`` (UBA air quality).
        cities: Comma-separated list of city slugs, e.g.
            ``"berlin,koeln,hamburg"`` (max. 28 cities).
    """
    return await client.get_collection(
        "compare", params={"resource": resource, "cities": cities}
    )
