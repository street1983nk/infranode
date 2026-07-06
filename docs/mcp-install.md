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
deutschen Städten (Wetter, ÖPNV, Luft, Verkehr, Demografie, öffentliche
Auftragsvergabe und mehr) über 12 schlanke MCP-Tools, die zusammen 66
Datenarten abdecken. Das hält den Token-Footprint im Kontextfenster des
Agenten minimal, bleibt weit unter den Tool-Limits gängiger Clients (z.B. 80
Tools in Cursor), und die Datenbreite wächst weiter, ohne dass neue Tools
dazukommen.

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
| Netzwerk (eingehend, Remote) | Nur der Remote-Server bindet einen Port (hinter Caddy/Cloudflare). Pro IP auf 60 Anfragen/Minute begrenzt (HTTP 429 + Retry-After bei Überschreitung). |
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
- **Rate-Limit (Remote, `src/infranode/mcp/ratelimit.py`):** Der öffentliche
  Streamable-HTTP-Endpunkt drosselt pro echter Client-IP (CF-Connecting-IP) mit
  einem Moving-Window (Default 480/Minute, per `INFRANODE_MCP_RATE_LIMIT`
  einstellbar). Überschreitung liefert HTTP 429 mit `Retry-After`. Der lokale
  stdio-Transport ist davon unberührt (kein offener Port).

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

12 Tools, die zusammen 67 Datenarten abdecken. Stadtbezogene Tools erwarten
einen `slug` (z.B. `berlin`, `hamburg`); gültige Slugs liefert `list_cities`.
Ausnahmen sind unten markiert.

| Tool | Argumente | Beschreibung | Quelle |
| --- | --- | --- | --- |
| `get_city` | `slug` | Base data for a German city (population, area, coordinates) | Wikidata |
| `get_city_overview` | `slug` | One-call overview: base data, a catalog of all 67 data types with coverage status and the matching resource key, plus a live highlights snapshot (weather, air). Discovery entry point | InfraNode |
| `get_city_resource` | `slug`, `resource` | Generic accessor: fetch ANY of the 67 data types by its resource key (kebab-case enum, see list below) | je Datenart |
| `air_quality` | `slug` | Official air quality (PM10, PM2.5, NO2, O3, SO2) | UBA |
| `weather` | `slug` | Current weather observations (not a forecast) | DWD |
| `pois` | `slug`, `type` | Points of interest, filtered by type | OpenStreetMap |
| `station_board_departures` | `eva` | Live departures of any station by EVA (all categories, incl. local trains + disruptions) | DB Timetables |
| `station_board_arrivals` | `eva` | Live arrivals of any station by EVA (all categories, incl. local trains + disruptions) | DB Timetables |
| `transit_departures` | `slug`, `stop_id?` | Live public-transport departures with real-time delays | GTFS-RT/HVV/VGN |
| `list_cities` | keine | List all covered cities (slug, state, population, coverage) | InfraNode |
| `sources` | keine | List all data sources with license, attribution and status | InfraNode |
| `compare` | `resource`, `cities` | Compare one resource (weather, air, indicators, demographics, unemployment, tourism, charging-status, weather-warnings) across multiple cities | InfraNode |

Das `pois`-Tool nimmt zusätzlich `type` aus der API-Whitelist (z.B. `hospital`,
`school`, `pharmacy`, `restaurant`, `police`, `kindergarten`).
`transit_departures` nimmt optional eine `stop_id`.

### Datenarten: der `resource`-Parameter von `get_city_resource`

Alle Datenarten ohne eigenes Tool holt der Agent über
`get_city_resource(slug, resource="<schlüssel>")`. Beispiel:
`get_city_resource(slug="berlin", resource="charging")` liefert die Ladesäulen
in Berlin. Der `resource`-Parameter ist ein Enum mit 67 Schlüsseln
(kebab-case). Welche Schlüssel eine Stadt abdeckt, zeigt
`get_city_overview(slug)` (je Datenart Schlüssel plus Abdeckungsstatus); die
Resource `infranode://catalog` listet alle Datenarten. Einige Datenarten haben
ein eigenes Tool (unten markiert), sind aber teilweise auch über den
generischen Zugriff erreichbar.

