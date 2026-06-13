# Beitragsleitfaden

Danke, dass du zu InfraNode API beitragen möchtest. Dieser Leitfaden beschreibt das Setup, die verbindlichen Qualitäts-Gates und die Regel zum Umgang mit Secrets.

## Setup

Das Projekt nutzt [uv](https://docs.astral.sh/uv/) für Dependency- und Environment-Management (Python 3.13).

```bash
# Abhängigkeiten installieren und virtuelle Umgebung aufbauen
uv sync
```

## Verbindliche Gate-Kommandos

Bevor du einen Pull Request öffnest, müssen alle drei Gates lokal grün sein. Genau diese Kommandos laufen auch in der CI:

```bash
# Linting (ruff: E, F, I, UP, B, ASYNC, S)
uv run ruff check .

# Format-Prüfung (ruff format im Check-Modus)
uv run ruff format --check .

# Tests (pytest, async-Modus aktiv)
uv run pytest -q
```

Ein PR wird nur gemergt, wenn ruff (check + format) und pytest sauber durchlaufen. Das ist das verbindliche Abschluss-Gate des Projekts: Linting + Tests müssen grün sein, bevor etwas als "fertig" gilt.

## Secret-Regel: niemals Secrets committen

- Echte API-Keys, Tokens oder Zugangsdaten gehören **niemals** ins Repository.
- Konfiguration läuft ausschließlich über Umgebungsvariablen mit dem Präfix `INFRANODE_`.
- Nur `.env.example` (mit leeren Platzhaltern) wird versioniert. Deine lokale `.env` mit echten Werten ist durch `.gitignore` ausgeschlossen und darf das auch bleiben.
- In CI läuft bei jedem Push und Pull Request ein **gitleaks**-Scan über die volle Git-History. Findet er ein Secret, schlägt die Pipeline fehl (`--exit-code 1`). Gefundene Secrets werden im CI-Log redigiert (`--redact`).

Falls du versehentlich ein Secret committet hast: Rotiere den betroffenen Key sofort (gitleaks erkennt ihn auch in der History) und entferne ihn aus dem Verlauf, bevor du pushst.

## Code-Stil

- Deutschsprachige Docstrings und Kommentare, korrekte Umlaute (ä/ö/ü/ß), keine ASCII-Ersatzschreibweise.
- Folge den im Projekt etablierten Mustern (App-Factory, zentrales Error-Mapping, strukturiertes JSON-Logging, versioniertes Routing unter `/api/v1`).
