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

SCHEMAS: parameters carry ``Annotated[str, Field(description=...)]`` so FastMCP
emits a per-parameter ``description`` in the inputSchema, and every tool is
annotated ``-> ToolEnvelope`` so FastMCP emits an ``outputSchema`` (directory
scanners like Smithery/Glama rate this higher). The runtime return value is
unchanged: a plain ``dict`` envelope passed through 1:1 (``ToolEnvelope`` is a
TypedDict, i.e. a type hint only). ``meta`` allows extra fields so FastMCP's
return-value validation never fails on a real response.

All tools are read-only. They return the canonical envelope with ``data`` and
``meta``; ``meta.source_status`` signals whether the upstream source delivered
data (``ok``/``disabled``/``no_data``/``not_covered``/``error``), so a missing
or failing source degrades gracefully instead of raising. City slugs come from
``list_cities``.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from infranode.mcp import client
from infranode.mcp.schemas import ToolEnvelope

# Most tools take a single ``slug``; the description is shared, the docstring's
# first line gives the per-tool example so the inputSchema stays informative.
_Slug = Annotated[
    str,
    Field(
        description="City slug from the list_cities tool, e.g. 'berlin' or 'hamburg'."
    ),
]


async def get_city(slug: _Slug) -> ToolEnvelope:
    """Get base data for a German city (population, area, coordinates).

    Sourced from Wikidata. Read-only. Useful as a first lookup to confirm a city
    exists and get its core attributes.
    """
    return await client.get_resource(slug, "base")


async def get_city_overview(slug: _Slug) -> ToolEnvelope:
    """Get a ONE-CALL overview of everything InfraNode knows about a German city.

    Start here for any city question. Returns: the city's base data, a CATALOG of
    all ~53 available data types (weather, air quality, public transit, trains,
    traffic, charging, parking, solar, energy, demographics, taxes, accidents,
    tourism, heritage, trees, population density, playgrounds, post boxes and many
    more), each with its coverage status and the exact
    tool to call next, plus a small live highlights snapshot (current weather, air
    quality and train departures). Data types not yet covered for this city show
    where they ARE available so you can pivot. InfraNode keeps adding data and cities,
    so the catalog grows over time. Read-only.
    """
    return await client.get_resource(slug, "overview")


async def air_quality(slug: _Slug) -> ToolEnvelope:
    """Get official air quality for a German city (PM10, NO2 and more).

    Sourced from the Umweltbundesamt (UBA). Read-only. For live station readings
    use ``air_quality_live`` instead.
    """
    return await client.get_resource(slug, "air-uba")


async def air_quality_live(slug: _Slug) -> ToolEnvelope:
    """Get live air quality readings for a German city.

    Sourced from the Umweltbundesamt (UBA), nearest-station hourly readings.
    Read-only. For official, archived values use ``air_quality``.
    """
    return await client.get_resource(slug, "air")


async def weather(slug: _Slug) -> ToolEnvelope:
    """Get current weather observations for a German city.

    Sourced from the Deutscher Wetterdienst (DWD): temperature, wind,
    precipitation and related fields. Read-only, current conditions only (not a
    forecast). For warnings see ``weather_warnings``.
    """
    return await client.get_resource(slug, "weather")


async def pois(
    slug: _Slug,
    type: Annotated[
        str,
        Field(
            description=(
                "POI type from the API allowlist, one of: hospital, school, "
                "pharmacy, restaurant, police, kindergarten."
            )
        ),
    ],
) -> ToolEnvelope:
    """Get points of interest in a German city, filtered by type.

    Sourced from OpenStreetMap. Read-only.
    """
    return await client.get_resource(slug, "pois", params={"type": type})


async def traffic(slug: _Slug) -> ToolEnvelope:
    """Get motorway roadworks and traffic messages for a city's region.

    Sourced from the Autobahn API. Read-only. For inner-city closures use
    ``road_events``.
    """
    return await client.get_resource(slug, "traffic")


