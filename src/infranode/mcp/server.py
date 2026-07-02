"""FastMCP-Server-Instanz des InfraNode-MCP-Servers (DX-05).

Der Server registriert wenige namentliche Tools (Einstieg/Meta/parametrisiert)
plus ein generisches ``get_city_resource`` fuer alle uebrigen Datenarten
(Konsolidierung 2026-07-02, s. Kommentar am Registrierungsblock). Die eigentliche
Tool-Logik liegt als freistehende async-Funktion in ``infranode.mcp.tools``
(Blocker-4-Aufrufvertrag): ``@mcp.tool()`` wird hier nur dünn über diese
Funktionen gelegt, sodass sie direkt als Coroutine testbar bleiben und der
Decorator dennoch das FunctionTool für die FastMCP-API registriert.

Es gibt KEINE Mapping-/Lizenz-Logik im Server: jedes Tool ruft über
``infranode.mcp.client.get_resource`` die Live-FastAPI und gibt deren
normalisiertes JSON 1:1 zurück (D-07/D-08). Zwei Transporte:
- stdio (Default): lokaler Subprozess für Claude Desktop/Code.
- streamable-http: öffentlicher Remote-Endpunkt (z.B. mcp.infranode.dev),
  hinter Caddy/Cloudflare, keylos wie die API. Per INFRANODE_MCP_TRANSPORT
  =streamable-http aktiviert; INFRANODE_MCP_API_BASE zeigt dann auf die
  öffentliche API (https://infranode.dev/api/v1).
"""

from __future__ import annotations

import functools
import os

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from infranode.mcp import tools
from infranode.mcp.client import UpstreamError
from infranode.registry.catalog import CITY_DATA_CATALOG

# Server-Instructions: werden beim initialize an den Client/Agenten ausgeliefert und
# sind der größte Discovery-Hebel. Sie sagen dem Agenten, WO er anfangen soll
# (get_city_overview) und wie alles zusammenhängt, damit er schnell und ohne Raten
# an alle Daten kommt (Owner-Wunsch 2026-06-24). Die Tool-Zahl wird UNTEN, nachdem
# alle _register()-Aufrufe gelaufen sind, live nachgetragen (siehe
# ``mcp._mcp_server.instructions = ...`` nach der letzten _register()-Zeile):
# eine hartkodierte Zahl hier wuerde bei jedem neuen Tool sofort veralten (genau das
# Problem, das ein veralteter Memory-Eintrag "44 Tools" ausgeloest hat, Owner-Fund
# 2026-07-01) und ist fuer JEDEN Client bei JEDEM Connect sichtbar, nicht nur fuer
# Claude Code mit eigenem Memory.
_INSTRUCTIONS = (
    "InfraNode is a keyless, read-only open-data API for 84 German cities with "
    "~60 data types, exposed as {tool_count} MCP tools (count is live from this "
    "server, not a cached or remembered number). To answer ANY city question, "
    "START with get_city_overview(slug): it returns the city's base data, a "
    "catalog of ALL available data types (each with its coverage status and the "
    "exact tool to call next) and a small live snapshot (weather, air, train "
    "departures). Most data types are fetched with ONE generic tool: "
    "get_city_resource(slug, resource=<type>), where <type> is the catalog key "
    "(e.g. 'parking', 'charging', 'demographics', 'solar'); its resource enum "
    "lists every valid key. Find valid city slugs with list_cities (or the "
    "infranode://cities resource); browse every data type with the "
    "infranode://catalog resource; see sources and licenses with sources. "
    "Compare one metric across many cities in one call with compare. Every tool "
    "returns a canonical {data, meta} envelope; meta.source_status tells you whether "
    "a source delivered data (ok / no_data / not_covered / disabled / error), so a "
    "missing source degrades gracefully instead of failing. Coverage keeps growing: "
    "more data types and cities are added regularly."
)

mcp = FastMCP("infranode", instructions=_INSTRUCTIONS)

