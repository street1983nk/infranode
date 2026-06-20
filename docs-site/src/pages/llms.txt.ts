// llms.txt an der Build-Wurzel (DX-04, GEO). Format strikt nach llmstxt.org:
// H1 (Projektname) -> Blockquote-Summary -> H2-Sektionen je tag mit
// Markdown-Linklisten ("- [METHOD path](<url>): summary"). Single Source ist
// loadEndpoints() (openapi.yaml). Astro-Endpoint: export GET -> Response
// (text/plain). Defensiv gegen fehlende Felder (Pitfall 5). ASCII in Code/URLs,
// Umlaute nur in Prosa, keine Em-Dashes, keine Emojis.
import type { APIRoute } from "astro";
import { getCollection } from "astro:content";
import type { Endpoint } from "../lib/openapi";
import { topics } from "../data/topics";
import { mcpTopics } from "../data/mcp-topics";

// Datenquelle ist die endpoints-Collection (gespeist aus loadEndpoints() in
// content.config.ts, Single Source openapi.yaml). Die Collection wird im
// Astro-Build-Kontext geladen, daher robust gegen das Cwd-/Bundle-Pfadproblem
// eines direkten loadEndpoints()-Aufrufs in der prerenderten Route.

// Absolute Doku-Domain. Astro.site stammt aus astro.config.mjs (Env
// INFRANODE_DOCS_SITE), Fallback ist die oeffentliche Domain infranode.dev.
function siteBase(site: URL | undefined): string {
  return (site?.toString() ?? "https://infranode.dev").replace(/\/$/, "");
}

