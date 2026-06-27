"""Statischer Katalog aller Stadt-Datenarten (Discovery-Schicht fuer /overview).

Owner-Wunsch (2026-06-24): MCP-Agenten und Endnutzer sollen auf einen Blick sehen,
wie VIELE Datenarten es pro Stadt gibt, nicht nur das meistgenutzte Wetter. Dieser
Katalog ist die EINZIGE Quelle der Datenart-Labels + zugehoeriger MCP-Tool-Namen
fuer den ``GET /cities/{slug}/overview``-Endpunkt.

Reine statische Metadaten (keine Upstream-Calls). Die Verfuegbarkeit je Stadt wird
zur Laufzeit guenstig aus ``registry.coverage`` abgeleitet. Eine Assertion im Test
``tests/integration/test_city_overview.py`` haelt die Schluessel deckungsgleich mit
der MCP-Allowlist (``mcp.client.ALLOWED_RESOURCES``), damit der Katalog beim
Hinzufuegen einer neuen Datenart nicht still zurueckfaellt.
"""

from __future__ import annotations

from typing import NamedTuple


class DataType(NamedTuple):
    """Eine Stadt-Datenart fuer den Overview-Katalog.

    ``key`` ist das letzte Pfadsegment (``/cities/{slug}/<key>``) und zugleich der
    Coverage-Schluessel (``registry.coverage.is_covered``). ``tool`` ist der Name
    des zugehoerigen MCP-Tools, damit ein Agent direkt weiterspringen kann.
    """

    key: str
    tool: str
    label: str
    label_en: str