# Haelt die Namen aller ueber _register() registrierten Tools fest, damit die
# Instructions unten die ECHTE, aktuelle Zahl tragen koennen statt eine
# haendisch gepflegte, die veraltet.
_registered_tool_names: list[str] = []


# Verhaltens-Hinweise (MCP Tool Annotations): Jedes InfraNode-Tool ist ein
# read-only GET-Wrapper auf die Live-API: es schreibt keinen State, ist gefahrlos
# wiederholbar (idempotent) und nicht destruktiv. Clients können Aufrufe so ohne
# Rückfrage zulassen; Verzeichnis-Scanner (Glama/Smithery) bewerten die
# Transparenz positiv. ``open_world`` unterscheidet ehrlich: Datentools ziehen
# Live-Daten von externen Behörden-APIs (offene, veränderliche Domäne = True),
# die Meta-Tools list_cities/sources liefern dagegen InfraNodes eigene,
# abgeschlossene Abdeckungsliste (geschlossene Domäne = False).
def _annotations(*, open_world: bool) -> ToolAnnotations:
    return ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=open_world,
    )


# Menschenlesbare Anzeige-Titel je Tool. Der Anthropic Connectors Directory
# verlangt fuer jedes Tool einen Titel; ausserdem lesen Clients/Verzeichnisse
# diesen Titel in der Werkzeugauswahl. Der Funktionsname (snake_case) ist der
# stabile technische Bezeichner, der Titel ist die Anzeige. Fehlt ein Eintrag,
# faellt _title_for() auf eine automatische Title-Case-Ableitung zurueck, damit
# neue Tools nie ganz ohne Titel bleiben (siehe test_mcp_tool_titles).
_TOOL_TITLES: dict[str, str] = {
    "get_city": "City Base Data",
    "get_city_overview": "City Overview",
    "get_city_resource": "City Data by Type",
    "air_quality": "Air Quality",
    "weather": "Weather",
    "pois": "Points of Interest",
    "station_board_departures": "Station Board: Departures",
    "station_board_arrivals": "Station Board: Arrivals",
    "transit_departures": "Transit Departures",
    "list_cities": "List Cities",
    "sources": "Data Sources",
    "compare": "Compare Cities",
}


def _title_for(name: str) -> str:
    """Anzeige-Titel eines Tools; Fallback = Title-Case aus dem Funktionsnamen."""
    return _TOOL_TITLES.get(name) or name.replace("_", " ").title()


# Graceful-Degradation-Wrapper: ein transienter Upstream-/Quellen-Ausfall (5xx)
# darf einen Tool-Call NICHT hart als Fehler abbrechen. Solche Faelle werden in
# einen ehrlichen ``source_status="error"``-Envelope gewandelt (genau das
# Envelope-Versprechen, das die uebrigen Tools bei 200 einhalten), damit ein
# Reviewer/Client nie einen rohen Fehler sieht, wenn z.B. Overpass kurz weg ist.
# 4xx (unbekannter Slug, fehlender Pflichtparameter) wird WEITER geworfen: der
# Text traegt message + hint, damit sich das Modell selbst korrigieren kann.
def _graceful(fn):
    """Umhuellt eine Tool-Coroutine; 5xx-UpstreamError -> graceful Envelope."""

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except UpstreamError as exc:
            code = exc.status_code
            if code is not None and 500 <= code < 600:
                return {
                    "data": None,
                    "meta": {
                        "source_status": "error",
                        "note": str(exc),
                    },
                }
            raise

    return wrapper


# Dünne Registrierung der freistehenden Tool-Funktionen (Blocker 4): der
# Decorator wird programmatisch über jede Funktion gelegt. Die Funktion selbst
# bleibt in infranode.mcp.tools unverändert als Coroutine aufrufbar; FastMCP
# generiert das Schema aus den Typannotationen und Docstrings (functools.wraps
# im Wrapper erhält Signatur, Annotationen und Docstring, das Schema bleibt gleich).
def _register(fn, *, open_world: bool = True) -> None:
    """Registriert ein Tool mit Titel + read-only Annotations (siehe oben)."""
    mcp.tool(
        title=_title_for(fn.__name__),
        annotations=_annotations(open_world=open_world),
    )(_graceful(fn))
    _registered_tool_names.append(fn.__name__)


