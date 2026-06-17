# InfraNode API

[![CI](https://github.com/street1983nk/infranode-api/actions/workflows/ci.yml/badge.svg)](https://github.com/street1983nk/infranode-api/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)

InfraNode ist eine öffentliche, quelloffene Proxy-REST-API, die fragmentierte offene Daten zu deutschen Städten hinter einer einheitlichen, normalisierten Schnittstelle bündelt. Entwickler erhalten ein konsistentes JSON-Format für Stammdaten, Luftqualität, Wetter, POIs, ÖPNV, Baustellen und Verkehr von 84 deutschen Städten (28 Kern-Städte: die 20 größten plus alle 16 Landeshauptstädte, sowie weitere Großstädte), statt sich mit Dutzenden unterschiedlicher Behörden- und Open-Data-APIs (verschiedene Formate, Felder, Sprachen) auseinandersetzen zu müssen.

## Core Value

Ein einziger, konsistenter und zuverlässig gecachter Endpunkt-Satz, der heterogene Open-Data-Quellen zu deutschen Städten normalisiert ausliefert, auch wenn einzelne Upstream-Quellen fehlen oder ausfallen.

## Status

In Betrieb. Die versionierte FastAPI-Anwendung läuft unter `/api/v1/...` mit strukturiertem JSON-Logging, Correlation-IDs, zentralem Fehler-Mapping und Resilienz (Circuit-Breaker, Graceful Degradation). Es sind reale Datenquellen angebunden (u.a. Wikidata, UBA, OpenAQ, DWD, OpenStreetMap/Overpass, DELFI/HVV, Autobahn, SMARD, KBA, DIVI). Die Daten der 84 Städte sind zusätzlich als MCP-Server verfügbar.

## MCP-Server

InfraNode ist auch als Model-Context-Protocol-Server nutzbar: 37 read-only Tools über alle Stadtdaten, keylos. Der schnellste Weg ist der öffentliche Remote-Endpunkt (kein Build, keine lokale API):

```bash
claude mcp add --transport http infranode https://mcp.infranode.dev/mcp
```

Vollständige Installationsanleitung, das komplette Tool-Manifest mit Beispiel-Ausgaben, das Berechtigungsmodell und ein Beispiel-Transkript stehen in [docs/mcp-install.md](./docs/mcp-install.md). Das Registry-Manifest ist [server.json](./server.json).

## Quick Start

Voraussetzung: Docker mit Compose v2.

```bash
# 1. Beispiel-Konfiguration kopieren (enthält KEINE echten Secrets)
cp .env.example .env

# 2. Stack lokal in einem Schritt starten (Caddy + API + Redis)
docker compose -f deploy/docker-compose.yml up

# 3. Health-Check über den Caddy-Ingress prüfen
curl http://localhost/api/v1/health
```

Der Health-Endpunkt antwortet mit `{"status": "ok", "version": "0.1.0", "redis": true}`, sobald der Stack läuft.

> Hinweis: Das Docker-Compose-Setup (`deploy/docker-compose.yml`) wird in Plan 01-02 ergänzt. Bis dahin lässt sich die API auch direkt via `uv run uvicorn infranode.main:app --reload` lokal starten (erfordert ein lokales Redis unter `redis://localhost:6379/0` oder einen angepassten `INFRANODE_REDIS_URL`).

## Konfiguration

Alle Einstellungen werden über Umgebungsvariablen mit dem Präfix `INFRANODE_` gesteuert (siehe `.env.example`). Jede Datenquelle ist einzeln per `INFRANODE_ENABLE_*`-Flag aktivierbar (Graceful Degradation: fehlt ein Key oder fällt eine Quelle aus, bleibt die API lauffähig).

Es werden niemals echte Secrets in das Repository committet. Nur `.env.example` ist versioniert; die lokale `.env` mit echten Keys bleibt durch `.gitignore` ausgeschlossen und wird in CI per gitleaks-Scan abgesichert.

## Lizenz: Code und Daten getrennt

- **Code:** Apache-2.0 (siehe [LICENSE](./LICENSE)). Patentschutz und seriöse Basis für ein öffentliches OSS-Projekt.
- **Daten:** Die über InfraNode ausgelieferten Open-Data-Inhalte stehen unter den jeweils eigenen Lizenzen der Upstream-Quellen (z. B. ODbL für OpenStreetMap, DL-DE-BY für GovData, Quellenangabe-Pflicht beim DWD). Diese Daten-Lizenzen und die zugehörige Attribution werden separat in `DATA-LICENSES.md` geführt. Diese Datei wird ab Phase 4 mit den ersten echten Quellen befüllt.

Das Code-vs-Daten-Lizenz-Prinzip ist bewusst getrennt: Die Apache-2.0-Lizenz deckt ausschließlich den Quellcode der API, nicht die durchgereichten Daten.

## Mitwirken

Beiträge sind willkommen. Setup, Gate-Kommandos und die Secret-Regel stehen in [CONTRIBUTING.md](./CONTRIBUTING.md).
