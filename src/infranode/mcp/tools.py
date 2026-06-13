"""Freistehende async-Tool-Funktionen des InfraNode-MCP-Servers (DX-05).

AUFRUF-VERTRAG (Blocker 4): Jede Tool-Logik liegt hier als freistehende
async-Funktion (Modul-Funktion), die in ``server.py`` nur duenn via
``@mcp.tool()`` registriert wird. Dadurch bleibt die Funktion direkt als
Coroutine testbar, unabhaengig davon, ob der Decorator das Callable durch ein
FunctionTool-Objekt ersetzt.

Jede Funktion ist ein Thin-Wrapper: sie ruft ``client.get_resource`` mit dem
festen Ressourcen-Namen und gibt das normalisierte JSON 1:1 zurueck. Es gibt
KEINE Mapping-/Lizenz-Logik hier (die lebt ausschliesslich in der Live-API).
Die SSRF-/Injection-Gates (T-12-MCP-SSRF, T-12-MCP-INJECT) sitzen in
``client.get_resource`` und greifen vor jedem Request.
"""

from __future__ import annotations

from infranode.mcp import client


async def get_city(slug: str) -> dict:
    """Stammdaten einer Stadt (Einwohner, Flaeche, Geo) via Wikidata.

    Args:
        slug: Stadt-Slug, z.B. ``"berlin"`` oder ``"hamburg"``.
    """
    return await client.get_resource(slug, "base")


async def air_quality(slug: str) -> dict:
    """UBA-Luftqualitaet (PM10/NO2 u.a.) einer Stadt."""
    return await client.get_resource(slug, "air-uba")


async def air_quality_live(slug: str) -> dict:
    """Live-Luftqualitaet via OpenAQ (Tier C, live-only) einer Stadt."""
    return await client.get_resource(slug, "air")


async def weather(slug: str) -> dict:
    """Aktuelle Wetterdaten einer Stadt via Deutscher Wetterdienst (DWD)."""
    return await client.get_resource(slug, "weather")


async def pois(slug: str, type: str) -> dict:
    """Points of Interest einer Stadt, gefiltert nach Typ.

    Args:
        slug: Stadt-Slug, z.B. ``"koeln"``.
        type: POI-Typ aus der API-Whitelist (z.B. ``"hospital"``,
            ``"school"``, ``"pharmacy"``, ``"restaurant"``, ``"police"``,
            ``"kindergarten"``).
    """
    return await client.get_resource(slug, "pois", params={"type": type})


async def traffic(slug: str) -> dict:
    """Baustellen und Verkehrsmeldungen einer Region via Autobahn-API."""
    return await client.get_resource(slug, "traffic")


async def transit(slug: str) -> dict:
    """OEPNV-Haltestellen einer Stadt (DELFI/GTFS, HVV)."""
    return await client.get_resource(slug, "transit")


async def charging(slug: str) -> dict:
    """E-Ladesaeulen-Standorte einer Stadt via Bundesnetzagentur."""
    return await client.get_resource(slug, "charging")


async def water_level(slug: str) -> dict:
    """Pegelstaende einer Stadt an Bundeswasserstrassen via PEGELONLINE."""
    return await client.get_resource(slug, "water-level")


async def flood(slug: str) -> dict:
    """Hochwasser-Warnstufen einer Stadt via Laenderhochwasserportal."""
    return await client.get_resource(slug, "flood")


async def pollen_uv(slug: str) -> dict:
    """Pollenflug und UV-Index der Grossregion einer Stadt via DWD."""
    return await client.get_resource(slug, "pollen-uv")


async def demographics(slug: str) -> dict:
    """Demografie-Kennzahlen einer Stadt via GENESIS/Regionalstatistik."""
    return await client.get_resource(slug, "demographics")


async def energy(slug: str) -> dict:
    """Energie-/Anlagen-Kennzahlen einer Stadt via Marktstammdatenregister."""
    return await client.get_resource(slug, "energy")


async def geo(slug: str) -> dict:
    """Geodaten/Grenzen einer Stadt."""
    return await client.get_resource(slug, "geo")


async def election(slug: str) -> dict:
    """Wahlergebnisse einer Stadt."""
    return await client.get_resource(slug, "election")


async def holidays(slug: str) -> dict:
    """Gesetzliche Feiertage einer Stadt bzw. ihres Bundeslandes."""
    return await client.get_resource(slug, "holidays")


async def health(slug: str) -> dict:
    """Krankenhausverzeichnis einer Stadt via Regionalstatistik."""
    return await client.get_resource(slug, "health")


async def icu_live(slug: str) -> dict:
    """Live-Intensivbetten-Auslastung einer Stadt via DIVI."""
    return await client.get_resource(slug, "icu-live")


async def road_events(slug: str) -> dict:
    """Innerstaedtische Baustellen und Sperrungen einer Stadt."""
    return await client.get_resource(slug, "road-events")


async def events(slug: str) -> dict:
    """Stadt-Events und Veranstaltungen einer Stadt."""
    return await client.get_resource(slug, "events")


async def webcams(slug: str) -> dict:
    """Verkehrs-Webcams einer Region via Autobahn-API."""
    return await client.get_resource(slug, "webcams")