# Genau die City-Sub-Ressourcen aus ``mcp.client.ALLOWED_RESOURCES`` (Test haelt
# die Mengen deckungsgleich). Labels mit echten Umlauten (deutsche Schreibweise).
CITY_DATA_CATALOG: tuple[DataType, ...] = (
    DataType("base", "get_city", "Basisdaten", "Base data"),
    DataType("weather", "weather", "Wetter", "Weather"),
    DataType(
        "weather-warnings", "weather_warnings", "Wetterwarnungen", "Weather warnings"
    ),
    DataType("pollen-uv", "pollen_uv", "Pollen & UV-Index", "Pollen & UV index"),
    DataType("air", "air_quality_live", "Luftqualität (live)", "Air quality (live)"),
    DataType(
        "air-uba", "air_quality", "Luftqualität (amtlich)", "Air quality (official)"
    ),
    DataType("transit", "transit", "ÖPNV-Haltestellen", "Public transit stops"),
    DataType(
        "station-departures",
        "station_departures",
        "Bahn-Abfahrten (Hbf)",
        "Train departures (main station)",
    ),
    DataType(
        "station-arrivals",
        "station_arrivals",
        "Bahn-Ankünfte (Hbf)",
        "Train arrivals (main station)",
    ),
    DataType("stations", "stations", "Bahnhöfe", "Railway stations"),
    DataType("traffic", "traffic", "Autobahn-Verkehr", "Motorway traffic"),
    DataType(
        "road-events",
        "road_events",
        "Innerstädtische Baustellen",
        "Inner-city roadworks",
    ),
    DataType("webcams", "webcams", "Verkehrs-Webcams", "Traffic webcams"),
    DataType("charging", "charging", "Ladesäulen", "EV charging stations"),
    DataType("fuel-prices", "fuel_prices", "Spritpreise", "Fuel prices"),
    DataType("sharing", "sharing", "Bike- & Scooter-Sharing", "Bike & scooter sharing"),
    DataType("pois", "pois", "Points of Interest", "Points of interest"),
    DataType("health", "health", "Krankenhäuser", "Hospitals"),
    DataType("icu-live", "icu_live", "Intensivbetten (live)", "ICU beds (live)"),
    DataType("water-level", "water_level", "Pegelstände", "Water levels"),
    DataType("flood", "flood", "Hochwasserwarnungen", "Flood warnings"),
    DataType("geo", "geo", "Geodaten & Grenzen", "Geodata & boundaries"),
    DataType("demographics", "demographics", "Demografie", "Demographics"),
    DataType(
        "indicators",
        "indicators",
        "Sozioökonomische Indikatoren",
        "Socioeconomic indicators",
    ),
    DataType("unemployment", "unemployment", "Arbeitslosigkeit", "Unemployment"),
    DataType(
        "tourism", "tourism", "Tourismus (Übernachtungen)", "Tourism (overnight stays)"
    ),
    DataType("construction", "construction", "Baugenehmigungen", "Building permits"),
    DataType("accidents", "accidents", "Verkehrsunfälle", "Road accidents"),
    DataType(
        "vehicle-registrations",
        "vehicle_registrations",
        "Kfz-Bestand",
        "Vehicle registrations",
    ),
    DataType("election", "election", "Wahlergebnisse", "Election results"),
    DataType("holidays", "holidays", "Feiertage", "Public holidays"),
    DataType("energy", "energy", "Energieanlagen", "Energy installations"),
    DataType("power-load", "power_load", "Netzlast (Strom)", "Grid load (electricity)"),
    DataType(
        "power-price", "power_price", "Strom-Börsenpreis", "Day-ahead power price"
    ),
    DataType(
        "solar", "solar", "Solar-Einstrahlung & Ertrag", "Solar irradiation & yield"
    ),
    DataType(
        "solar-roofs", "solar_roofs", "Dach-Solarkataster", "Rooftop solar cadastre"
    ),
    DataType("land-values", "land_values", "Bodenrichtwerte", "Land values"),
    DataType(
        "tax-rates", "tax_rates", "Realsteuer-Hebesätze", "Property & trade tax rates"
    ),
    DataType(
        "business-registrations",
        "business_registrations",
        "Gewerbe-An- & Abmeldungen",
        "Business registrations",
    ),
    DataType("events", "events", "Veranstaltungen", "Public events"),
    # DATA-OSM (Tier 1): dedizierte OSM-Overpass-Datenarten (ODbL, Tier B).
    DataType("playgrounds", "playgrounds", "Spielplätze", "Playgrounds"),
    DataType(
        "drinking-water",
        "drinking_water",
        "Trinkwasserbrunnen",
        "Drinking water fountains",
    ),
    DataType("markets", "markets", "Wochenmärkte", "Markets"),
    DataType("parcel-lockers", "parcel_lockers", "Paketstationen", "Parcel lockers"),
    DataType("post-offices", "post_offices", "Postfilialen", "Post offices"),
    DataType("post-boxes", "post_boxes", "Briefkästen", "Post boxes"),
    DataType("public-wifi", "public_wifi", "Öffentliches WLAN", "Public Wi-Fi"),
    DataType(
        "recycling-centres",
        "recycling_centres",
        "Recyclinghöfe",
        "Recycling centres",
    ),
    DataType(
        "government-offices",
        "government_offices",
        "Behörden & Ämter",
        "Government offices",
    ),
    DataType("education", "education", "Bildungseinrichtungen", "Education facilities"),
    # DATA-OSM-Tier-2: Denkmallisten je Bundesland (Land-WFS, coverage-gated).
    DataType("heritage", "heritage", "Denkmäler", "Heritage monuments"),
    # DATA-OSM-Tier-2: Baumkataster je Stadt (kommunaler WFS, coverage-gated).
    DataType("tree-cadastre", "tree_cadastre", "Baumkataster", "Tree cadastre"),
    # DATA-OSM-Tier-2: Einwohnerdichte aus dem Zensus-2022-100m-Gitter (alle Städte).
    DataType(
        "population-density",
        "population_density",
        "Einwohnerdichte",
        "Population density",
    ),
    # TENDER-01/05: oeffentliche Auftragsvergabe (oeffentlichevergabe.de, CC0 = Tier A).
    # key/tool ASCII (Pfadsegment + MCP-Tool), Label mit korrektem Umlaut.
    DataType(
        "public-tenders",
        "public_tenders",
        "Öffentliche Auftragsvergabe",
        "Public procurement",
    ),
    # DATA-40: kommunale Radzaehl-Open-Data je Stadt (Dauerzaehlstellen, Tier A,
    # Teilabdeckung muenchen/leipzig/hamburg/berlin/stuttgart). key/tool ASCII,
    # Label mit korrektem Umlaut. NICHT das sharing-Tool (GBFS-Leihfahrzeuge).
    DataType(
        "bike-counts",
        "bike_counts",
        "Radzählstellen",
        "Bike counters",
    ),
)
