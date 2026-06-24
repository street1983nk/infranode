// Liefert die kuratierte OpenAPI-Spec an der Build-Wurzel aus:
// https://infranode.dev/openapi.yaml. Single Source ist docs/openapi.yaml; sie
// wird per Vite ?raw-Import zur Build-Zeit eingebettet (robust gegen das
// Bundle-Pfadproblem eines Laufzeit-readFileSync). Stabile, offizielle Spec-URL
// fuer API-Verzeichnisse (APIs.guru), Codegen, Postman/Swagger.
import type { APIRoute } from "astro";
// @ts-expect-error - Vite ?raw-Import liefert den Dateiinhalt als String.
import specYaml from "../../../docs/openapi.yaml?raw";

export const prerender = true;

export const GET: APIRoute = () =>
  new Response(specYaml as string, {
    headers: {
      "Content-Type": "application/yaml; charset=utf-8",
      "Cache-Control": "public, max-age=3600",
    },
  });