async def transit(slug: _Slug) -> ToolEnvelope:
    """Get public-transport stops for a German city (static).

    Sourced from DELFI/GTFS (HVV in Hamburg). Read-only. For minute-fresh
    departures with delays use ``transit_departures``.
    """
    return await client.get_resource(slug, "transit")


async def charging(slug: _Slug) -> ToolEnvelope:
    """Get EV charging-station locations for a German city.

    Sourced from the Bundesnetzagentur. Read-only.
    """
    return await client.get_resource(slug, "charging")


async def water_level(slug: _Slug) -> ToolEnvelope:
    """Get water levels on federal waterways near a German city.

    Sourced from PEGELONLINE. Read-only. Coverage is partial (only cities on a
    federal waterway return data).
    """
    return await client.get_resource(slug, "water-level")


async def flood(slug: _Slug) -> ToolEnvelope:
    """Get flood warning levels for a German city.

    Sourced from the Laenderhochwasserportal. Read-only. Coverage is partial.
    """
    return await client.get_resource(slug, "flood")


async def pollen_uv(slug: _Slug) -> ToolEnvelope:
    """Get pollen forecast and UV index for a city's wider region.

    Sourced from the Deutscher Wetterdienst (DWD). Read-only.
    """
    return await client.get_resource(slug, "pollen-uv")


async def demographics(slug: _Slug) -> ToolEnvelope:
    """Get demographic indicators for a German city.

    Sourced from GENESIS/Regionalstatistik. Read-only.
    """
    return await client.get_resource(slug, "demographics")


async def energy(slug: _Slug) -> ToolEnvelope:
    """Get energy installation metrics for a German city.

    Sourced from the Marktstammdatenregister (power-generation units). Read-only.
    """
    return await client.get_resource(slug, "energy")


async def geo(slug: _Slug) -> ToolEnvelope:
    """Get geodata and administrative boundaries for a German city. Read-only."""
    return await client.get_resource(slug, "geo")


async def election(slug: _Slug) -> ToolEnvelope:
    """Get election results for a German city. Read-only."""
    return await client.get_resource(slug, "election")


async def holidays(slug: _Slug) -> ToolEnvelope:
    """Get public holidays for a German city's federal state.

    Read-only. Holidays are determined by the city's Bundesland.
    """
    return await client.get_resource(slug, "holidays")


async def health(slug: _Slug) -> ToolEnvelope:
    """Get the hospital directory for a German city.

    Sourced from Regionalstatistik. Read-only.
    """
    return await client.get_resource(slug, "health")


async def icu_live(slug: _Slug) -> ToolEnvelope:
    """Get live ICU bed occupancy for a German city.

    Sourced from DIVI (intensive-care register). Read-only, current snapshot.
    """
    return await client.get_resource(slug, "icu-live")


async def road_events(slug: _Slug) -> ToolEnvelope:
    """Get inner-city roadworks and closures for a German city.

    Read-only. Coverage is partial (selected cities). For motorway traffic use
    ``traffic``.
    """
    return await client.get_resource(slug, "road-events")


async def events(slug: _Slug) -> ToolEnvelope:
    """Get public events and happenings for a German city.

    Read-only. Coverage is partial.
    """
    return await client.get_resource(slug, "events")


async def webcams(slug: _Slug) -> ToolEnvelope:
    """Get traffic webcams for a city's region.

    Sourced from the Autobahn API. Read-only. Coverage is partial.
    """
    return await client.get_resource(slug, "webcams")


async def power_load(slug: _Slug) -> ToolEnvelope:
    """Get the daily grid load (electricity consumption) for a city's control zone.

    Sourced from SMARD. Read-only, daily value.
    """
    return await client.get_resource(slug, "power-load")


async def power_price(slug: _Slug) -> ToolEnvelope:
    """Get the day-ahead wholesale electricity price (nationwide), daily.

    Sourced from SMARD. Read-only. The price is nationwide; the slug only
    anchors the request to a covered city.
    """
    return await client.get_resource(slug, "power-price")


