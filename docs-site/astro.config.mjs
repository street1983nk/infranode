// @ts-check
import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";

// Oeffentliche Doku-Domain: Doku + API liegen beide auf infranode.dev (kein
// docs.-Subdomain). Per Env INFRANODE_DOCS_SITE ueberschreibbar (z.B. fuer
// Preview-Deploys). sitemap() braucht eine absolute site-URL fuer den Index.
// site steuert ausserdem canonical, og:url und die .md-Links in llms.txt.
const site = process.env.INFRANODE_DOCS_SITE || "https://infranode.dev";

export default defineConfig({
  site,
  integrations: [sitemap()],
});
