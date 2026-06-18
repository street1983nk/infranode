# InfraNode MCP-Server: Installation, Tools und Vertrauen

Dieses Dokument ist das vollständige Listing-Blatt für den InfraNode-MCP-Server:
Installation, alle Tools mit Beispiel-Argumenten und echten Ausgaben, ein
Beispiel-Transkript inklusive Fehlerfall, die angeforderten Berechtigungen,
Versions-Kompatibilität, Deinstallation und Provenance. Wer einen fremden
MCP-Server installiert, soll hier alles finden, um die Entscheidung ohne Raten
treffen zu können.

## Was dieser Server ist

Der InfraNode-MCP-Server ist ein dünner, read-only Wrapper um die öffentliche
InfraNode-Live-API. Jedes Tool ruft einen festen API-Endpunkt auf und gibt
dessen normalisiertes JSON unverändert zurück (kanonischer `{data, meta}`-
Envelope). Es gibt keine eigene Mapping-, Lizenz- oder Schreib-Logik im
MCP-Server, keine Datenbank und keinen Zustand. Er bündelt offene Daten zu 84
deutschen Städten (Wetter, ÖPNV, Luft, Verkehr, Demografie und mehr) als 38
MCP-Tools.

## Berechtigungen und Sicherheitsmodell

Dies ist das wichtigste Vertrauenssignal, daher zuerst:

| Berechtigung | Status |
| --- | --- |
| API-Keys / Secrets | Keine. Der Server ist vollständig keylos. |
| Dateisystem (lesen/schreiben) | Kein Zugriff. |
| Shell / Prozess-Ausführung | Kein Zugriff. |
| Browser / GUI-Automatisierung | Kein Zugriff. |
| Netzwerk (ausgehend) | Nur GET an die allowlistete InfraNode-Base-URL. |
| Netzwerk (eingehend, stdio) | Kein offener Port. Lokaler Subprozess über stdio. |
| Schreibende Operationen | Keine. Alle Tools sind reine Lesezugriffe (HTTP GET). |

Konkrete Schutzmechanismen im Code (`src/infranode/mcp/client.py`):

- **SSRF-Gate (T-12-MCP-SSRF):** Die Ziel-URL stammt ausschließlich aus der Env
  `INFRANODE_MCP_API_BASE`. Ihr Host wird gegen eine enge Allowlist geprüft
  (`localhost`, `127.0.0.1`, `::1`, `api`); ein nicht-allowlisteter Host wird mit
  `ValueError` abgewiesen, bevor ein Request rausgeht. Tool-Argumente können keine
  beliebige URL erzwingen.
- **Injection-Gate (T-12-MCP-INJECT):** Der Ressourcen-Name wird gegen eine
  feste Allowlist (`ALLOWED_RESOURCES`/`ALLOWED_LIVE_RESOURCES`/
  `ALLOWED_COLLECTIONS`) geprüft, der Stadt-Slug als reiner Pfadbestandteil
  url-gequotet. Slugs mit Pfad- oder Host-Anteilen (`/`, `@`, `:`, Whitespace)
  werden abgewiesen, bevor ein Request rausgeht.
- **Endlicher Timeout:** 30 s pro Aufruf, kein hängender Agent.

## Getestete Clients und Versionen

| Komponente | Version | Status |
| --- | --- | --- |
| MCP Python SDK (gebündeltes FastMCP) | `mcp[cli]==1.27.2` (exakt gepinnt) | im `mcp`-Dependency-Group fixiert |
| Python | >= 3.13 | erforderlich |
| InfraNode-Paket | 1.0.0 | siehe `pyproject.toml` |
| Claude Code | stdio + Remote-HTTP | manuell verifiziert |
| Claude Desktop | stdio | manuell verifiziert |
| Cursor und andere MCP-Clients | stdio + streamable-http | standardkonform, nicht separat verifiziert |

Die SDK-Version ist exakt gepinnt (`==1.27.2`), damit der Server nicht still mit
einer neueren Client-Version bricht. Wer einen anderen Client testet, sollte die
funktionierende Kombination hier ergänzen.

