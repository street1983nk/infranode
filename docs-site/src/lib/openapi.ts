// openapi.yaml-Loader: liest docs/openapi.yaml und normalisiert jede
// Operation zu einem flachen Endpoint-Objekt. Bewusst defensiv (Pitfall 5):
// es werden NUR paths gelesen, $ref/oneOf werden NICHT aufgelöst, optionale
// Felder bekommen Defaults. Nachgelagerte Slices (SEO/GEO/Try-it) filtern
// über das Feld `kind`, statt erneut die Spec zu parsen.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { parse } from "yaml";

// docs/openapi.yaml liegt relativ zu dieser Datei unter ../../../docs/.
// Auflösen über import.meta.url, damit der Pfad unabhängig vom Cwd stimmt
// (Astro-Build-Cwd ist docs-site/, aber Content-Loader laufen aus .astro/).
const HERE = dirname(fileURLToPath(import.meta.url));
const SPEC_PATH = resolve(HERE, "..", "..", "..", "docs", "openapi.yaml");

// HTTP-Methoden, die als Operationen gelten (Path-Item-Keys).
const HTTP_METHODS = ["get", "put", "post", "delete", "patch", "options", "head", "trace"];

export interface Endpoint {
  id: string;
  path: string;
  method: string;
  tag: string;
  summary: string;
  description: string;
  // Englische Entsprechungen aus den OpenAPI-Extensions x-summary-en/
  // x-description-en. Fallback auf die deutschen Texte, falls nicht gepflegt.
  summaryEn: string;
  descriptionEn: string;
  parameters: unknown[];
  responses: Record<string, unknown>;
  kind: "city" | "meta";
}

// Klassifiziert eine Operation als datentragende Stadt-Ressource ("city")
// oder als Demo-/Betriebs-Operation ("meta"). Stadt = Pfad unter
// /cities/{slug}/... ODER die Listen-/Vergleichs-Operationen getCities,
// getSources, compareCities. Alles andere (Ping, Echo, _boom, Health,
// Openapi-Spec) ist meta.
function classifyKind(opPath: string, operationId: string): "city" | "meta" {
  const cityIds = new Set(["getCities", "getSources", "compareCities"]);
  if (cityIds.has(operationId)) {
    return "city";
  }
  if (/\/cities\/\{[^}]+\}\//.test(opPath)) {
    return "city";
  }
  return "meta";
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

export function loadEndpoints(): Endpoint[] {
  const raw = readFileSync(SPEC_PATH, "utf-8");
  const spec = parse(raw) as { paths?: Record<string, Record<string, unknown>> };
  const paths = spec?.paths ?? {};
  const endpoints: Endpoint[] = [];

  for (const [opPath, pathItem] of Object.entries(paths)) {
    if (pathItem == null || typeof pathItem !== "object") {
      continue;
    }
    for (const method of HTTP_METHODS) {
      const operation = (pathItem as Record<string, unknown>)[method];
      if (operation == null || typeof operation !== "object") {
        continue;
      }
      const op = operation as Record<string, unknown>;
      const tags = Array.isArray(op.tags) ? op.tags : [];
      const operationId = asString(op.operationId, `${method}_${opPath}`);
      // Parameter durchreichen und je Parameter eine englische Beschreibung
      // (x-description-en) als descriptionEn ergänzen, Fallback auf description.
      const parameters = (Array.isArray(op.parameters) ? op.parameters : []).map((p) => {
        if (p == null || typeof p !== "object") return p;
        const param = p as Record<string, unknown>;
        const de = asString(param.description);
        const en = asString(param["x-description-en"], de);
        return { ...param, descriptionEn: en };
      });
      const responses =
        op.responses != null && typeof op.responses === "object"
          ? (op.responses as Record<string, unknown>)
          : {};

      endpoints.push({
        id: operationId,
        path: opPath,
        method: method.toUpperCase(),
        tag: asString(tags[0], "meta"),
        summary: asString(op.summary),
        description: asString(op.description),
        summaryEn: asString(op["x-summary-en"], asString(op.summary)),
        descriptionEn: asString(op["x-description-en"], asString(op.description)),
        parameters,
        responses,
        kind: classifyKind(opPath, operationId),
      });
    }
  }

  return endpoints;
}
