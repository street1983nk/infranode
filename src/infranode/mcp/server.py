"""FastMCP-Server-Instanz des InfraNode-MCP-Servers (DX-05).

Der Server registriert je Stadtdaten-Ressource ein Tool. Die eigentliche
Tool-Logik liegt als freistehende async-Funktion in ``infranode.mcp.tools``
(Blocker-4-Aufrufvertrag): ``@mcp.tool()`` wird hier nur duenn ueber diese
Funktionen gelegt, sodass sie direkt als Coroutine testbar bleiben und der
Decorator dennoch das FunctionTool fuer die FastMCP-API registriert.

Es gibt KEINE Mapping-/Lizenz-Logik im Server: jedes Tool ruft ueber
``infranode.mcp.client.get_resource`` die Live-FastAPI und gibt deren
normalisiertes JSON 1:1 zurueck (D-07/D-08). Zwei Transporte:
- stdio (Default): lokaler Subprozess fuer Claude Desktop/Code.
- streamable-http: oeffentlicher Remote-Endpunkt (z.B. mcp.infranode.dev),
  hinter Caddy/Cloudflare, keylos wie die API. Per INFRANODE_MCP_TRANSPORT
  =streamable-http aktiviert; INFRANODE_MCP_API_BASE zeigt dann auf die
  oeffentliche API (https://infranode.dev/api/v1).
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from infranode.mcp import tools
from infranode.registry.catalog import CITY_DATA_CATALOG

# Server-Instructions: werden beim initialize an den Client/Agenten ausgeliefert und
# sind der groesste Discovery-Hebel. Sie sagen dem Agenten, WO er anfangen soll
# (get_city_overview) und wie alles zusammenhaengt, damit er schnell und ohne Raten
# an alle Daten kommt (Owner-Wunsch 2026-06-24).
_INSTRUCTIONS = (
    "InfraNode is a keyless, read-only open-data API for 84 German cities, exposed "
    "as MCP tools. To answer ANY city question, START with get_city_overview(slug): "
    "it returns the city's base data, a catalog of ALL available data types (each "
    "with its coverage status and the exact tool to call next) and a small live "
    "snapshot (weather, air, train departures). Find valid city slugs with "
    "list_cities (or the infranode://cities resource); browse every data type with "
    "the infranode://catalog resource; see sources and licenses with sources. "
    "Compare one metric across many cities in one call with compare. Every tool "
    "returns a canonical {data, meta} envelope; meta.source_status tells you whether "
    "a source delivered data (ok / no_data / not_covered / disabled / error), so a "
    "missing source degrades gracefully instead of failing. Coverage keeps growing: "
    "more data types and cities are added regularly."
)

mcp = FastMCP("infranode", instructions=_INSTRUCTIONS)


# Verhaltens-Hinweise (MCP Tool Annotations): Jedes InfraNode-Tool ist ein
# read-only GET-Wrapper auf die Live-API: es schreibt keinen State, ist gefahrlos
# wiederholbar (idempotent) und nicht destruktiv. Clients koennen Aufrufe so ohne
# Rueckfrage zulassen; Verzeichnis-Scanner (Glama/Smithery) bewerten die
# Transparenz positiv. ``open_world`` unterscheidet ehrlich: Datentools ziehen
# Live-Daten von externen Behoerden-APIs (offene, veraenderliche Domaene = True),
# die Meta-Tools list_cities/sources liefern dagegen InfraNodes eigene,
# abgeschlossene Abdeckungsliste (geschlossene Domaene = False).
def _annotations(*, open_world: bool) -> ToolAnnotations:
    return ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=open_world,
    )


# Duenne Registrierung der freistehenden Tool-Funktionen (Blocker 4): der
# Decorator wird programmatisch ueber jede Funktion gelegt. Die Funktion selbst
# bleibt in infranode.mcp.tools unveraendert als Coroutine aufrufbar; FastMCP
# generiert das Schema aus den Typannotationen und Docstrings.
def _register(fn, *, open_world: bool = True) -> None:
    """Registriert ein Tool mit den read-only Annotations (siehe oben)."""
    mcp.tool(annotations=_annotations(open_world=open_world))(fn)


_register(tools.get_city)
# Owner 2026-06-24: Ein-Aufruf-Ueberblick (Basis + Katalog aller Datenarten +
# Live-Highlights). Discovery-Einstieg, damit Agenten die ganze Breite je Stadt
# sehen (nicht nur Wetter). Zieht Live-Highlights -> open_world=True.
_register(tools.get_city_overview)
_register(tools.air_quality)
_register(tools.air_quality_live)
_register(tools.weather)
_register(tools.pois)
_register(tools.traffic)
_register(tools.transit)
_register(tools.charging)
_register(tools.water_level)
_register(tools.flood)
_register(tools.pollen_uv)
_register(tools.demographics)
_register(tools.energy)
_register(tools.geo)
_register(tools.election)
_register(tools.holidays)
_register(tools.health)
_register(tools.icu_live)
_register(tools.road_events)
_register(tools.events)
_register(tools.webcams)
# SMARD/DWD (frueher ergaenzte Endpunkte, jetzt als MCP-Tools nachgezogen).
_register(tools.power_load)
_register(tools.power_price)
_register(tools.weather_warnings)
# DATA-27/28/29: KBA Pkw-Bestand + GENESIS-Trio + Unfallatlas (Tier A).
_register(tools.vehicle_registrations)
_register(tools.unemployment)
_register(tools.tourism)
_register(tools.construction)
_register(tools.accidents)
# DATA-30: Tankerkoenig Spritpreise (Tier A, aggregiert je Stadt).
_register(tools.fuel_prices)
# DATA-33: GBFS-Bike-/Scooter-Sharing (Tier A, aggregiert je Stadt).
_register(tools.sharing)
# DATA-38: PVGIS-Solar-Einstrahlung + normierter PV-Ertrag je Stadt (Tier A, alle 84).
_register(tools.solar)
# DATA-39: Dach-Solarkataster je Stadt (NRW-Pilot, Tier A, Teilabdeckung).
_register(tools.solar_roofs)
# DATA-32: INKAR/BBSR sozialoekonomische Indikatoren je Kreis (Tier A).
_register(tools.indicators)
# DATA-35: BORIS amtliche Bodenrichtwerte je Stadt (Tier A, aggregiert, Bauland).
_register(tools.land_values)
# DATA-37: Regionalstatistik.de Realsteuer-Hebesaetze (Gemeinde) + Gewerbean-/
# -abmeldungen (Kreis), Tier A.
_register(tools.tax_rates)
_register(tools.business_registrations)
# DATA-37: Regionalstatistik.de beantragte Insolvenzen je Kreis (52411-02
# Unternehmen + 52411-03 uebrige Schuldner), Tier A.
_register(tools.insolvencies)
# DATA-34: DB-Timetables Bahnhof-Abfahrten + -Ankuenfte Metropolen-Hbf (Tier A).
_register(tools.station_departures)
_register(tools.station_arrivals)
# DATA-36: StaDa Bahnhofs-Katalog je Stadt + Per-Bahnhof-Live-Boards (jede EVA,
# alle Gattungen inkl. Nahverkehr, Stoerungen/Meldungen). Tier A.
_register(tools.stations)
_register(tools.station_board_departures)
_register(tools.station_board_arrivals)
# DATA-26: Live-/Meta-Tools (echte neue Faehigkeiten, nicht slug-redundant):
# Echtzeit-Abfahrten, Staedte-Liste, Quellen-Uebersicht. list_cities/sources
# beschreiben die eigene Abdeckung -> geschlossene Domaene (open_world=False).
_register(tools.transit_departures)
# Frankfurt am Main Live-Parkbelegung (Mobilithek DATEX II V3, stadt-fix; weitere
# Park-Staedte folgen ueber dieselbe parking-Route -> Tool laeuft automatisch mit).
_register(tools.parking)
_register(tools.list_cities, open_world=False)
_register(tools.sources, open_world=False)
# API-05/D-06: Multi-City-Compare einer Ressource (weather/air) in einer Antwort.
_register(tools.compare)
# DATA-OSM (Tier 1): 10 dedizierte OSM-Overpass-Datenarten (ODbL, Tier B).
_register(tools.playgrounds)
_register(tools.drinking_water)
_register(tools.markets)
_register(tools.parcel_lockers)
_register(tools.post_offices)
_register(tools.post_boxes)
_register(tools.public_wifi)
_register(tools.recycling_centres)
_register(tools.government_offices)
_register(tools.education)
# DATA-OSM-Tier-2: Denkmallisten je Bundesland (Land-WFS, coverage-gated).
_register(tools.heritage)
# DATA-OSM-Tier-2: Baumkataster je Stadt (kommunaler WFS, coverage-gated).
_register(tools.tree_cadastre)
# DATA-OSM-Tier-2: Einwohnerdichte (Zensus-2022-100m-Gitter, alle Staedte).
_register(tools.population_density)
# TENDER-05/06: Oeffentliche Auftragsvergabe je Stadt (oeffentlichevergabe.de,
# OCDS, CC0/Tier A). Zieht Live-/Store-Daten von der API -> open_world=True.
_register(tools.public_tenders)
# DATA-40: Kommunale Radzaehlstellen je Stadt (Dauerzaehlstellen, Tier A,
# Teilabdeckung). Zieht Zaehldaten von externen kommunalen Quellen -> open_world=True.
# NICHT das sharing-Tool (GBFS-Leihfahrzeuge).
_register(tools.bike_counts)


# MCP Resources: expose the coverage catalog as browsable resources, so clients
# can discover what InfraNode offers (cities + sources) without a tool call.
@mcp.resource("infranode://cities")
async def cities_resource() -> dict:
    """All covered German cities with slug, federal state, population and coverage."""
    return await tools.list_cities()


@mcp.resource("infranode://sources")
async def sources_resource() -> dict:
    """All InfraNode data sources with license, attribution and availability."""
    return await tools.sources()


@mcp.resource("infranode://catalog")
async def catalog_resource() -> dict:
    """The catalog of all per-city data types: label, matching tool and REST path.

    Lets an agent browse the full breadth of InfraNode (every data type and the tool
    that fetches it) without a tool call. For a live, per-city view with coverage
    status and highlights, call get_city_overview(slug).
    """
    return {
        "data_types": [
            {
                "type": dt.key,
                "label": dt.label_en,
                "tool": dt.tool,
                "path": f"/api/v1/cities/{{slug}}/{dt.key}",
            }
            for dt in CITY_DATA_CATALOG
        ],
        "note": (
            "InfraNode keeps adding more data types and cities. Start with "
            "get_city_overview(slug) for a live, per-city view."
        ),
    }


# MCP Prompts: a few ready-made prompts that showcase common multi-tool flows.
@mcp.prompt()
def city_overview(slug: str) -> str:
    """Get a complete picture of a German city and what InfraNode offers for it."""
    return (
        f"Give me an overview of the German city '{slug}'. Call get_city_overview "
        "first to see its base data, every available data type (with the tool to "
        "fetch each) and a live snapshot, then pull the most relevant data types in "
        "full and summarize the situation."
    )


@mcp.prompt()
def city_briefing(slug: str) -> str:
    """A concise live briefing (weather, air, transit) for a German city."""
    return (
        f"Give me a concise current briefing for the German city '{slug}'. "
        "Use the InfraNode tools to fetch weather, air quality and live "
        "public-transport departures, then summarize the situation in a few "
        "bullet points. If a source has no data, say so briefly."
    )


@mcp.prompt()
def compare_air_quality(cities: str) -> str:
    """Compare current air quality across several German cities."""
    return (
        f"Compare the current air quality across these German cities: {cities}. "
        "Use the InfraNode 'compare' tool with resource='air', then rank the "
        "cities from cleanest to most polluted and note any missing data."
    )


@mcp.prompt()
def commute_check(slug: str) -> str:
    """Check the live commute/transit situation for a German city."""
    return (
        f"Check the live commute situation in the German city '{slug}': pull "
        "real-time public-transport departures (transit_departures) and any "
        "motorway roadworks/traffic, then tell me whether there are notable "
        "delays right now."
    )


def run() -> None:
    """Startet den Server im per Env gewaehlten Transport.

    stdio (Default): kein offener Port, lokaler Subprozess. streamable-http:
    bindet einen HTTP-Port (INFRANODE_MCP_HOST/-PORT) fuer den oeffentlichen
    Remote-Endpunkt. Host-Default 127.0.0.1; der Container-Service setzt
    INFRANODE_MCP_HOST=0.0.0.0, damit Caddy ihn ueber das Compose-Netz erreicht.
    """
    transport = os.environ.get("INFRANODE_MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        from mcp.server.transport_security import TransportSecuritySettings

        mcp.settings.host = os.environ.get("INFRANODE_MCP_HOST", "127.0.0.1")
        mcp.settings.port = int(os.environ.get("INFRANODE_MCP_PORT", "8081"))
        # Der MCP-Transport hat einen DNS-Rebinding-Schutz, der per Default nur
        # localhost-Hosts/-Origins erlaubt (gedacht fuer lokal gebundene Server).
        # Hinter Caddy/Cloudflare variieren Host/Origin; fuer eine oeffentliche,
        # keylose read-only API ist der Schutz nicht noetig und blockt sonst alle
        # Calls (HTTP 421). Default daher aus; per
        # INFRANODE_MCP_DNS_REBINDING_PROTECTION=1 mit expliziten Allowlists
        # (INFRANODE_MCP_ALLOWED_HOSTS/-ORIGINS, kommagetrennt) wieder scharf.
        if os.environ.get("INFRANODE_MCP_DNS_REBINDING_PROTECTION") == "1":
            hosts = [
                h.strip()
                for h in os.environ.get("INFRANODE_MCP_ALLOWED_HOSTS", "").split(",")
                if h.strip()
            ]
            origins = [
                o.strip()
                for o in os.environ.get("INFRANODE_MCP_ALLOWED_ORIGINS", "").split(",")
                if o.strip()
            ]
            mcp.settings.transport_security = TransportSecuritySettings(
                enable_dns_rebinding_protection=True,
                allowed_hosts=hosts,
                allowed_origins=origins,
            )
        else:
            mcp.settings.transport_security = TransportSecuritySettings(
                enable_dns_rebinding_protection=False,
            )
        # Eigener uvicorn-Start statt mcp.run(transport=...), damit wir die
        # Streamable-HTTP-App mit der IP-Rate-Limit-Middleware umhuellen koennen
        # (Security-Haertung 2026-06-21): der oeffentliche MCP-Endpunkt hatte
        # sonst KEINE Drosselung. mcp.run() wuerde intern denselben
        # streamable_http_app() bauen und per uvicorn starten; wir reichen nur die
        # Middleware dazwischen. Die App-eigene Lifespan (Session-Manager) bleibt
        # erhalten, da uvicorn sie aus der ASGI-App ausfuehrt.
        import uvicorn

        from infranode.mcp.ratelimit import MCPRateLimitMiddleware

        app = mcp.streamable_http_app()
        app.add_middleware(MCPRateLimitMiddleware)
        uvicorn.run(
            app,
            host=mcp.settings.host,
            port=mcp.settings.port,
            log_level=mcp.settings.log_level.lower(),
        )
    else:
        mcp.run()


if __name__ == "__main__":
    run()