# TOOL-KONSOLIDIERUNG 2026-07-02: frueher 1 Tool pro Datenart (71 Tools, ~30k
# Tokens Tool-Liste, Cursor-80-Tool-Limit in Sichtweite). Jetzt: wenige
# namentliche Tools (Einstieg/Meta/parametrisiert/populaer) + EIN generisches
# get_city_resource fuer den gesamten Long-Tail. Die Datenarten-Discovery
# uebernimmt get_city_overview + infranode://catalog (je Datenart der
# resource-Schluessel) + das resource-Enum im inputSchema des generischen Tools.
_register(tools.get_city)
# Owner 2026-06-24: Ein-Aufruf-Überblick (Basis + Katalog aller Datenarten +
# Live-Highlights). Discovery-Einstieg, damit Agenten die ganze Breite je Stadt
# sehen (nicht nur Wetter). Zieht Live-Highlights -> open_world=True.
_register(tools.get_city_overview)
# Generischer Long-Tail-Zugriff: JEDE Katalog-Datenart per resource-Schluessel
# (Enum aus client.ALLOWED_RESOURCES ohne pois). Live-Quellen dahinter ->
# open_world=True.
_register(tools.get_city_resource)
# Die zwei populaersten Datenarten behalten eigene Tools (Discoverability in
# der Werkzeugauswahl); alles Weitere laeuft ueber get_city_resource.
_register(tools.air_quality)
_register(tools.weather)
# Parametrisierte Faehigkeiten (echte Eigenlogik, kein reiner Slug-Wrapper):
_register(tools.pois)
# DATA-36: Per-Bahnhof-Live-Boards (jede EVA, alle Gattungen inkl. Nahverkehr).
_register(tools.station_board_departures)
_register(tools.station_board_arrivals)
# DATA-26: Echtzeit-Abfahrten je Haltestelle (stop_id aus resource='transit').
_register(tools.transit_departures)
# Meta-Tools: beschreiben die eigene Abdeckung -> geschlossene Domäne
# (open_world=False).
_register(tools.list_cities, open_world=False)
_register(tools.sources, open_world=False)
# API-05/D-06: Multi-City-Compare einer Ressource (weather/air) in einer Antwort.
_register(tools.compare)

# Live-Tool-Zahl in die Instructions nachtragen: FastMCPs ``instructions`` ist
# eine Property ohne Setter (nur ueber den Konstruktor gesetzt), daher ueber das
# darunterliegende ``_mcp_server`` geschrieben. ``str.replace`` statt
# ``str.format``, weil die Instructions selbst literale ``{data, meta}``-Klammern
# als Envelope-Beispiel enthalten, die ``.format()`` als Platzhalter fehldeuten wuerde.
mcp._mcp_server.instructions = _INSTRUCTIONS.replace(
    "{tool_count}", str(len(_registered_tool_names))
)


