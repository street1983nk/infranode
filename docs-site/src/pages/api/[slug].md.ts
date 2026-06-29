// Statische .md-Variante je Endpunkt (DX-04, "Copy page as Markdown"-Quelle).
// getStaticPaths baut je OpenAPI-Operation eine Route (params.slug =
// operationId), die GET-Funktion gibt eine reine Markdown-Repräsentation
// (Titel, summary/description, Parameter-Liste, Beispiel-curl) als
// text/markdown zurück. Single Source ist loadEndpoints() (openapi.yaml).
// Defensiv gegen fehlende Felder (Pitfall 5). ASCII in Code/URLs, Umlaute nur in
// Prosa, keine Em-Dashes, keine Emojis.
import type { APIRoute, GetStaticPaths } from "astro";
import { getCollection } from "astro:content";
import type { Endpoint } from "../../lib/openapi";
import { curlFor } from "../../lib/codegen";

// Datenquelle ist die endpoints-Collection (gespeist aus loadEndpoints() in
// content.config.ts). getCollection läuft im Astro-Build-Kontext und vermeidet
// das Pfadproblem eines direkten loadEndpoints()-Aufrufs im prerenderten Chunk.

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

export const getStaticPaths: GetStaticPaths = async () => {
  const collection = await getCollection("endpoints");
  return collection.map((entry) => ({
    params: { slug: entry.data.id },
    props: { endpoint: entry.data as Endpoint },
  }));
};

function renderMarkdown(endpoint: Endpoint): string {
  const fence = "```";
  const out: string[] = [];
  out.push(`# ${endpoint.method} ${endpoint.path}`);
  out.push("");
  if (endpoint.summary) {
    out.push(`**${endpoint.summary}**`);
    out.push("");
  }
  if (endpoint.description) {
    out.push(endpoint.description);
    out.push("");
  }

  out.push("## Parameter");
  out.push("");
  const params = endpoint.parameters.map(asParam);
  if (params.length > 0) {
    for (const p of params) {
      const name = p.name ?? "?";
      const where = p.in ?? "?";
      const type = p.schema?.type ?? "?";
      const req = p.required ? "Pflicht" : "optional";
      const desc = p.description ? ` , ${p.description}` : "";
      out.push(`- \`${name}\` (${where}, ${type}, ${req})${desc}`);
    }
  } else {
    out.push("Dieser Endpunkt nimmt keine Parameter.");
  }
  out.push("");

  out.push("## Beispiel");
  out.push("");
  out.push(`${fence}bash`);
  out.push(curlFor(endpoint));
  out.push(fence);
  out.push("");
  return out.join("\n");
}

export const GET: APIRoute = ({ props }) => {
  const endpoint = props.endpoint as Endpoint;
  return new Response(renderMarkdown(endpoint), {
    headers: { "Content-Type": "text/markdown; charset=utf-8" },
  });
};
