# InfraNode

[![GitHub stars](https://img.shields.io/github/stars/street1983nk/infranode?style=flat&logo=github)](https://github.com/street1983nk/infranode/stargazers)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache_2.0-blue.svg)](./LICENSE)
[![Glama score](https://glama.ai/mcp/servers/street1983nk/infranode/badges/score.svg)](https://glama.ai/mcp/servers/street1983nk/infranode)
[![MCP Registry](https://img.shields.io/badge/MCP_Registry-dev.infranode%2Finfranode-1f6feb)](https://registry.modelcontextprotocol.io)
[![Smithery](https://img.shields.io/badge/Smithery-infranode-7c3aed)](https://smithery.ai/server/infranode/infranode)

**The open-data REST API for Germany: a keyless HTTP API for German
public-infrastructure open data, also available as an MCP server.**

German cities publish a lot of open data, but every source has its own format,
fields and quirks, and several need portal registration. InfraNode normalizes
~20 categories, weather (DWD), air quality (UBA), public transit (incl. realtime
departures), traffic, electricity price (SMARD), land values (BORIS), parking,
charging, water levels, demographics, energy and more, for **84+ German cities**
behind **one** interface. **No API key, no account.** Every response uses one
canonical `{ data, meta }` envelope with per-record license and attribution. The
same data is also exposed as an MCP server (12 lean read-only tools covering 67
data types) for AI agents.
Start with the one-call `get_city_overview`: it returns a catalog of every data
type available for a city plus a live highlights snapshot, so agents discover the
full breadth, not just weather. InfraNode is actively growing, with more data
types and cities added regularly.

Sources include the Deutscher Wetterdienst (DWD), Umweltbundesamt (UBA),
Mobilithek/DELFI, GovData, OpenStreetMap, Bundesnetzagentur, KBA, DIVI and more.

## See it in action

[![InfraNode live overview for Cologne: current weather, official air quality, DWD warnings, live train departures with delays, roadworks and the full data-type catalog, all from one keyless call](https://infranode.dev/showcase/koeln-live-dashboard.png)](https://infranode.dev)

*A single `get_city_overview("koeln")` call: current weather, official air
quality, DWD warnings, live train departures with delays, roadworks and the full
per-city data catalog, from one keyless endpoint. Try any city live at
[infranode.dev](https://infranode.dev).*

## How it works

One shared HTTP client fans out to the upstream sources, each response is mapped
into the canonical schema, license-gated with its attribution and cached in Redis
(with stale-on-error fallback), then served through both a REST API and an MCP
server. A failing upstream degrades to `source_status`, it never fails the call.

```mermaid
flowchart LR
    subgraph SRC["25+ German open-data sources"]
        direction TB
        S1["DWD, UBA<br/>weather, air"]
        S2["Mobilithek, DELFI, DB<br/>transit, realtime"]
        S3["SMARD, BNetzA, MaStR<br/>energy"]
        S4["BORIS, GovData, OSM,<br/>DIVI, KBA, ..."]
    end

    subgraph CORE["InfraNode core"]
        direction TB
        N["Normalize<br/>one canonical schema"] --> L["License-gate<br/>per-record attribution"] --> C["Redis cache<br/>stale-on-error fallback"]
    end

    SRC --> CORE
    CORE --> API["REST API<br/>infranode.dev/api/v1<br/>84 cities, keyless"]
    CORE --> MCP["MCP server<br/>mcp.infranode.dev<br/>12 read-only tools"]
    API --> APPS["Apps &amp; dashboards"]
    MCP --> AGENTS["AI agents<br/>Claude, ChatGPT"]
```

> If InfraNode saves you a data integration, a star helps other developers find it.

## Quickstart

Base URL `https://infranode.dev/api/v1`. No key, no account, just call it:

```bash
curl https://infranode.dev/api/v1/cities/koeln/weather
```

```jsonc
{
  "data": {
    "city_slug": "koeln",
    "observed_at": "2026-06-18T13:00:00Z",
    "source": "dwd",
    "attribution": { "text": "Datenbasis: Deutscher Wetterdienst", "modified": true },
    "payload": { "kind": "weather", "temperature_c": 30.4, "humidity": 43.0, "station_id": "02667" }
  },
  "meta": { "source_status": "ok", "cache_status": "hit", "correlation_id": "..." }
}
```

Every response follows the same `{ data, meta }` envelope: each record carries
its `attribution` (license + source), and `meta.source_status` tells you whether
the upstream source delivered data, so a dead source degrades gracefully instead
of failing the call.

> Tip: call `/api/v1/cities` first to discover valid city slugs (e.g. `koeln`,
> `berlin`, `hamburg`), then call any city-scoped endpoint.

[![Run in Postman](https://run.pstmn.io/button.svg)](https://god.gw.postman.com/run-collection/55901679-26601800-bf9d-4ddd-8413-5f273f18be4d)

The full interactive reference and per-city coverage live at
[infranode.dev](https://infranode.dev). The
[InfraNode API on the Postman API Network](https://www.postman.com/alster83-7133231/infranode/overview)
mirrors every endpoint with real example responses, so you can try the
[InfraNode API Postman collection](https://www.postman.com/alster83-7133231/infranode/collection/pft781f/infranode-api)
in the browser without an API key.

## Data (84 cities, 101 endpoints)

Every category below is a REST endpoint under `/api/v1/cities/{slug}/<key>`.
Over MCP the same data comes through 12 lean tools: a few named ones
(`get_city_overview`, `weather`, `air_quality`, `pois`, `compare`, live boards)
plus one generic `get_city_resource(slug, resource=<key>)` for every other data
type (its `resource` enum lists all 67 keys).

| Group | Data types (endpoint keys) |
|-------|----------------------------|
| **Discovery** | `list_cities`, `sources`, `compare` (one resource across many cities), `overview` (one-call catalog + live snapshot) |
| **Weather & environment** | `weather`, `weather-warnings`, `civil-protection-warnings` (BBK NINA), `air-uba` (official), `air` (live), `pollen-uv`, `water-level`, `flood`, `fire-danger`, `bathing-water` |
| **Mobility** | `transit`, live stop departures (`transit_departures` tool), `stations` (catalog), station boards by EVA (`station_board_departures`/`station_board_arrivals` tools, incl. local trains + disruptions), `station-departures`, `station-arrivals`, `traffic`, `road-events`, `webcams`, `charging`, `parking` (live occupancy), `sharing`, `fuel-prices`, `bike-counts` |
| **City & people** | `base`, `geo`, `demographics`, `indicators`, `unemployment`, `tourism`, `construction`, `accidents`, `crime-stats`, `health`, `icu-live`, `holidays`, `election`, `events`, `pois`, playgrounds/markets/toilets and more OSM types |
| **Economy & real estate** | `land-values`, `tax-rates` (trade/property tax multipliers per municipality), `business-registrations` (founding dynamics per district), `insolvencies` (insolvency filings per district: corporate and other debtors, annual), `public-tenders` (public procurement: running tenders and awarded contracts per city) |
| **Energy & vehicles** | `power-load`, `power-price`, `energy`, `solar`, `solar-roofs`, `district-heating`, `vehicle-registrations` |

## How it behaves

- **Keyless & read-only.** No credentials, no writes, no user accounts.
- **Canonical envelope.** `{ data, meta }` with per-source status and attribution.
- **Graceful degradation.** A failing upstream returns `source_status`, not an error.
- **Safe by design.** SSRF and injection gates validate every request; inputs are checked against fixed allowlists.

See [SECURITY.md](./SECURITY.md) for the security model.

## Use it as an MCP server

The same API is exposed as a remote MCP server, so AI agents can call all 67
data types as tools. One line with Claude Code:

```bash
claude mcp add --transport http infranode https://mcp.infranode.dev/mcp
```

Any other MCP client, point it at the remote endpoint (Streamable HTTP):

```jsonc
{
  "mcpServers": {
    "infranode": { "url": "https://mcp.infranode.dev/mcp" }
  }
}
```

- **Cursor / Windsurf:** add the block above to `~/.cursor/mcp.json` (or the app's MCP settings).
- **VS Code:** `code --add-mcp '{"name":"infranode","url":"https://mcp.infranode.dev/mcp"}'`
- **Claude Desktop:** add the same `mcpServers` block to your `claude_desktop_config.json`.
- **ChatGPT:** add a connector with the URL `https://mcp.infranode.dev/mcp`.

All tools are annotated `readOnlyHint: true` / `destructiveHint: false` /
`idempotentHint: true`, so MCP clients can safely auto-allow them. The MCP layer
also ships ready-made **prompts** (`city_briefing`, `compare_air_quality`,
`commute_check`) and **resources** (`infranode://cities`, `infranode://sources`).
Full install guide, the complete tool manifest with example outputs, the
permission model and an example transcript are in
[docs/mcp-install.md](./docs/mcp-install.md). The registry manifest is
[server.json](./server.json).

## Use it in ChatGPT (Custom GPT action)

**Ready-made GPT:** [German City Data (InfraNode)](https://chatgpt.com/g/g-6a48bf065e648191b062bc86256c1897-infranode-live-data-for-german-cities)
is listed in the GPT Store (Research & Analysis) and works out of the box.

To build your own: InfraNode ships a curated OpenAPI spec for GPT
actions: 23 of the most useful operations (ChatGPT allows at most 30 per
action), keyless, all GET.

1. In the [GPT editor](https://chatgpt.com/gpts/editor) open **Configure →
   Actions → Create new action → Import from URL** and paste
   `https://infranode.dev/actions/openapi.json`.
2. Leave authentication at **None**; as privacy policy use
   `https://infranode.dev/en/privacy/`.
3. Tell the GPT in its instructions to start with `getCityOverview(slug)`,
   resolve city names via `getCities`, and cite `data.attribution` (the data
   licences require attribution).

Details and recommended instructions:
[infranode.dev/en/chatgpt/](https://infranode.dev/en/chatgpt/). The spec is
generated from `docs/openapi.yaml` by `scripts/build_actions_spec.py`.

## Alternatives and how InfraNode compares

Other MCP servers cover parts of the German or European data space. InfraNode is
the broadest for city-level open data, and the projects below often complement
each other:

- **[germany-mcp-server](https://github.com/AiAgentKarl/germany-mcp-server)** federal and government data (Autobahn, DWD, NINA, SMARD, Bundestag). Nationwide, no per-city breadth.
- **[db-mcp-server](https://github.com/PaulvonBerg/db-mcp-server)** / db-timetable-mcp Deutsche Bahn rail timetables only.
- **[mcp-server-public-transport](https://github.com/mirodn/mcp-server-public-transport)** public transport across Europe; in Germany it covers Berlin/Brandenburg (VBB).
- **Single-city servers** (e.g. Munich, Berlin) cover one city each.

InfraNode covers **84 German cities and 67 data types** behind one keyless, hosted
endpoint, from environment and mobility to energy, economy and city life. Full
side-by-side comparison:
[infranode.dev/en/mcp-comparison](https://infranode.dev/en/mcp-comparison/).

## Self-host (optional)

You don't need to, the hosted endpoint above is the fastest path. But the code
is open. Run the API stack locally with Docker (Compose v2):

```bash
cp .env.example .env          # example config, contains NO real secrets
docker compose -f deploy/docker-compose.yml up
curl http://localhost/api/v1/health   # -> {"status":"ok","version":"1.0.0","redis":true}
```

To run the MCP server itself locally over stdio (against the public API):

```bash
uv sync --group mcp
INFRANODE_MCP_API_BASE=https://infranode.dev/api/v1 uv run python -m infranode.mcp.server
```

All settings use the `INFRANODE_` env prefix (see `.env.example`); each data
source is toggled by its own `INFRANODE_ENABLE_*` flag. Real secrets are never
committed, only `.env.example` is versioned and CI runs a gitleaks scan.

## License: code and data are separate

- **Code:** Apache-2.0 (see [LICENSE](./LICENSE)).
- **Data:** the open data served through InfraNode keeps the licenses of its
  upstream sources (e.g. ODbL for OpenStreetMap, DL-DE-BY for GovData, attribution
  for DWD). These data licenses and attribution are tracked separately in
  `DATA-LICENSES.md`. The Apache-2.0 license covers only the API source code, not
  the passed-through data.

## Contributing

Contributions are welcome. Setup, gate commands and the secret rule are in
[CONTRIBUTING.md](./CONTRIBUTING.md). To add a new data source, start with the
declarative source registry in `src/infranode/registry/source_specs.py` (one
`SourceSpec` entry per upstream); CONTRIBUTING.md has the full checklist.
