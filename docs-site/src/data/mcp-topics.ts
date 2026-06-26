// Single Source fuer die MCP-Datennischen-Landingpages (SEO-Dominanz "MCP-Server
// Deutschland"). Jede Datenachse bekommt eine eigene Seite, die gezielt auf
// "{Datentyp} MCP-Server [Deutschland]" optimiert ist: was das MCP-Tool macht,
// wie man es in Claude/ChatGPT nutzt. DE+EN. Routen: src/pages/mcp/[topic].astro
// und src/pages/en/mcp/[topic].astro. Verweist auf die REST-Pendants
// (/daten/{slug}) und die MCP-Setup-Seite (/mcp/).

export interface McpFaq {
  q: string;
  a: string;
}

export interface McpTopicLang {
  slug: string;
  dataSlug: string; // Pendant unter /daten/ bzw. /en/data/
  metaTitle: string;
  h1: string;
  lead: string;
  what: string;
  examplePrompt: string;
  keywords: string[];
  faq: McpFaq[];
}

export interface McpTopic {
  id: string;
  tool: string; // MCP-Tool-Name
  de: McpTopicLang;
  en: McpTopicLang;
}

export const mcpTopics: McpTopic[] = [
  {
    id: "weather",
    tool: "weather",
    de: {
      slug: "wetter",
      dataSlug: "wetter-api",
      metaTitle: "Wetter-MCP-Server Deutschland (DWD) für Claude und ChatGPT",
      h1: "Wetter-MCP-Server für deutsche Städte (DWD)",
      lead: "Aktuelle Wetterdaten des Deutschen Wetterdienstes (DWD) für 84 deutsche Großstädte direkt in deinem KI-Assistenten, über das kostenlose, keylose MCP-Tool von InfraNode. Kein API-Schlüssel, keine Installation.",
      what: "Das MCP-Tool weather liefert die nächstgelegene DWD-Messung einer Stadt: Temperatur, Luftfeuchte, Windgeschwindigkeit und Wetterlage. Dein KI-Agent (Claude, ChatGPT u.a.) ruft es selbst auf, sobald du nach dem Wetter einer Stadt fragst.",
      examplePrompt: "Wie ist das Wetter gerade in Hamburg?",
      keywords: ["Wetter MCP Server", "DWD MCP Server", "MCP Server Wetter Deutschland", "Wetter Tool Claude", "MCP Wetterdaten"],
      faq: [
        { q: "Brauche ich für den Wetter-MCP-Server einen API-Schlüssel?", a: "Nein. Der InfraNode-MCP-Server ist keylos und kostenlos. Du verbindest ihn einmal mit Claude oder ChatGPT, danach ruft der Assistent das weather-Tool ohne Schlüssel auf." },
        { q: "Woher stammen die Wetterdaten?", a: "Vom Deutschen Wetterdienst (DWD), durchgereicht unter DL-DE BY 2.0. Quelle und Zeitstempel stehen in jeder Antwort." },
      ],
    },
    en: {
      slug: "weather",
      dataSlug: "weather-api",
      metaTitle: "Germany Weather MCP Server (DWD) for Claude and ChatGPT",
      h1: "Weather MCP server for German cities (DWD)",
      lead: "Current German Weather Service (DWD) data for 84 major German cities directly in your AI assistant, through InfraNode's free, keyless MCP tool. No API key, no install.",
      what: "The weather MCP tool returns the nearest DWD observation for a city: temperature, humidity, wind speed and condition. Your AI agent (Claude, ChatGPT and others) calls it automatically when you ask about a city's weather.",
      examplePrompt: "What is the weather in Hamburg right now?",
      keywords: ["weather MCP server", "DWD MCP server", "Germany weather MCP", "weather tool Claude", "MCP weather data"],
      faq: [
        { q: "Do I need an API key for the weather MCP server?", a: "No. The InfraNode MCP server is keyless and free. You connect it once to Claude or ChatGPT, then the assistant calls the weather tool without a key." },
        { q: "Where does the weather data come from?", a: "From the German Weather Service (DWD), passed through under DL-DE BY 2.0. Source and timestamp are in every response." },
      ],
    },
  },
  {
    id: "air-quality",
    tool: "air_quality",
    de: {
      slug: "luftqualitaet",
      dataSlug: "luftqualitaet-api",
      metaTitle: "Luftqualitäts-MCP-Server Deutschland (UBA) für KI-Agenten",
      h1: "Luftqualitäts-MCP-Server für deutsche Städte (UBA)",
      lead: "Aktuelle Luftqualitätsdaten des Umweltbundesamts (UBA) für deutsche Großstädte direkt in Claude oder ChatGPT, über das kostenlose, keylose MCP-Tool von InfraNode.",
      what: "Das MCP-Tool air_quality liefert die Messwerte der nächstgelegenen UBA-Station: Feinstaub PM10 und PM2.5, Stickstoffdioxid NO2, Ozon O3 und Schwefeldioxid SO2. Der KI-Agent ruft es auf, wenn du nach der Luftqualität einer Stadt fragst.",
      examplePrompt: "Wie ist die Luftqualität heute in München?",
      keywords: ["Luftqualität MCP Server", "UBA MCP Server", "Feinstaub MCP", "MCP Server Luftqualität Deutschland", "Air Quality MCP"],
      faq: [
        { q: "Ist der Luftqualitäts-MCP-Server kostenlos?", a: "Ja, kostenlos und keylos. Einmal mit dem KI-Client verbinden, dann ruft er das air_quality-Tool ohne Schlüssel auf." },
        { q: "Welche Werte liefert das Tool?", a: "PM10, PM2.5, NO2, O3 und SO2 aus dem Messnetz des Umweltbundesamts, mit Messzeitpunkt und Stationsbezug." },
      ],
    },
    en: {
      slug: "air-quality",
      dataSlug: "air-quality-api",
      metaTitle: "Germany Air Quality MCP Server (UBA) for AI agents",
      h1: "Air quality MCP server for German cities (UBA)",
      lead: "Current German Environment Agency (UBA) air quality data for major German cities directly in Claude or ChatGPT, through InfraNode's free, keyless MCP tool.",
      what: "The air_quality MCP tool returns readings from the nearest UBA station: PM10 and PM2.5, NO2, O3 and SO2. The AI agent calls it when you ask about a city's air quality.",
      examplePrompt: "How is the air quality in Munich today?",
      keywords: ["air quality MCP server", "UBA MCP server", "particulate matter MCP", "Germany air quality MCP", "air quality MCP tool"],
      faq: [
        { q: "Is the air quality MCP server free?", a: "Yes, free and keyless. Connect it once to your AI client, then it calls the air_quality tool without a key." },
        { q: "Which values does the tool return?", a: "PM10, PM2.5, NO2, O3 and SO2 from the German Environment Agency network, with measurement time and station reference." },
      ],
    },
  },
  {
    id: "electricity-price",
    tool: "power_price",
    de: {
      slug: "strompreis",
      dataSlug: "strompreis-api",
      metaTitle: "Strompreis-MCP-Server Deutschland (SMARD) für Claude",
      h1: "Strompreis-MCP-Server für Deutschland (SMARD)",
      lead: "Der bundesweite Day-Ahead-Börsenstrompreis (SMARD, Bundesnetzagentur) direkt in deinem KI-Assistenten, über das kostenlose, keylose MCP-Tool von InfraNode.",
      what: "Das MCP-Tool power_price liefert den deutschlandweiten Day-Ahead-Börsenstrompreis als Tageswert. Frag deinen KI-Agenten nach dem Strompreis, und er ruft das Tool selbst auf, etwa um den günstigsten Ladezeitpunkt zu finden.",
      examplePrompt: "Wie hoch ist heute der Börsenstrompreis in Deutschland?",
      keywords: ["Strompreis MCP Server", "SMARD MCP Server", "Börsenstrompreis MCP", "MCP Server Strompreis", "Energie MCP Deutschland"],
      faq: [
        { q: "Ist der Strompreis pro Stadt unterschiedlich?", a: "Nein, der Day-Ahead-Börsenstrompreis gilt bundesweit. Du fragst ihn bequem über jede Stadt ab, der Wert ist derselbe." },
        { q: "Kostet der Strompreis-MCP-Server etwas?", a: "Nein, kostenlos und keylos. Im Gegensatz zu vielen Energie-APIs ohne Anmeldung oder Abo nutzbar." },
      ],
    },
    en: {
      slug: "electricity-price",
      dataSlug: "electricity-price-api",
      metaTitle: "Germany Electricity Price MCP Server (SMARD) for Claude",
      h1: "Electricity price MCP server for Germany (SMARD)",
      lead: "The nationwide day-ahead spot electricity price (SMARD, Federal Network Agency) directly in your AI assistant, through InfraNode's free, keyless MCP tool.",
      what: "The power_price MCP tool returns the Germany-wide day-ahead spot electricity price as a daily value. Ask your AI agent about the price and it calls the tool itself, for example to find the cheapest charging time.",
      examplePrompt: "What is today's spot electricity price in Germany?",
      keywords: ["electricity price MCP server", "SMARD MCP server", "spot price MCP", "Germany energy MCP", "power price MCP tool"],
      faq: [
        { q: "Does the electricity price differ per city?", a: "No, the day-ahead spot price is nationwide. You query it conveniently via any city, the value is the same." },
        { q: "Does the electricity price MCP server cost anything?", a: "No, free and keyless. Unlike many energy APIs, usable without sign-up or subscription." },
      ],
    },
  },
  {
    id: "land-values",
    tool: "land_values",
    de: {
      slug: "bodenrichtwerte",
      dataSlug: "bodenrichtwerte-api",
      metaTitle: "Bodenrichtwerte-MCP-Server Deutschland (BORIS) für KI",
      h1: "Bodenrichtwerte-MCP-Server für deutsche Städte (BORIS)",
      lead: "Amtliche Bodenrichtwerte (BORIS) je Stadt direkt in Claude oder ChatGPT, über das kostenlose, keylose MCP-Tool von InfraNode.",
      what: "Das MCP-Tool land_values liefert eine Bauland-Kennzahl je Stadt: Median, Minimum und Maximum der Bodenrichtwerte in EUR pro Quadratmeter sowie den Stichtag. Der KI-Agent ruft es auf, wenn du nach Grundstückspreisen einer Stadt fragst.",
      examplePrompt: "Was ist der Bodenrichtwert in Köln?",
      keywords: ["Bodenrichtwerte MCP Server", "BORIS MCP Server", "Grundstückspreise MCP", "MCP Server Immobilien Deutschland", "land values MCP"],
      faq: [
        { q: "Welche Städte deckt das Tool ab?", a: "Alle Städte, deren Bundesland einen offenen BORIS-Dienst bereitstellt. Wo das fehlt, antwortet das Tool ehrlich mit not_covered." },
        { q: "Ist der Bodenrichtwerte-MCP-Server kostenlos?", a: "Ja, kostenlos und keylos, ohne Anmeldung." },
      ],
    },
    en: {
      slug: "land-values",
      dataSlug: "land-values-api",
      metaTitle: "Germany Land Values MCP Server (BORIS) for AI",
      h1: "Land values MCP server for German cities (BORIS)",
      lead: "Official standard land values (BORIS) per city directly in Claude or ChatGPT, through InfraNode's free, keyless MCP tool.",
      what: "The land_values MCP tool returns a building-land metric per city: median, minimum and maximum standard land value in EUR per square meter plus the reference date. The AI agent calls it when you ask about a city's property prices.",
      examplePrompt: "What is the standard land value in Cologne?",
      keywords: ["land values MCP server", "BORIS MCP server", "property prices MCP", "Germany real estate MCP", "land value MCP tool"],
      faq: [
        { q: "Which cities does the tool cover?", a: "All cities whose federal state provides an open BORIS service. Where it is missing, the tool answers honestly with not_covered." },
        { q: "Is the land values MCP server free?", a: "Yes, free and keyless, without sign-up." },
      ],
    },
  },
  {
    id: "public-transport",
    tool: "station_departures",
    de: {
      slug: "oepnv",
      dataSlug: "oepnv-echtzeit-api",
      metaTitle: "ÖPNV-MCP-Server Deutschland: Echtzeit-Abfahrten für KI",
      h1: "ÖPNV-MCP-Server für deutsche Städte",
      lead: "Echtzeit-Abfahrten an Haltestellen deutscher Großstädte direkt in deinem KI-Assistenten, über das kostenlose, keylose MCP-Tool von InfraNode (DELFI, GTFS, Verkehrsverbünde).",
      what: "Das MCP-Tool station_departures liefert die nächsten Abfahrten an einer zentralen Haltestelle: Linie, Richtung, geplante und prognostizierte Abfahrtszeit, Verspätung. Der KI-Agent ruft es auf, wenn du nach Abfahrten in einer Stadt fragst.",
      examplePrompt: "Wann fahren die nächsten Bahnen in Hamburg?",
      keywords: ["ÖPNV MCP Server", "Abfahrten MCP", "GTFS MCP Server", "MCP Server ÖPNV Deutschland", "public transport MCP"],
      faq: [
        { q: "Welche Verkehrsdaten liefert das Tool?", a: "Echtzeit-Abfahrten mit Linie, Richtung, geplanter und prognostizierter Zeit sowie Verspätung, aus DELFI, GTFS und regionalen Verbünden." },
        { q: "Ist der ÖPNV-MCP-Server kostenlos?", a: "Ja, kostenlos und keylos, ohne Anmeldung." },
      ],
    },
    en: {
      slug: "public-transport",
      dataSlug: "public-transport-api",
      metaTitle: "Germany Public Transport MCP Server: real-time departures",
      h1: "Public transport MCP server for German cities",
      lead: "Real-time departures at stops in major German cities directly in your AI assistant, through InfraNode's free, keyless MCP tool (DELFI, GTFS, transit associations).",
      what: "The station_departures MCP tool returns the next departures at a central stop: line, direction, planned and predicted departure time and delay. The AI agent calls it when you ask about departures in a city.",
      examplePrompt: "When do the next trains leave in Hamburg?",
      keywords: ["public transport MCP server", "departures MCP", "GTFS MCP server", "Germany transit MCP", "real-time transit MCP"],
      faq: [
        { q: "Which transit data does the tool return?", a: "Real-time departures with line, direction, planned and predicted time and delay, from DELFI, GTFS and regional associations." },
        { q: "Is the public transport MCP server free?", a: "Yes, free and keyless, without sign-up." },
      ],
    },
  },
];
