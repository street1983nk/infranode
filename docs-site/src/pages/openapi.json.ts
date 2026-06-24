// Liefert die kuratierte OpenAPI-Spec als JSON aus:
// https://infranode.dev/openapi.json. Single Source ist docs/openapi.yaml (per
// Vite ?raw-Import eingebettet), hier YAML -> JSON geparst. Viele Tools (Swagger
// UI, Postman, Codegen) erwarten JSON. Stabile, offizielle Spec-URL.
import type { APIRoute } from "astro";
import { parse } from "yaml";
// @ts-expect-error - Vite ?raw-Import liefert den Dateiinhalt als String.
import specYaml from "../../../docs/openapi.yaml?raw";

export const prerender = true;

export const GET: APIRoute = () =>
  new Response(JSON.stringify(parse(specYaml as string), null, 2), {
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "public, max-age=3600",
    },
  });