## Installation

### Variante A: Remote-Server (empfohlen, kein Build, keine lokale API)

Der öffentliche Remote-Endpunkt ist keylos und read-only. Kein Klonen, kein
Build, keine lokale API nötig.

```bash
claude mcp add --transport http infranode https://mcp.infranode.dev/mcp
```

Manifest für die offizielle MCP-Registry: siehe `server.json` im Repo-Root.

### Variante B: Claude Code lokal (stdio)

Voraussetzung: eine laufende lokale InfraNode-Live-API (Standard
`http://localhost:8000/api/v1`, siehe README). Dann:

```bash
claude mcp add infranode -- uv run --group mcp python -m infranode.mcp
```

Claude Code startet den Server bei Bedarf als lokalen Subprozess über stdio.

### Variante C: Claude Desktop (stdio)

Eintrag in `claude_desktop_config.json` unter `mcpServers`. Pfad:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "infranode": {
      "command": "uv",
      "args": ["run", "--group", "mcp", "python", "-m", "infranode.mcp"],
      "env": {
        "INFRANODE_MCP_API_BASE": "http://localhost:8000/api/v1"
      }
    }
  }
}
```

Claude Desktop nach dem Speichern neu starten. Das `env`-Feld ist optional; ohne
es gilt die Default-Base-URL.

## Deinstallation und Rollback

- Claude Code: `claude mcp remove infranode`
- Claude Desktop: den `infranode`-Eintrag aus `claude_desktop_config.json`
  entfernen und neu starten.

Der Server hält keinen Zustand, schreibt nichts und legt keine Dateien an. Nach
dem Entfernen bleibt kein Rückstand auf dem System. Ein Rollback auf eine ältere
Version erfolgt über den gepinnten Git-Tag bzw. die `uv.lock`.

## Vollständiges Tool-Manifest

38 Tools. Stadtbezogene Tools erwarten einen `slug` (z.B. `berlin`, `hamburg`);
gültige Slugs liefert `list_cities`. Ausnahmen sind unten markiert.

| Tool | Argumente | Beschreibung | Quelle |
| --- | --- | --- | --- |
| `get_city` | `slug` | Base data for a German city (population, area, coordinates) | Wikidata |
| `air_quality` | `slug` | Official air quality (PM10, NO2 and more) | UBA |
| `air_quality_live` | `slug` | Live air quality readings (live-only, no history) | OpenAQ |
| `weather` | `slug` | Current weather observations (not a forecast) | DWD |
| `pois` | `slug`, `type` | Points of interest, filtered by type | OpenStreetMap |
| `traffic` | `slug` | Motorway roadworks and traffic messages (region) | Autobahn |
| `transit` | `slug` | Public-transport stops (static) | DELFI/GTFS, HVV |
| `charging` | `slug` | EV charging-station locations | Bundesnetzagentur |
| `water_level` | `slug` | Water levels on federal waterways (partial coverage) | PEGELONLINE |
| `flood` | `slug` | Flood warning levels (partial coverage) | Länderhochwasserportal |
| `pollen_uv` | `slug` | Pollen forecast and UV index (region) | DWD |
| `demographics` | `slug` | Demographic indicators | GENESIS/Regionalstatistik |
| `energy` | `slug` | Energy installation metrics (power-generation units) | Marktstammdatenregister |
| `geo` | `slug` | Geodata and administrative boundaries | diverse |
| `election` | `slug` | Election results | diverse |
| `holidays` | `slug` | Public holidays for the city's federal state | Bundesland-Kalender |
| `health` | `slug` | Hospital directory | Regionalstatistik |
| `icu_live` | `slug` | Live ICU bed occupancy (current snapshot) | DIVI |
| `road_events` | `slug` | Inner-city roadworks and closures (partial coverage) | kommunal |
| `events` | `slug` | Public events and happenings (partial coverage) | kommunal |
| `webcams` | `slug` | Traffic webcams (region, partial coverage) | Autobahn |
| `power_load` | `slug` | Daily grid load of the control zone | SMARD |
| `power_price` | `slug` | Day-ahead wholesale electricity price (nationwide) | SMARD |
| `weather_warnings` | `slug` | Official weather warnings (highest active level) | DWD |
| `vehicle_registrations` | `slug` | Registered car stock and electric share | KBA |
| `unemployment` | `slug` | Number of unemployed and unemployment rate (district) | Regionalstatistik |
| `tourism` | `slug` | Guest overnight stays and arrivals (district) | Regionalstatistik |
| `construction` | `slug` | Building permits (district) | Regionalstatistik |
| `accidents` | `slug` | Road-traffic accidents (district, yearly) | Unfallatlas |
| `fuel_prices` | `slug` | Current fuel prices, aggregated per fuel type | Tankerkönig |
| `sharing` | `slug` | Bike/scooter sharing availability, aggregated (partial) | GBFS |
| `indicators` | `slug` | Socioeconomic indicators (district, latest year) | INKAR/BBSR |
| `station_departures` | `slug` | Live long-distance train departures (metro hubs) | DB Timetables |
| `station_arrivals` | `slug` | Live long-distance train arrivals (metro hubs) | DB Timetables |
| `transit_departures` | `slug`, `stop_id?` | Live public-transport departures with real-time delays | GTFS-RT/HVV/VGN |
| `list_cities` | keine | List all covered cities (slug, state, population, coverage) | InfraNode |
| `sources` | keine | List all data sources with license, attribution and status | InfraNode |
| `compare` | `resource`, `cities` | Compare one resource (`weather`/`air`) across multiple cities | InfraNode |

Das `pois`-Tool nimmt zusätzlich `type` aus der API-Whitelist (z.B. `hospital`,
`school`, `pharmacy`, `restaurant`, `police`, `kindergarten`).
`transit_departures` nimmt optional eine `stop_id`.

## Beispiel-Argumente und echte Ausgaben

Jedes Tool gibt den kanonischen Envelope zurück: `data` enthält die Nutzdaten
plus Herkunft/Lizenz/Attribution, `meta` enthält Correlation-ID, Quell-Status
und Cache-Status. Die folgenden Ausgaben sind echte, gekürzte Antworten der
Live-API.

`get_city(slug="berlin")`:

```json
{
  "data": {
    "city_slug": "berlin",
    "geo": { "lat": 52.516666666667, "lon": 13.383333333333 },
    "retrieved_at": "2026-06-17T09:07:33Z",
    "source": "wikidata",
    "license_id": "cc0",
    "license_tier": "A",
    "ags": "11000000",
    "wikidata_qid": "Q64",
    "attribution": {
      "text": "Wikidata",
      "license_url": "https://creativecommons.org/publicdomain/zero/1.0/"
    },
    "payload": { "kind": "city_base", "population": 3782202, "area_km2": 891.12 }
  },
  "meta": { "source_status": "ok", "cache_status": "MISS" }
}
```

`weather(slug="berlin")`:

```json
{
  "data": {
    "city_slug": "berlin",
    "observed_at": "2026-06-17T08:30:00Z",
    "source": "dwd",
    "license_id": "geonutzv",
    "attribution": { "text": "Datenbasis: Deutscher Wetterdienst, eigene Elemente ergänzt" },
    "payload": {
      "kind": "weather",
      "station_id": "00433",
      "temperature_c": 19.4,
      "humidity": 54.0,
      "condition": "dry"
    }
  },
  "meta": { "source_status": "ok", "cache_status": "HIT" }
}
```

## Beispiel-Transkript (inklusive Fehlerfall)

Ein typischer Agent-Ablauf, der zuerst gültige Slugs ermittelt und dann Daten
abruft. Der zweite Teil zeigt bewusst einen Fehlerfall.

```
Nutzer: Wie warm ist es gerade in Berlin?

