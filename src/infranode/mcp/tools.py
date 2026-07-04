"""Free-standing async tool functions of the InfraNode MCP server (DX-05).

CALL CONTRACT (Blocker 4): each tool's logic lives here as a free-standing
async module function that ``server.py`` registers thinly via ``@mcp.tool()``.
That keeps the function directly callable as a coroutine, independent of whether
the decorator replaces the callable with a FunctionTool object.

Every function is a thin wrapper: it calls ``client.get_resource`` with the
resource name and returns the normalized JSON 1:1. There is NO mapping or
licensing logic here (that lives solely in the live API). The SSRF/injection
gates (T-12-MCP-SSRF, T-12-MCP-INJECT) sit in ``client.get_resource`` and run
before every request.

TOOL SURFACE (Konsolidierung 2026-07-02): frueher trug jede Datenart ein
eigenes Tool (71 Stueck, ~30k Tokens Tool-Liste, Cursor-80-Tool-Limit in
Sichtweite). Jetzt gibt es wenige NAMENTLICHE Tools (Einstieg, Meta,
parametrisierte Faehigkeiten, die zwei populaersten Datenarten) plus EIN
generisches ``get_city_resource(slug, resource)`` fuer den gesamten Long-Tail.
Die Discovery uebernimmt ``get_city_overview``/``infranode://catalog``: beide
nennen je Datenart den ``resource``-Schluessel, und das ``resource``-Enum im
inputSchema listet alle gueltigen Werte maschinenlesbar.

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

from typing import Annotated, Literal

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

# Alle per get_city_resource abrufbaren Datenarten = die City-Allowlist OHNE
# ``pois`` (braucht den Pflichtparameter ``type`` und hat deshalb ein eigenes
# Tool). ``base``/``overview``/``weather``/``air-uba`` haben zwar ebenfalls
# namentliche Tools, bleiben hier aber absichtlich drin: so gilt fuer JEDEN
# Katalog-Schluessel ohne Ausnahme "get_city_resource(slug, <type>) liefert
# ihn", und das Enum spiegelt den Katalog 1:1. Als Literal annotiert, damit
# FastMCP ein ``enum`` im inputSchema emittiert (maschinenlesbare Discovery)
# und Pydantic ungueltige Werte schon vor dem Request abweist.
GENERIC_RESOURCES: tuple[str, ...] = tuple(sorted(client.ALLOWED_RESOURCES - {"pois"}))
_ResourceKey = Annotated[
    Literal[GENERIC_RESOURCES],
    Field(
        description=(
            "Data type key to fetch, exactly as listed by get_city_overview / the "
            "infranode://catalog resource (the 'type' field), e.g. 'charging', "
            "'parking', 'demographics', 'solar', 'district-heating'."
        )
    ),
]


async def get_city(slug: _Slug) -> ToolEnvelope:
    """Get base data for a German city (population, area, coordinates).

    Sourced from Wikidata. Read-only. Useful as a first lookup to confirm a city
    exists and get its core attributes. For a broader question about the city
    (what data is available at all) use ``get_city_overview`` instead.
    """
    return await client.get_resource(slug, "base")


async def get_city_overview(slug: _Slug) -> ToolEnvelope:
    """Get a ONE-CALL overview of everything InfraNode knows about a German city.

    Start here for any city question. Returns: the city's base data, a CATALOG of
    all ~60 available data types (weather, air quality, public transit, trains,
    traffic, charging, parking, solar, energy, demographics, taxes, accidents,
    tourism, heritage, trees, population density, playgrounds, post boxes and many
    more), each with its coverage status and the exact tool to call next (for most
    data types that is ``get_city_resource(slug, resource=<type>)``), plus a small
    live highlights snapshot (current weather, air quality and train departures).
    Data types not yet covered for this city show where they ARE available so you
    can pivot. InfraNode keeps adding data and cities, so the catalog grows over
    time. Read-only.
    """
    return await client.get_resource(slug, "overview")


async def get_city_resource(slug: _Slug, resource: _ResourceKey) -> ToolEnvelope:
    """Fetch ANY per-city data type by its key (generic accessor, ~60 data types).

    One tool for the whole breadth of InfraNode: live data (air, traffic, transit
    stops, parking, charging, water-level, flood, sharing, fuel-prices, icu-live,
    webcams, station-departures/-arrivals/stations, ...), statistics
    (demographics, unemployment, tourism, accidents, crime-stats, indicators,
    land-values, tax-rates, insolvencies, ...), infrastructure and environment
    (solar, solar-roofs, district-heating, energy, heritage, tree-cadastre,
    playgrounds, public-toilets, markets, education, ...) and more. Discover the
    valid keys and per-city coverage with ``get_city_overview(slug)`` or the
    ``infranode://catalog`` resource; the ``resource`` enum lists every key.
    Uncovered types return ``source_status="not_covered"`` (plus where they ARE
    available), never an error. Read-only.
    """
    return await client.get_resource(slug, resource)


async def air_quality(slug: _Slug) -> ToolEnvelope:
    """Get official air quality for a German city (PM10, NO2 and more).

    Sourced from the Umweltbundesamt (UBA). Read-only. For live nearest-station
    hourly readings use ``get_city_resource(slug, resource='air')`` instead.
    """
    return await client.get_resource(slug, "air-uba")


async def weather(slug: _Slug) -> ToolEnvelope:
    """Get current weather observations for a German city.

    Sourced from the Deutscher Wetterdienst (DWD): temperature, wind,
    precipitation and related fields. Read-only, current conditions only (not a
    forecast). For warnings use ``get_city_resource(slug,
    resource='weather-warnings')``. For a broader question about the city (not
    just weather) use ``get_city_overview`` instead, which already includes a
    live weather highlight.
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