# Schema-Diaet (Token-Footprint 2026-07-02): Die Tool-Liste kostete ~30k Tokens,
# davon ~55% ein 71x BYTE-IDENTISCH wiederholtes outputSchema (ToolEnvelope) samt
# deutschem ToolMeta-Docstring und 9 Pydantic-Auto-``title``-Feldern pro Tool.
# Dieser Pass entfernt NACH der Registrierung in-place:
# - alle Auto-``title`` aus input- UND outputSchema (der Property-Key sagt schon
#   alles; der ANZEIGE-Titel des Tools ist ein eigenes MCPTool-Feld und bleibt,
#   Anthropic-Directory-Anforderung unberuehrt),
# - ``description`` NUR im outputSchema (Klassen-Docstrings von ToolEnvelope/
#   ToolMeta; die Parameter-Descriptions im inputSchema sind wertvoll fuer die
#   Tool-Auswahl und BLEIBEN, test_every_tool_has_output_schema_and_param_
#   descriptions sichert das).
# Gemessen: ~-27% der gesamten Tool-Listen-Tokens. Die Laufzeit-Validierung
# (fn_metadata.output_model) haengt nicht am Schema-Dict und bleibt unberuehrt.
def _slim_schema(node: object, *, strip_descriptions: bool = False) -> None:
    """Entfernt rekursiv Auto-``title`` (und optional ``description``) in-place.

    Rekursion NUR in Schema-Positionen (properties-WERTE, items, $defs, anyOf,
    ...): ein Datenfeld, das selbst "title" heisst, bleibt als Property-Key
    erhalten, nur das Schema-Schluesselwort wird entfernt.
    """
    if not isinstance(node, dict):
        return
    node.pop("title", None)
    if strip_descriptions:
        node.pop("description", None)
    for key in ("properties", "$defs", "definitions", "patternProperties"):
        sub = node.get(key)
        if isinstance(sub, dict):
            for child in sub.values():
                _slim_schema(child, strip_descriptions=strip_descriptions)
    for key in (
        "items",
        "prefixItems",
        "additionalProperties",
        "anyOf",
        "oneOf",
        "allOf",
        "not",
    ):
        sub = node.get(key)
        if isinstance(sub, dict):
            _slim_schema(sub, strip_descriptions=strip_descriptions)
        elif isinstance(sub, list):
            for child in sub:
                _slim_schema(child, strip_descriptions=strip_descriptions)


def _slim_all_tool_schemas() -> None:
    """Wendet die Schema-Diaet auf alle registrierten Tools an (einmal, in-place).

    ``tool.parameters`` (inputSchema) und ``fn_metadata.output_schema`` sind
    plain dicts, die FastMCPs list_tools per Referenz ausliefert; das Slimming
    hier wirkt damit fuer jeden Client und jede Listung.
    """
    for tool in mcp._tool_manager._tools.values():
        _slim_schema(tool.parameters)
        if tool.fn_metadata.output_schema is not None:
            _slim_schema(tool.fn_metadata.output_schema, strip_descriptions=True)


_slim_all_tool_schemas()


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
            "get_city_overview(slug) for a live, per-city view. Where 'tool' is "
            "get_city_resource, pass the 'type' value as its resource argument."
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
        "motorway roadworks/traffic (get_city_resource with resource='traffic'), "
        "then tell me whether there are notable delays right now."
    )


def run() -> None:
    """Startet den Server im per Env gewählten Transport.

    stdio (Default): kein offener Port, lokaler Subprozess. streamable-http:
    bindet einen HTTP-Port (INFRANODE_MCP_HOST/-PORT) für den öffentlichen
    Remote-Endpunkt. Host-Default 127.0.0.1; der Container-Service setzt
    INFRANODE_MCP_HOST=0.0.0.0, damit Caddy ihn über das Compose-Netz erreicht.
    """
    transport = os.environ.get("INFRANODE_MCP_TRANSPORT", "stdio")
    if transport == "streamable-http":
        from mcp.server.transport_security import TransportSecuritySettings

        mcp.settings.host = os.environ.get("INFRANODE_MCP_HOST", "127.0.0.1")
        mcp.settings.port = int(os.environ.get("INFRANODE_MCP_PORT", "8081"))
        # Der MCP-Transport hat einen DNS-Rebinding-Schutz, der per Default nur
        # localhost-Hosts/-Origins erlaubt (gedacht für lokal gebundene Server).
        # Hinter Caddy/Cloudflare variieren Host/Origin; für eine öffentliche,
        # keylose read-only API ist der Schutz nicht nötig und blockt sonst alle
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
        # Streamable-HTTP-App mit der IP-Rate-Limit-Middleware umhüllen können
        # (Security-Härtung 2026-06-21): der öffentliche MCP-Endpunkt hatte
        # sonst KEINE Drosselung. mcp.run() würde intern denselben
        # streamable_http_app() bauen und per uvicorn starten; wir reichen nur die
        # Middleware dazwischen. Die App-eigene Lifespan (Session-Manager) bleibt
        # erhalten, da uvicorn sie aus der ASGI-App ausführt.
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