Agent -> Tool: list_cities()
Tool  -> Agent: { "data": [ { "slug": "berlin", ... }, { "slug": "hamburg", ... }, ... ] }

Agent -> Tool: weather(slug="berlin")
Tool  -> Agent: { "data": { "payload": { "temperature_c": 19.4, "condition": "dry" } },
                  "meta": { "source_status": "ok", "cache_status": "HIT" } }

Agent: In Berlin sind es aktuell 19,4 Grad, trocken (Quelle: DWD).
```

Fehlerfall, unbekannte Stadt. Die Live-API antwortet mit HTTP 404 und einem
strukturierten Fehler-Envelope. Der MCP-Server gibt diesen nicht als rohen
Traceback weiter, sondern reicht `message` und `hint` als lesbare
Tool-Fehlermeldung durch, sodass das Modell sich selbst korrigieren kann (z.B.
`list_cities` aufrufen):

```
Agent -> Tool: get_city(slug="atlantis")
Tool  -> Agent: HTTP 404
                {
                  "error": {
                    "code": "not_found",
                    "message": "Unbekannte Stadt 'atlantis'.",
                    "hint": "Nutze GET /api/v1/cities fuer alle unterstuetzten Staedte."
                  }
                }
```

Lokaler Fehlerfall vor jedem Request: ein Slug mit Pfad-/Host-Anteilen (z.B.
`get_city(slug="berlin/../admin")`) löst im Client einen `ValueError`
(T-12-MCP-INJECT) aus, bevor irgendein Request rausgeht.

## Versions-Kompatibilität

- Das MCP-SDK ist exakt gepinnt (`mcp[cli]==1.27.2`). Es bricht damit nicht still
  mit neueren Client-Versionen; die getestete Kombination steht in der Tabelle
  oben.
- Der Server spricht den Standard-MCP-Transport (stdio sowie streamable-http) und
  ist daher mit jedem konformen Client kompatibel.
- Brechende Änderungen werden über die Paket-Version (`pyproject.toml`) und
  Git-Tags signalisiert.

## Build-Reproduzierbarkeit

Der veröffentlichte Code ist identisch mit dem Quellcode im öffentlichen Repo;
es gibt keinen vorgebauten, abweichenden Artefakt-Stand. Lokaler Bau:

```bash
git clone https://github.com/street1983nk/infranode
cd infranode
uv sync --group mcp          # installiert exakt die Versionen aus uv.lock
uv run --group mcp python -m infranode.mcp   # startet den Server (stdio)
```

`uv.lock` pinnt alle transitiven Abhängigkeiten; ein Klon ergibt damit denselben
lauffähigen Server.

## Transport

Primärer Transport ist stdio: der Server läuft als lokaler Subprozess des
Clients und öffnet keinen Netzwerk-Port. Tool-Aufrufe gehen ausschließlich an die
konfigurierte, allowlistete Base-URL. Der öffentliche Remote-Endpunkt
(`https://mcp.infranode.dev/mcp`) nutzt streamable-http hinter Caddy/Cloudflare,
keylos wie die API, aktiviert per `INFRANODE_MCP_TRANSPORT=streamable-http`.

## Lizenz und Provenance

- **Code:** Apache-2.0 (siehe `LICENSE`).
- **Daten:** Die durchgereichten Open-Data-Inhalte stehen unter den jeweils
  eigenen Lizenzen der Upstream-Quellen. Jede Antwort trägt im Envelope
  `license_id`, `license_tier` und ein `attribution`-Objekt mit Quellenangabe und
  Lizenz-URL. Das Tool `sources` listet alle Quellen mit Lizenz und Status.

## Betreiber und Reputation

- Quellcode (öffentlich): https://github.com/street1983nk/infranode
- Live-API und Doku: https://infranode.dev
- Status-Page (Verfügbarkeit, Per-City-Coverage): https://status.infranode.dev
- MCP-Registry-Manifest: `server.json` im Repo-Root

## End-to-End-Prüfung

Die vollständige E2E-Prüfung im echten Client (Claude Code bzw. Claude Desktop)
ist eine manuelle Verifikation: Tools erscheinen im Client und ein
`get_city`-Aufruf liefert gegen die laufende API Daten. Für den Remote-Endpunkt
genügt Variante A ohne lokale API.