async def weather_warnings(slug: _Slug) -> ToolEnvelope:
    """Get official weather warnings for a German city (highest active level).

    Sourced from the Deutscher Wetterdienst (DWD). Read-only.
    """
    return await client.get_resource(slug, "weather-warnings")


async def vehicle_registrations(slug: _Slug) -> ToolEnvelope:
    """Get registered car stock and electric share for a city's registration district.

    Sourced from the Kraftfahrt-Bundesamt (KBA). Read-only.
    """
    return await client.get_resource(slug, "vehicle-registrations")


async def unemployment(slug: _Slug) -> ToolEnvelope:
    """Get the number of unemployed and the unemployment rate for a city's district.

    Sourced from Regionalstatistik. Read-only.
    """
    return await client.get_resource(slug, "unemployment")


async def tourism(slug: _Slug) -> ToolEnvelope:
    """Get guest overnight stays and arrivals for a city's district.

    Sourced from Regionalstatistik. Read-only.
    """
    return await client.get_resource(slug, "tourism")


async def construction(slug: _Slug) -> ToolEnvelope:
    """Get building permits (residential buildings/dwellings) for a city's district.

    Sourced from Regionalstatistik. Read-only.
    """
    return await client.get_resource(slug, "construction")


async def accidents(slug: _Slug) -> ToolEnvelope:
    """Get road-traffic accidents for a German city (yearly aggregate).

    Sourced from the Unfallatlas. Read-only.
    """
    return await client.get_resource(slug, "accidents")


async def crime_stats(slug: _Slug) -> ToolEnvelope:
    """Get police crime statistics for a German city (per main offence group).

    Sourced from the BKA Polizeiliche Kriminalstatistik (PKS): cases, frequency
    per 100k inhabitants and clearance rate per main offence group. Read-only.
    """
    return await client.get_resource(slug, "crime-stats")


async def fuel_prices(slug: _Slug) -> ToolEnvelope:
    """Get current fuel prices for a German city, aggregated per fuel type.

    Sourced from Tankerkoenig. Returns average and minimum per fuel type
    (E5/E10/diesel). Read-only, near-real-time.
    """
    return await client.get_resource(slug, "fuel-prices")


async def sharing(slug: _Slug) -> ToolEnvelope:
    """Get bike/scooter sharing availability for a German city, aggregated.

    Sourced from GBFS feeds (primarily Nextbike). Returns vehicle and station
    counts. Read-only, live. Coverage is partial.
    """
    return await client.get_resource(slug, "sharing")


async def solar(slug: _Slug) -> ToolEnvelope:
    """Get solar irradiation and normalized PV yield potential for a German city.

    Sourced from PVGIS (European Commission JRC). Returns a multi-year
    climatological average for the city centre, normalized to a 1 kWp system at the
    optimal tilt: annual PV yield (kWh/kWp), annual global irradiation (kWh/m2), the
    optimal tilt/azimuth and 12 monthly values. All 84 cities are covered.
    Read-only.
    """
    return await client.get_resource(slug, "solar")


async def solar_roofs(slug: _Slug) -> ToolEnvelope:
    """Get rooftop solar cadastre potential and installed PV for a German city.

    Sourced from the official state solar cadastre aggregates (NRW, Bavaria,
    Berlin and Hamburg). Returns the total installable rooftop PV potential (kWp
    and annual yield in MWh), the already installed rooftop PV, the exploitation
    ratio and a per-building-category breakdown (scope varies by source).
    Distinct from ``solar`` (PVGIS irradiation/yield per kWp). Coverage is partial
    (federated per state). Read-only.
    """
    return await client.get_resource(slug, "solar-roofs")


async def indicators(slug: _Slug) -> ToolEnvelope:
    """Get socioeconomic indicators for a German city (district level, latest year).

    Sourced from INKAR/BBSR (~70 curated indicators across labour market,
    economy, income, demography, housing, mobility, health and more). Read-only.
    """
    return await client.get_resource(slug, "indicators")