| Datenart | Beschreibung |
| --- | --- |
| `base` | Stammdaten einer Stadt. Eigenes Tool: `get_city` |
| `overview` | Ein-Aufruf-Überblick mit Katalog und Live-Highlights. Eigenes Tool: `get_city_overview` |
| `geo` | Geodaten und Verwaltungsgrenzen |
| `demographics` | Demografische Indikatoren |
| `population-density` | Einwohnerdichte aus dem Zensus-2022-100m-Gitter |
| `air-uba` | Amtliche Luftqualität (UBA). Eigenes Tool: `air_quality` |
| `air` | Luftqualität, Live-Messwerte (ohne Historie) |
| `weather` | Aktuelle Wetterbeobachtungen (DWD). Eigenes Tool: `weather` |
| `weather-warnings` | Amtliche Wetterwarnungen (höchste aktive Stufe) |
| `civil-protection-warnings` | Amtliche Bevölkerungsschutz-Warnungen (BBK NINA): Gefahrstoff, Großbrand, Bombenentschärfung. Warntext verbatim |
| `pollen-uv` | Pollenflug und UV-Index (Region) |
| `fire-danger` | Waldbrand- und Graslandfeuer-Index (DWD) |
| `traffic` | Autobahn-Baustellen und Verkehrsmeldungen (Region) |
| `transit` | ÖPNV-Haltestellen (statisch) |
| `charging` | Ladesäulen-Standorte (Bundesnetzagentur) |
| `charging-status` | Live-Ladesäulen-Belegung je Stadt (eRound, alle 84 Städte) |
| `road-events` | Innerstädtische Baustellen und Sperrungen (Teilabdeckung) |
| `parking` | Live-Parkbelegung (Dortmund, Frankfurt am Main, Wuppertal) |
| `vehicle-registrations` | Pkw-Bestand und Elektroauto-Anteil (KBA) |
| `accidents` | Verkehrsunfälle je Kreis, jährlich (Unfallatlas) |
| `crime-stats` | Kriminalstatistik je Hauptstraftatengruppe (BKA PKS) |
| `fuel-prices` | Aktuelle Spritpreise, aggregiert je Sorte (Tankerkönig) |
| `sharing` | Bike-/Scooter-Sharing, aggregiert (GBFS, Teilabdeckung) |
| `bike-counts` | Radzählstellen je Stadt (kommunale Open Data, Teilabdeckung) |
| `station-departures` | Live-Fernverkehrs-Abfahrten am Haupt-Bahnhof (DB Timetables) |
| `station-arrivals` | Live-Fernverkehrs-Ankünfte am Haupt-Bahnhof (DB Timetables) |
| `stations` | Katalog aller DB-Bahnhöfe einer Stadt mit EVA-Nummern (DB StaDa) |
| `station-facilities` | Bahnhofsausstattung: Aufzug-/Fahrtreppen-Status (DB FaSta, Teilabdeckung) |
| `water-level` | Pegelstände an Bundeswasserstraßen (PEGELONLINE, Teilabdeckung) |
| `flood` | Hochwasser-Warnstufen (Länderhochwasserportal, Teilabdeckung) |
| `bathing-water` | Badegewässerqualität im Umkreis (EEA) |
| `health` | Krankenhausverzeichnis (Regionalstatistik) |
| `icu-live` | Intensivbetten-Belegung, Live (DIVI) |
| `hospitals-atlas` | Krankenhausstandorte aus dem Bundes-Klinik-Atlas |
| `energy` | Energieanlagen (Marktstammdatenregister) |
| `power-load` | Tägliche Netzlast der Regelzone (SMARD) |
| `power-price` | Börsenstrompreis Day-ahead (SMARD) |
| `solar` | Solar-Einstrahlung und normierter PV-Ertrag je kWp (PVGIS) |
| `solar-roofs` | Dach-Solarkataster je Stadt (Teilabdeckung) |
| `district-heating` | Fernwärme und Wärmenetze (kommunale Wärmeplanung, Teilabdeckung) |
| `unemployment` | Arbeitslose und Arbeitslosenquote je Kreis (Regionalstatistik) |
| `tourism` | Gästeübernachtungen und Ankünfte je Kreis (Regionalstatistik) |
| `construction` | Baugenehmigungen je Kreis (Regionalstatistik) |
| `indicators` | Sozialökonomische Indikatoren je Kreis (INKAR/BBSR) |
| `land-values` | Amtliche Bodenrichtwerte, aggregiert (BORIS, Teilabdeckung) |
| `tax-rates` | Realsteuer-Hebesätze je Gemeinde (Regionalstatistik) |
| `business-registrations` | Gewerbean-/-abmeldungen und Saldo je Kreis (Regionalstatistik) |
| `insolvencies` | Beantragte Insolvenzen je Kreis, jährlich (Regionalstatistik) |
| `public-tenders` | Öffentliche Auftragsvergabe: laufende und vergebene Aufträge (OCDS) |
| `events` | Veranstaltungen (Teilabdeckung, kommunal) |
| `webcams` | Verkehrs-Webcams (Region, Teilabdeckung, Autobahn) |
| `election` | Wahlergebnisse |
| `holidays` | Feiertage des Bundeslands |
| `heritage` | Denkmäler/Baudenkmale aus der Landes-Denkmalliste (Berlin) |
| `office-wait-times` | Behörden-Wartezeiten je Stadt: Live-Wartezeit der Bürgerämter (nur Köln, Teilabdeckung) |
| `playgrounds` | Öffentliche Spielplätze (OpenStreetMap) |
| `drinking-water` | Öffentliche Trinkwasserbrunnen (OpenStreetMap) |
| `public-toilets` | Öffentliche Toiletten (OpenStreetMap) |
| `markets` | Wochen- und Marktplätze (OpenStreetMap) |
| `parcel-lockers` | Paketstationen/Locker (OpenStreetMap) |
| `post-offices` | Postfilialen (OpenStreetMap) |
| `post-boxes` | Öffentliche Briefkästen mit Leerungszeiten (OpenStreetMap) |
| `public-wifi` | Öffentliche WLAN-Standorte (OpenStreetMap) |
| `recycling-centres` | Recycling-/Wertstoffhöfe (OpenStreetMap) |
| `government-offices` | Behörden und Ämter (OpenStreetMap) |
| `education` | Bildungseinrichtungen (OpenStreetMap) |
| `tree-cadastre` | Baumkataster je Stadt (Berlin) |

