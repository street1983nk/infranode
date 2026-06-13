// Code-Snippet-Generatoren je OpenAPI-Operation (D-03). Aus einem Endpoint
// (siehe ./openapi.ts) werden curl-, fetch- und httpx-Snippets erzeugt, die
// alle dieselbe Live-API-URL treffen. Method-aware (Blocker 3): GET ist
// Default, POST-Operationen erhalten -X POST / method:'POST' /
// httpx.post. Keine Build-Time-Calls der Live-API: hier werden
// nur Strings gebaut, nie ein Request abgesetzt.
import type { Endpoint } from "./openapi";

// Basis-URL der Live-API fuer die Snippets. Kommt aus der Env, sodass die
// Try-it-Konsole weiterhin lokal/konfigurierbar bleibt; das Produktions-
// Beispiel zeigt die oeffentliche Domain. ASCII-only (CLAUDE.md: Code/URLs).
export const API_BASE: string =
  (typeof process !== "undefined" && process.env?.INFRANODE_DOCS_API_BASE) ||
  "https://infranode.dev";

// Beispiel-Stadt-Slug fuer {slug}-Pfadparameter (registrierte Stadt).
const SLUG_EXAMPLE = "hamburg";

// OpenAPI-Parameter-Form, soweit wir sie defensiv brauchen. Der Loader liefert
// parameters als unknown[]; wir lesen nur name/in/required/schema/example.
interface OpenApiParameter {
  name?: string;
  in?: string;
  required?: boolean;
  example?: unknown;
  schema?: { type?: string; enum?: unknown[]; default?: unknown; example?: unknown };
}

function asParam(value: unknown): OpenApiParameter {
  return value != null && typeof value === "object" ? (value as OpenApiParameter) : {};
}

// Liefert einen Beispielwert fuer einen Parameter. Reihenfolge: expliziter
// example -> schema.example -> schema.default -> erster enum-Wert -> typbasiert.
// Spezialfall slug -> hamburg. Alles ASCII.
function exampleFor(param: OpenApiParameter): string {
  if (param.name === "slug") {
    return SLUG_EXAMPLE;
  }
  if (typeof param.example === "string" || typeof param.example === "number") {
    return String(param.example);
  }
  const schema = param.schema ?? {};
  if (typeof schema.example === "string" || typeof schema.example === "number") {
    return String(schema.example);
  }
  if (typeof schema.default === "string" || typeof schema.default === "number") {
    return String(schema.default);
  }
  if (Array.isArray(schema.enum) && schema.enum.length > 0) {
    return String(schema.enum[0]);
  }
  if (schema.type === "integer" || schema.type === "number") {
    return "1";
  }
  // Generischer Fallback fuer freie String-Parameter (z.B. POI type).
  return "example";
}

// Ersetzt alle {param}-Platzhalter im Pfad durch Beispielwerte aus parameters
// (NICHT nur {slug}). Unbekannte Platzhalter fallen auf "example" zurueck.
function resolvePath(endpoint: Endpoint): string {
  const params = endpoint.parameters.map(asParam);
  return endpoint.path.replace(/\{([^}]+)\}/g, (_match, rawName: string) => {
    const name = rawName;
    const param = params.find((p) => p.in === "path" && p.name === name);
    if (param) {
      return exampleFor(param);
    }
    return name === "slug" ? SLUG_EXAMPLE : "example";
  });
}

// Liefert die required Query-Parameter (in: query, required: true) mit
// Beispielwerten als [name, value]-Paare.
function requiredQuery(endpoint: Endpoint): Array<[string, string]> {
  return endpoint.parameters
    .map(asParam)
    .filter((p) => p.in === "query" && p.required === true && typeof p.name === "string")
    .map((p) => [p.name as string, exampleFor(p)] as [string, string]);
}

// Baut die vollstaendige Beispiel-URL inkl. required Query-String.
export function urlFor(endpoint: Endpoint): string {
  const path = resolvePath(endpoint);
  const query = requiredQuery(endpoint);
  const base = `${API_BASE}${path}`;
  if (query.length === 0) {
    return base;
  }
  const qs = query.map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join("&");
  return `${base}?${qs}`;
}

// curl-Snippet. Method-aware: POST/PUT/PATCH/DELETE setzen -X <METHOD>.
export function curlFor(endpoint: Endpoint): string {
  const url = urlFor(endpoint);
  const method = endpoint.method.toUpperCase();
  const lines: string[] = [];
  if (method === "GET") {
    lines.push(`curl "${url}"`);
  } else {
    lines.push(`curl -X ${method} "${url}" \\`);
    lines.push(`  -H "Content-Type: application/json"`);
  }
  return lines.join("\n");
}

// fetch-Snippet (JS). Method-aware via method-Property.
export function jsFor(endpoint: Endpoint): string {
  const url = urlFor(endpoint);
  const method = endpoint.method.toUpperCase();
  if (method === "GET") {
    return [
      `const res = await fetch("${url}");`,
      `const data = await res.json();`,
      `console.log(data);`,
    ].join("\n");
  }
  return [
    `const res = await fetch("${url}", {`,
    `  method: "${method}",`,
    `  headers: { "Content-Type": "application/json" },`,
    `});`,
    `const data = await res.json();`,
    `console.log(data);`,
  ].join("\n");
}

// httpx-Snippet (Python). Method-aware via httpx.<method>.
export function pyFor(endpoint: Endpoint): string {
  const url = urlFor(endpoint);
  const method = endpoint.method.toLowerCase();
  const call = method === "get" ? "httpx.get" : `httpx.${method}`;
  return [
    `import httpx`,
    ``,
    `res = ${call}("${url}")`,
    `res.raise_for_status()`,
    `print(res.json())`,
  ].join("\n");
}
