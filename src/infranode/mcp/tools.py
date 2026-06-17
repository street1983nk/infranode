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


async def power_load(slug: str) -> dict:
    """Stromverbrauch (Netzlast) der Regelzone einer Stadt, Tageswert (SMARD)."""
    return await client.get_resource(slug, "power-load")


async def power_price(slug: str) -> dict:
    """Day-ahead-Boersenstrompreis (bundesweit), Tageswert (SMARD)."""
    return await client.get_resource(slug, "power-price")


async def weather_warnings(slug: str) -> dict:
    """Amtliche DWD-Wetterwarnungen einer Stadt (hoechste Warnstufe)."""
    return await client.get_resource(slug, "weather-warnings")


async def vehicle_registrations(slug: str) -> dict:
    """Pkw-Bestand und Elektro-Anteil einer Stadt je Zulassungsbezirk (KBA)."""
    return await client.get_resource(slug, "vehicle-registrations")


async def unemployment(slug: str) -> dict:
    """Arbeitslose und Arbeitslosenquote einer Stadt je Kreis (Regionalstatistik)."""
    return await client.get_resource(slug, "unemployment")


async def tourism(slug: str) -> dict:
    """Gaesteuebernachtungen und Ankuenfte einer Stadt je Kreis (Regionalstatistik)."""
    return await client.get_resource(slug, "tourism")


async def construction(slug: str) -> dict:
    """Baugenehmigungen (Wohngebaeude/Wohnungen) je Kreis (Regionalstatistik)."""
    return await client.get_resource(slug, "construction")


async def accidents(slug: str) -> dict:
    """Strassenverkehrsunfaelle einer Stadt je Kreis, Jahres-Aggregat (Unfallatlas)."""
    return await client.get_resource(slug, "accidents")


async def fuel_prices(slug: str) -> dict:
    """Aktuelle Spritpreise einer Stadt, aggregiert (Durchschnitt/Minimum je Sorte)."""
    return await client.get_resource(slug, "fuel-prices")


async def sharing(slug: str) -> dict:
    """Bike-/Scooter-Sharing einer Stadt, aggregiert (Fahrzeuge + Stationen)."""
    return await client.get_resource(slug, "sharing")


async def indicators(slug: str) -> dict:
    """Sozialoekonomische INKAR/BBSR-Indikatoren einer Stadt (Kreisebene, je Jahr)."""
    return await client.get_resource(slug, "indicators")


async def station_departures(slug: str) -> dict:
    """Live-Abfahrten am Fernverkehrs-Hbf der Stadt (DB Timetables, mit Verspaetung)."""
    return await client.get_resource(slug, "station-departures")


async def station_arrivals(slug: str) -> dict:
    """Live-Ankuenfte am Fernverkehrs-Hbf der Stadt (DB Timetables, mit Verspaetung)."""
    return await client.get_resource(slug, "station-arrivals")


async def transit_departures(slug: str, stop_id: str | None = None) -> dict:
    """Live-OEPNV-Abfahrten je Halt mit Echtzeit-Verspaetung (GTFS-RT/HVV/VGN).

    Anders als ``transit`` (statische Haltestellen) liefert dies minutenfrische
    Abfahrten inkl. Verspaetung.

    Args:
        slug: Stadt-Slug, z.B. ``"berlin"`` oder ``"hamburg"``.
        stop_id: Optionale Halt-ID; ohne sie liefert die Quelle die verfuegbaren
            Abfahrten der Stadt.
    """
    params = {"stop_id": stop_id} if stop_id else None
    return await client.get_live(slug, "transit/departures", params=params)


async def list_cities() -> dict:
    """Liste aller abgedeckten Staedte (Slug, Bundesland, Einwohner, Abdeckung).

    Ohne Argumente. Hilfreich, um gueltige Stadt-Slugs zu ermitteln, bevor ein
    stadtbezogenes Tool aufgerufen wird.
    """
    return await client.get_collection("cities")


async def sources() -> dict:
    """Uebersicht aller Datenquellen mit Lizenz, Attribution und Verfuegbarkeit.

    Ohne Argumente. Zeigt, welche Quellen InfraNode buendelt und ob sie aktiv sind.
    """
    return await client.get_collection("sources")