async def land_values(slug: _Slug) -> ToolEnvelope:
    """Get aggregated official land values (Bodenrichtwerte) for a German city.

    Sourced from BORIS (the surveyor committees' land-value information system),
    federated per federal state. Returns a building-land summary
    (residential/mixed/commercial, excluding forest/water/farmland): median, min
    and max land value in EUR/m2, the number of zones, the valuation reference
    date and the bounding-box radius the aggregate was computed over. Read-only.
    Coverage is partial (per state); ``source_status`` is ``not_covered`` for
    states without a BORIS WFS yet.
    """
    return await client.get_resource(slug, "land-values")


async def tax_rates(slug: _Slug) -> ToolEnvelope:
    """Get the local real-property tax multipliers (Hebesätze) for a German city.

    Sourced from Regionalstatistik (German statistical offices, table 71231),
    municipality-level: trade-tax multiplier (gewerbesteuer_hebesatz) and property
    tax A/B/C (grundsteuer_a/b/c), all in percent, plus the reference date
    (stichtag). An unset rate is null. Location/real-estate relevant. Read-only.
    """
    return await client.get_resource(slug, "tax-rates")


async def business_registrations(slug: _Slug) -> ToolEnvelope:
    """Get business registrations/deregistrations for a German city (district level).

    Sourced from Regionalstatistik (German business notification statistics, table
    52311, annual total), district-level: anmeldungen (registrations), abmeldungen
    (deregistrations), saldo (net = registrations - deregistrations; positive = a
    founding surplus) and the reporting year (jahr). A measure of founding
    dynamics. Read-only.
    """
    return await client.get_resource(slug, "business-registrations")


async def insolvencies(slug: _Slug) -> ToolEnvelope:
    """Get insolvency filings for a German city (district level, annual).

    Sourced from Regionalstatistik (German insolvency statistics, tables 52411-02
    ISV006 + 52411-03 ISV007, annual total), district-level: unternehmensinsolvenzen
    (corporate insolvencies) and uebrige_schuldner_insolvenzen (other debtors,
    including consumers and former self-employed) plus the reporting year (jahr). A
    measure of regional economic distress. Read-only.
    """
    return await client.get_resource(slug, "insolvencies")


async def station_departures(slug: _Slug) -> ToolEnvelope:
    """Get live train departures from a city's main station, all train categories.

    Sourced from Deutsche Bahn Timetables, including delays and cancellations. All
    84 cities are covered: the main station is auto-selected from the official
    StaDa catalog. For a specific station use ``station_board_departures`` with its
    EVA from ``stations``. Read-only.
    """
    return await client.get_resource(slug, "station-departures")


async def station_arrivals(slug: _Slug) -> ToolEnvelope:
    """Get live train arrivals at a city's main station, all train categories.

    Sourced from Deutsche Bahn Timetables, including delays and cancellations. All
    84 cities are covered: the main station is auto-selected from the official
    StaDa catalog. For a specific station use ``station_board_arrivals`` with its
    EVA from ``stations``. Read-only.
    """
    return await client.get_resource(slug, "station-arrivals")


async def stations(slug: _Slug) -> ToolEnvelope:
    """List all railway stations in a city (every station, not just the main hub).

    Returns each Deutsche Bahn station in the city with its EVA number, name,
    category, coordinates and ZIP. Use an EVA from here with
    ``station_board_departures``/``station_board_arrivals`` for a live board of any
    station, including local/regional trains. Sourced from DB StaDa. Read-only.
    """
    return await client.get_resource(slug, "stations")


async def station_board_departures(
    eva: Annotated[
        str,
        Field(
            description=(
                "Station EVA number (digits only) from the stations tool, "
                "e.g. '8011160' (Berlin Hbf)."
            )
        ),
    ],
) -> ToolEnvelope:
    """Get live departures for ANY railway station by its EVA number.

    Covers all train categories including local/regional (S/RB/RE) and long
    distance, with real-time delays, cancellations and disruption messages. Get
    the EVA from ``stations``. Read-only.
    """
    return await client.get_station_board(eva, "departures")