Points of Interest laufen ausschließlich über das eigene Tool `pois`
(Pflichtparameter `type`), da der generische Zugriff keinen Typ-Filter kennt.

## Beispiel-Argumente und echte Ausgaben

Jedes Tool gibt den kanonischen Envelope zurück: `data` enthält die Nutzdaten
plus Herkunft/Lizenz/Attribution, `meta` enthält Correlation-ID, Quell-Status
und Cache-Status. Die folgenden Ausgaben sind echte, gekürzte Antworten der
Live-API.

`get_city_overview(slug="berlin")` , the discovery entry point, start here for any
city question instead of guessing a single tool:

```json
{
  "data": {
    "city_slug": "berlin",
    "base": { "population": 3782202, "area_km2": 891.12, "geo": { "lat": 52.52, "lon": 13.38 } },
    "catalog": [
      { "resource": "weather", "tool": "weather", "covered": true },
      { "resource": "air-uba", "tool": "air_quality", "covered": true },
      { "resource": "solar-roofs", "tool": "get_city_resource", "covered": true }
    ],
    "highlights": {
      "weather": { "temperature_c": 19.4, "condition": "dry" },
      "air": { "pm10": 12.0 }
    }
  },
  "meta": { "source_status": "ok", "cache_status": "MISS" }
}
```

`get_city(slug="berlin")` , for just the base facts, without the full catalog:

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

`weather(slug="berlin")` , for a single known fact once you already know what you want:

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

`get_city_resource(slug="koeln", resource="public-tenders")`, der generische
Zugriff für jede Datenart ohne eigenes Tool:

```json
{
  "data": {
    "city_slug": "koeln",
    "source": "oeffentlichevergabe",
    "license_id": "cc0",
    "license_tier": "A",
    "attribution": { "text": "Datenservice Öffentlicher Einkauf" },
    "payload": {
      "kind": "public_tenders",
      "count": 2,
      "notices": [
        { "notice_type": "tender", "status": "active", "buyer_city": "Köln", "cpv": "45000000", "value": null }
      ]
    }
  },
  "meta": { "source_status": "ok", "cache_status": "MISS" }
}
```

## Beispiel-Transkript (inklusive Fehlerfall)

Bei einer offenen/allgemeinen Frage ist `get_city_overview` der richtige erste
Aufruf statt ein einzelnes Tool zu raten: er liefert Stammdaten plus den
Katalog aller Datenarten in einem Schritt.

```
Nutzer: Was gibt es an offenen Daten zu Köln?

Agent -> Tool: get_city_overview(slug="koeln")
Tool  -> Agent: { "data": { "base": { "population": 1073096, ... },
                  "catalog": [ { "resource": "weather", "tool": "weather", "covered": true },
                               { "resource": "public-tenders", "tool": "get_city_resource", "covered": true },
                               ... 62 weitere Datenarten ... ] },
                  "meta": { "source_status": "ok" } }

Agent: Zu Köln gibt es u.a. Wetter, Luftqualität, ÖPNV, Verkehr, öffentliche
Vergaben und mehr , soll ich zu einem Bereich ins Detail gehen?
```

Bei einer konkreten, bereits eindeutigen Frage ruft der Agent direkt das
passende Einzel-Tool auf; ein typischer Ablauf, der zuerst gültige Slugs
ermittelt und dann Daten abruft. Der zweite Teil zeigt bewusst einen
Fehlerfall.

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