async def station_board_departures(
    eva: Annotated[
        str,
        Field(
            description=(
                "Station EVA number (digits only) from get_city_resource(slug, "
                "resource='stations'), e.g. '8011160' (Berlin Hbf)."
            )
        ),
    ],
) -> ToolEnvelope:
    """Get live departures for ANY railway station by its EVA number.

    Covers all train categories including local/regional (S/RB/RE) and long
    distance, with real-time delays, cancellations and disruption messages. Get
    the EVA from ``get_city_resource(slug, resource='stations')``. Read-only.
    """
    return await client.get_station_board(eva, "departures")


async def station_board_arrivals(
    eva: Annotated[
        str,
        Field(
            description=(
                "Station EVA number (digits only) from get_city_resource(slug, "
                "resource='stations'), e.g. '8000105' (Frankfurt Hbf)."
            )
        ),
    ],
) -> ToolEnvelope:
    """Get live arrivals for ANY railway station by its EVA number.

    Mirror of ``station_board_departures`` for arriving trains (all categories,
    real-time delays, disruption messages). Get the EVA from
    ``get_city_resource(slug, resource='stations')``. Read-only.
    """
    return await client.get_station_board(eva, "arrivals")


async def transit_departures(
    slug: _Slug,
    stop_id: Annotated[
        str | None,
        Field(
            description=(
                "Required stop ID to fetch departures for. Discover a city's stop "
                "IDs with get_city_resource(slug, resource='transit') first (each "
                "stop carries its id). Format: DELFI 'de:<AGS>:<id>' or a numeric "
                "gtfs.de stop id."
            )
        ),
    ] = None,
) -> ToolEnvelope:
    """Get live public-transport departures with real-time delays for a stop.

    Sourced from GTFS-RT/HVV/VGN. Unlike the static stop list
    (``get_city_resource(slug, resource='transit')``), this returns minute-fresh
    departures including delay for ONE stop. A ``stop_id`` is required: fetch the
    city's transit stops first to discover valid stop IDs, then pass one here.
    Read-only.
    """
    if not stop_id:
        # Ohne stop_id kann die Live-Quelle keine Abfahrten liefern. Statt eines
        # harten Fehlers eine ehrliche, selbst-korrigierende Envelope zurueckgeben.
        return {
            "data": None,
            "meta": {
                "source_status": "no_data",
                "note": (
                    "Provide a stop_id to get live departures. Discover valid stop "
                    "IDs for this city with get_city_resource(slug, "
                    "resource='transit'), then call again."
                ),
            },
        }
    return await client.get_live(
        slug, "transit/departures", params={"stop_id": stop_id}
    )


async def list_cities() -> ToolEnvelope:
    """List all covered cities (slug, federal state, population, coverage).

    Takes no arguments. Call this first to discover valid city slugs before
    invoking any city-scoped tool. Read-only.
    """
    # limit explizit auf MAX_LIMIT: der API-Default (50) wuerde die Liste
    # abschneiden und das Tool-Versprechen "list ALL" brechen.
    return await client.get_collection("cities", {"limit": "200"})


async def sources() -> ToolEnvelope:
    """List all data sources with license, attribution and availability.

    Takes no arguments. Shows which upstream sources InfraNode bundles and
    whether each is currently active. Read-only.
    """
    # limit explizit auf MAX_LIMIT (API-Default 50 schnitt bei 76 Quellen ab:
    # eround_charging & Co. fehlten im Tool UND in infranode://sources).
    return await client.get_collection("sources", {"limit": "200"})


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
