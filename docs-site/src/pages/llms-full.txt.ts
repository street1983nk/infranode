// llms-full.txt an der Build-Wurzel (DX-04, GEO). Volltext aller Endpunkte als
// zusammengefügtes Markdown, sodass ein LLM ohne Folgeklicks alles im Kontext
// hat: je Endpunkt Titel (METHOD path), summary/description, Parameter-Liste
// und ein Beispiel-curl. Single Source ist loadEndpoints() (openapi.yaml).
// Defensiv gegen fehlende Felder (Pitfall 5). ASCII in Code/URLs, Umlaute nur in
// Prosa, keine Em-Dashes, keine Emojis.
import type { APIRoute } from "astro";
import { getCollection } from "astro:content";
import type { Endpoint } from "../lib/openapi";
import { curlFor } from "../lib/codegen";

// Datenquelle ist die endpoints-Collection (gespeist aus loadEndpoints() in
// content.config.ts). Collection-Load läuft im Astro-Build-Kontext und ist
// robust gegen das Pfadproblem eines direkten loadEndpoints()-Aufrufs hier.

interface OpenApiParameter {
  name?: string;
  in?: string;
  required?: boolean;
  description?: string;
  schema?: { type?: string };
}

function asParam(value: unknown): OpenApiParameter {
  return value != null && typeof value === "object" ? (value as OpenApiParameter) : {};
}

// Rendert einen Endpunkt als Markdown-Block (ohne fenced code via Backtick-Var,
// damit die Quelldatei keine literalen Code-Fences enthält).
function renderEndpoint(endpoint: Endpoint): string {
  const fence = "```";
  const out: string[] = [];
  out.push(`## ${endpoint.method} ${endpoint.path}`);
  out.push("");
  if (endpoint.summary) {
    out.push(`**${endpoint.summary}**`);
    out.push("");
  }
  if (endpoint.description) {
    out.push(endpoint.description);
    out.push("");
  }

  const params = endpoint.parameters.map(asParam);
  if (params.length > 0) {
    out.push("### Parameter");
    out.push("");
    for (const p of params) {
      const name = p.name ?? "?";
      const where = p.in ?? "?";
      const type = p.schema?.type ?? "?";
      const req = p.required ? "Pflicht" : "optional";
      const desc = p.description ? ` , ${p.description}` : "";
      out.push(`- \`${name}\` (${where}, ${type}, ${req})${desc}`);
    }
    out.push("");
  }

  out.push("### Beispiel");
  out.push("");
  out.push(`${fence}bash`);
  out.push(curlFor(endpoint));
  out.push(fence);
  out.push("");
  return out.join("\n");
}

export const GET: APIRoute = async () => {
  const collection = await getCollection("endpoints");
  const endpoints: Endpoint[] = collection.map((entry) => entry.data as Endpoint);

  // Nach tag gruppieren, je Gruppe nach id sortieren (stabile Reihenfolge).
  const groups = new Map<string, Endpoint[]>();
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
  lines.push("# InfraNode API | Vollständige Endpunkt-Referenz");
  lines.push("");
  lines.push(
    "> Volltext aller Endpunkte der InfraNode API in einem Dokument. " +
      "Normalisierte Open-Data-Proxy-API für deutsche Großstädte (84 Städte, " +
      "28 Kern-Städte voll abgedeckt; Stammdaten, Luftqualität, Wetter und " +
      "Wetterwarnungen, ÖPNV inkl. Echtzeit, Verkehr, Energie und Strommarkt, " +
      "Pkw-Bestand und Elektro-Anteil, Arbeitslosenquote, Tourismus, " +
      "Baugenehmigungen, Verkehrsunfälle, POIs). Kanonischer Envelope mit data " +
      "und meta auf Top-Level " +
      "(source_status, correlation_id und cache_status in meta); jeder " +
      "data-Record trägt zusätzlich ein attribution-Feld mit Lizenz und Herkunft.",
  );
  lines.push("");

  for (const tag of sortedTags) {
    lines.push(`# ${tag}`);
    lines.push("");
    for (const endpoint of groups.get(tag)!) {
      lines.push(renderEndpoint(endpoint));
    }
  }

  return new Response(lines.join("\n"), {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
};