async def station_board_arrivals(
    eva: Annotated[
        str,
        Field(
            description=(
                "Station EVA number (digits only) from the stations tool, "
                "e.g. '8000105' (Frankfurt Hbf)."
            )
        ),
    ],
) -> ToolEnvelope:
    """Get live arrivals for ANY railway station by its EVA number.

    Mirror of ``station_board_departures`` for arriving trains (all categories,
    real-time delays, disruption messages). Get the EVA from ``stations``.
    Read-only.
    """
    return await client.get_station_board(eva, "arrivals")


async def transit_departures(
    slug: _Slug,
    stop_id: Annotated[
        str | None,
        Field(
            description=(
                "Optional stop ID; omit it to get the city's available departures."
            )
        ),
    ] = None,
) -> ToolEnvelope:
    """Get live public-transport departures with real-time delays.

    Sourced from GTFS-RT/HVV/VGN. Unlike ``transit`` (static stops), this returns
    minute-fresh departures including delay. Read-only.
    """
    params = {"stop_id": stop_id} if stop_id else None
    return await client.get_live(slug, "transit/departures", params=params)


async def parking(slug: _Slug) -> ToolEnvelope:
    """Get live parking occupancy (vacant spaces, occupancy %) for a city.

    Per car park: vacant spaces, occupancy percentage and graded occupancy,
    enriched with name, geo coordinate and capacity. Sourced from the Mobilithek
    (DATEX II V3). Currently available for ``frankfurt-am-main``; other slugs
    return source_status="disabled". Read-only, live (minute-fresh).
    """
    return await client.get_live(slug, "parking")


async def list_cities() -> ToolEnvelope:
    """List all covered cities (slug, federal state, population, coverage).

    Takes no arguments. Call this first to discover valid city slugs before
    invoking any city-scoped tool. Read-only.
    """
    return await client.get_collection("cities")


async def sources() -> ToolEnvelope:
    """List all data sources with license, attribution and availability.

    Takes no arguments. Shows which upstream sources InfraNode bundles and
    whether each is currently active. Read-only.
    """
    return await client.get_collection("sources")


async def compare(
    resource: Annotated[
        str,
        Field(
            description=(
                "Resource to compare. Currently supported: 'weather' (DWD) or "
                "'air' (UBA air quality)."
            )
        ),
    ],
    cities: Annotated[
        str,
        Field(
            description=(
                "Comma-separated list of city slugs, e.g. 'berlin,koeln,hamburg' "
                "(max. 28 cities)."
            )
        ),
    ],
) -> ToolEnvelope:
    """Compare ONE resource across MULTIPLE cities in a single response.

    Fans the resource out over the listed cities and returns a per-city
    ``source_status`` (ok/disabled/no_data/error/not_found), so a missing or
    failing city source does not spoil the whole answer. Read-only.
    """
    return await client.get_collection(
        "compare", params={"resource": resource, "cities": cities}
    )


# DATA-OSM (Tier 1): dedizierte OSM-Overpass-Datenarten (ODbL, Tier B copyleft).
# Duenne Wrapper wie oben; Tag-Whitelist + Overpass-QL liegen in der Live-API.
async def playgrounds(slug: _Slug) -> ToolEnvelope:
    """List public playgrounds in a city (OpenStreetMap). Read-only."""
    return await client.get_resource(slug, "playgrounds")


async def drinking_water(slug: _Slug) -> ToolEnvelope:
    """List public drinking-water fountains in a city (OpenStreetMap). Read-only.

    OSM coverage varies by city; a sparse result is a data gap, not an error.
    """
    return await client.get_resource(slug, "drinking-water")


async def markets(slug: _Slug) -> ToolEnvelope:
    """List marketplaces in a city (OpenStreetMap). Read-only.

    Market days/times come as optional opening_hours per item (often empty).
    """
    return await client.get_resource(slug, "markets")


