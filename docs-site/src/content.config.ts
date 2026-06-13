// Astro Content Collection "endpoints": speist sich aus dem openapi.yaml-Loader
// (eine Quelle der Wahrheit, Design-First). Jeder Eintrag ist eine OpenAPI-
// Operation, normalisiert auf method (UPPERCASE) + kind (city|meta). Spaetere
// Slices generieren per-Endpoint-Seiten und filtern ueber kind.
import { defineCollection, z } from "astro:content";
import { loadEndpoints } from "./lib/openapi";

const endpoints = defineCollection({
  loader: async () => {
    const items = loadEndpoints();
    // Astro-Loader erwartet je Eintrag eine eindeutige `id`.
    return items.map((endpoint) => ({ id: endpoint.id, ...endpoint }));
  },
  schema: z.object({
    id: z.string(),
    path: z.string(),
    method: z.string(),
    tag: z.string(),
    summary: z.string(),
    description: z.string(),
    summaryEn: z.string().optional().default(""),
    descriptionEn: z.string().optional().default(""),
    parameters: z.array(z.any()),
    responses: z.record(z.any()),
    kind: z.enum(["city", "meta"]),
  }),
});

export const collections = { endpoints };