export const GET: APIRoute = async ({ site }) => {
  const base = siteBase(site);
  const collection = await getCollection("endpoints");
  const endpoints: Endpoint[] = collection.map((entry) => entry.data as Endpoint);

  // Nach tag gruppieren, je Gruppe nach id sortieren (stabile Reihenfolge).
  const groups = new Map<string, typeof endpoints>();
  for (const endpoint of endpoints) {
    const tag = endpoint.tag || "meta";
    if (!groups.has(tag)) groups.set(tag, []);
    groups.get(tag)!.push(endpoint);
  }
  for (const list of groups.values()) {
    list.sort((a, b) => a.id.localeCompare(b.id));
  }
  const sortedTags = [...groups.keys()].sort();

  const lines: string[] = [];
  lines.push("# InfraNode API");
  lines.push("");
  lines.push(
    "> Eine kostenlose, öffentliche Open-Data-Proxy-REST-API, die fragmentierte " +
      "offene Daten deutscher Großstädte (84 Städte über 100.000 Einwohner, davon " +
      "28 Kern-Städte voll abgedeckt) hinter einer einheitlichen, " +
      "normalisierten JSON-Schnittstelle bündelt (Stammdaten, Luftqualität, " +
      "Wetter und Wetterwarnungen, ÖPNV inkl. Echtzeit-Abfahrten, Verkehr, " +
      "Ladesäulen, Energie und Strommarkt, Pkw-Bestand und Elektro-Anteil, " +
      "Arbeitslosenquote, Tourismus, Baugenehmigungen, Verkehrsunfälle, POIs). " +
      "Alle permissiv lizenziert (Tier A, kommerziell nutzbar). " +
      "Jede Antwort folgt dem kanonischen " +
      "Envelope mit data und meta auf Top-Level (source_status, correlation_id " +
      "und cache_status liegen in meta); jeder data-Record trägt zusätzlich ein " +
      "attribution-Feld mit Lizenz und Herkunft.",
  );
  lines.push("");
  lines.push(
    "Diese Datei listet alle Endpunkte mit Links zu ihrer Doku im Markdown-" +
      "Format. Je Endpunkt-Seite existiert eine .md-Variante unter " +
      `${base}/api/<operationId>.md für den direkten Maschinen-Konsum.`,
  );
  lines.push("");

  // Kern-Seiten (Doku, MCP, Ueber) zuerst, damit Agenten Einstieg und Kontext
  // finden, gefolgt von der englischen Fassung der Kernseiten.
  lines.push("## Seiten");
  lines.push("");
  lines.push(`- [Quick-Start](${base}/quickstart/): In drei Schritten zum ersten Aufruf, ohne Schlüssel.`);
  lines.push(`- [Städte](${base}/staedte/): Durchsuchbare Liste aller 84 abgedeckten Großstädte mit Slug, Bundesland, Einwohnern und Abdeckung.`);
  lines.push(`- [Daten-API](${base}/daten/): Daten-API und Datenanalyse-API für deutsche Städte, Hub über alle Datenarten, Datensatz (CSV/Parquet) und MCP-Zugang.`);
  lines.push(`- [Abdeckung & Status](${base}/abdeckung/): Welche Endpunkte für welche Städte Daten liefern (flächendeckend vs. teilabgedeckt: flood, webcams, traffic, road-events), source_status-Werte inkl. not_covered, Live-Status-Page für Störungen.`);
  lines.push(`- [MCP-Server](${base}/mcp/): Gehosteter MCP-Server unter https://mcp.infranode.dev/mcp (Remote, Streamable HTTP, keylos) mit 44 Tools inkl. Echtzeit-Abfahrten, Städte- und Quellenübersicht. Als Connector in Claude/ChatGPT verbinden, keine Installation.`);
  lines.push(`- [Über](${base}/ueber/): Hintergrund zum Projekt, kostenlose Open-Data-API (Quellcode öffentlich auf GitHub, Apache-2.0), Betrieb in Deutschland, Kontakt.`);
  lines.push(`- [Impressum](${base}/impressum/): Anbieterangaben nach DDG.`);
  lines.push(`- [Datenschutz](${base}/datenschutz/): Keine Cookies, kein Tracking, DSGVO-Rechte.`);
  lines.push("");
  lines.push("## English");
  lines.push("");
  lines.push(`- [Home](${base}/en/): Free, public open-data API for German cities.`);
  lines.push(`- [Quickstart](${base}/en/quickstart/): Your first call in three steps, no key.`);
  lines.push(`- [Cities](${base}/en/cities/): Searchable list of all 84 covered cities with slug, state, population and coverage.`);
  lines.push(`- [Data API](${base}/en/data/): Data API and data analysis API for German cities, hub over all data types, dataset (CSV/Parquet) and MCP access.`);
  lines.push(`- [Coverage & status](${base}/en/coverage/): Which endpoints serve which cities (fully vs. partially covered: flood, webcams, traffic, road-events), source_status values incl. not_covered, live status page for outages.`);
  lines.push(`- [MCP server](${base}/en/mcp/): Hosted MCP server at https://mcp.infranode.dev/mcp (remote, Streamable HTTP, key-free) with 44 tools incl. live departures, cities and sources overview. Add as a connector in Claude/ChatGPT, no install.`);
  lines.push(`- [About](${base}/en/about/): Background, free open-data API (source code on GitHub, Apache-2.0), contact.`);
  lines.push("");

  // Per-Datentyp-Landingpages (REST), DE+EN. Keyword-Einstieg je Datenachse.
  lines.push("## Daten nach Thema / Data by topic");
  lines.push("");
  for (const topic of topics) {
    lines.push(`- [${topic.de.h1}](${base}/daten/${topic.de.slug}/): ${topic.de.lead}`);
  }
  for (const topic of topics) {
    lines.push(`- [${topic.en.h1}](${base}/en/data/${topic.en.slug}/): ${topic.en.lead}`);
  }
  lines.push("");

  // Per-Datentyp-MCP-Landingpages (KI-Agenten), DE+EN.
  lines.push("## MCP-Server nach Thema / MCP by topic");
  lines.push("");
  for (const topic of mcpTopics) {
    lines.push(`- [${topic.de.h1}](${base}/mcp/${topic.de.slug}/): ${topic.de.lead}`);
  }
  for (const topic of mcpTopics) {
    lines.push(`- [${topic.en.h1}](${base}/en/mcp/${topic.en.slug}/): ${topic.en.lead}`);
  }
  lines.push("");

  // Tutorials / Ratgeber (informationell, GEO).
  lines.push("## Tutorials");
  lines.push("");
  lines.push(`- [Was ist ein MCP-Server? Einfach erklärt](${base}/tutorials/was-ist-ein-mcp-server/): MCP und Model Context Protocol verständlich erklärt, mit kostenlosem Beispiel für offene Daten deutscher Städte.`);
  lines.push(`- [MCP-Server in Claude und ChatGPT einrichten](${base}/tutorials/mcp-server-claude-einrichten/): Den kostenlosen, keylosen InfraNode-MCP-Server in Claude Code, Claude Desktop und ChatGPT einrichten.`);
  lines.push(`- [Offene Stadtdaten in Home Assistant einbinden](${base}/tutorials/home-assistant-stadtdaten/): Wetter, Luftqualität und Strompreis als REST-Sensor in Home Assistant, ohne API-Schlüssel.`);
  lines.push(`- [Stadtdaten mit Python und pandas abrufen](${base}/tutorials/python-pandas-stadtdaten/): Offene Daten deutscher Großstädte mit requests und pandas über alle Städte auswerten.`);
  lines.push(`- [InfraNode mit Python: das infranode-Paket](${base}/tutorials/python-sdk/): Keyloses Python-Paket (PyPI: infranode), synchron und asynchron, plus LangChain- und LlamaIndex-Tools für KI-Agenten.`);
  lines.push(`- [InfraNode mit JavaScript: infranode-sdk](${base}/tutorials/javascript-sdk/): Keyloses TypeScript-Paket (npm: infranode-sdk) für Node und Browser, mit Vercel-AI-SDK-Tool und Cursor-Starter-Template.`);
  lines.push(`- [What is an MCP server? Simply explained](${base}/en/tutorials/what-is-an-mcp-server/): Model Context Protocol explained, with a free open-data example for German cities.`);
  lines.push(`- [Set up an MCP server in Claude and ChatGPT](${base}/en/tutorials/set-up-mcp-server-claude/): Set up the free, keyless InfraNode MCP server in Claude and ChatGPT.`);
  lines.push(`- [InfraNode with Python: the infranode package](${base}/en/tutorials/python-sdk/): Keyless Python package (PyPI: infranode), sync and async, with LangChain and LlamaIndex tools for AI agents.`);
  lines.push(`- [InfraNode with JavaScript: infranode-sdk](${base}/en/tutorials/javascript-sdk/): Keyless TypeScript package (npm: infranode-sdk) for Node and the browser, with a Vercel AI SDK tool and a Cursor starter template.`);
  lines.push("");
  lines.push("## Libraries / SDKs");
  lines.push("");
  lines.push(`- [infranode (Python)](https://github.com/street1983nk/infranode-python): Keyless Python client + LangChain/LlamaIndex tools. pip install infranode.`);
  lines.push(`- [infranode-sdk (JavaScript/TypeScript)](https://github.com/street1983nk/infranode-js): Keyless TS client + Vercel AI SDK tool. npm install infranode-sdk.`);
  lines.push(`- [infranode-weather-starter](https://github.com/street1983nk/infranode-weather-starter): Ready-made React dashboard template with InfraNode MCP preconfigured for Cursor.`);
  lines.push("");

  for (const tag of sortedTags) {
    lines.push(`## ${tag}`);
    lines.push("");
    for (const endpoint of groups.get(tag)!) {
      const summary = endpoint.summary || endpoint.description || endpoint.id;
      const url = `${base}/api/${endpoint.id}.md`;
      lines.push(`- [${endpoint.method} ${endpoint.path}](${url}): ${summary}`);
    }
    lines.push("");
  }

  return new Response(lines.join("\n"), {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
};