async def parcel_lockers(slug: _Slug) -> ToolEnvelope:
    """List parcel lockers in a city (OpenStreetMap). Read-only.

    operator/brand (DHL/Amazon/DPD/Hermes/GLS) per item where tagged.
    """
    return await client.get_resource(slug, "parcel-lockers")


async def post_offices(slug: _Slug) -> ToolEnvelope:
    """List post offices in a city (OpenStreetMap). Read-only."""
    return await client.get_resource(slug, "post-offices")


async def post_boxes(slug: _Slug) -> ToolEnvelope:
    """List public post boxes in a city (OpenStreetMap). Read-only.

    collection_times per item where tagged (~75%); missing = data gap.
    """
    return await client.get_resource(slug, "post-boxes")


async def public_wifi(slug: _Slug) -> ToolEnvelope:
    """List public Wi-Fi locations in a city (OpenStreetMap). Read-only."""
    return await client.get_resource(slug, "public-wifi")


async def recycling_centres(slug: _Slug) -> ToolEnvelope:
    """List recycling centres (Wertstoffhoefe) in a city (OpenStreetMap). Read-only."""
    return await client.get_resource(slug, "recycling-centres")


async def government_offices(slug: _Slug) -> ToolEnvelope:
    """List government offices in a city (OpenStreetMap). Read-only.

    Consolidates citizen, administrative and other offices; subtype per item as
    an optional government tag.
    """
    return await client.get_resource(slug, "government-offices")


async def education(slug: _Slug) -> ToolEnvelope:
    """List education facilities in a city (schools, universities, kindergartens).

    Sourced from OpenStreetMap. Read-only.
    """
    return await client.get_resource(slug, "education")


async def heritage(slug: _Slug) -> ToolEnvelope:
    """List heritage/listed monuments in a city (state heritage registers).

    Sourced from federal-state heritage WFS (e.g. Berlin, DL-DE/Zero). Coverage is
    partial (heritage protection is a state matter); ``source_status`` is
    ``not_covered`` for cities in states without a verified open WFS. Read-only.
    """
    return await client.get_resource(slug, "heritage")


async def tree_cadastre(slug: _Slug) -> ToolEnvelope:
    """List a city's street-tree cadastre (species, planting year, height).

    Sourced from the municipal tree register WFS (e.g. Berlin, DL-DE/Zero). The
    response is a capped sample (registers are very large; ``count`` is the number
    of returned trees, not the full stock). Coverage is partial; ``source_status``
    is ``not_covered`` for cities without a verified open WFS. Read-only.
    """
    return await client.get_resource(slug, "tree-cadastre")


async def population_density(slug: _Slug) -> ToolEnvelope:
    """Get a city's population density from the Census 2022 100m grid.

    Aggregated exactly over the grid cells with the city's AGS (sum of inhabitants,
    populated 100m cells, populated area, inhabitants per km2 over the populated
    area). Sourced from the official Zensus 2022 grid (DL-DE/BY). Read-only.
    """
    return await client.get_resource(slug, "population-density")


async def public_tenders(slug: _Slug) -> ToolEnvelope:
    """Get public procurement notices for a German city.

    Running tenders and awarded contracts, sourced from the German federal
    procurement publication service (oeffentlichevergabe.de, OCDS, CC0).
    Read-only.
    """
    return await client.get_resource(slug, "public-tenders")


async def bike_counts(slug: _Slug) -> ToolEnvelope:
    """Get municipal bike-counter (continuous cycling-count) stations for a city.

    Permanent cycling-count stations operated by the city, sourced from municipal
    cycling open data per city (DL-DE/CC-BY, varying by source). Read-only.
    Coverage is partial (selected cities only). This is NOT bike sharing: for
    rental bikes/scooters use the ``sharing`` tool instead.
    """
    return await client.get_resource(slug, "bike-counts")
