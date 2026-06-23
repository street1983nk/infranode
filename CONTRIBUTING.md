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

## Datenquelle hinzufügen

Eine neue Upstream-Quelle ist deklarativ an **einer** Stelle definiert:
`src/infranode/registry/source_specs.py`. Ein `SourceSpec`-Eintrag dort speist
automatisch die abgeleiteten Strukturen (Quellenliste der `/sources`-Route,
Lizenz + Attribution, Cache-TTL, Breaker-Cooldown), sodass keine vier verstreuten
Stellen mehr gepflegt werden müssen.

Schritte für eine neue Quelle `meine_quelle`:

1. **Registry-Eintrag** in `registry/source_specs.py`:
   `SourceSpec(name="meine_quelle", license_id="...", attribution="...", ttl=(fresh_s, stale_s), cooldown=...)`.
   `ttl`/`cooldown` weglassen, wenn die Defaults passen (60 s frisch / 120 s stale, 30 s Breaker-Probe).
2. **Toggle** in `config.py` (`SourceToggleSettings`): `enable_meine_quelle: bool = ...`.
   Der Name MUSS exakt `enable_<name>` sein (dynamische Auflösung via `getattr`).
3. **SourceId** in `normalization/enums.py`: ein gleichnamiger Enum-Wert
   (dokumentierte Ausnahmen/Aliase stehen in `tests/unit/test_source_specs_registry.py`).
4. **Lizenzzeile** in `DATA-LICENSES.md`: wortgenaue Attribution (fail-closed
   gegen `tests/unit/test_source_license_map.py`).
5. **Adapter** (`adapters/<name>.py`, `fetch_*`) + **Mapper**
   (`normalization/mappers/<name>.py`, `map_*` → kanonischer Envelope).
6. **Route** (`api/v1/cities.py` bzw. `live.py`) + passender Eintrag in `docs/openapi.yaml`.

`tests/unit/test_source_specs_registry.py` erzwingt die Konsistenz (fehlender
Toggle, fehlende SourceId, ungültige Lizenz/TTL/Cooldown) und schlägt fehl, wenn
ein Schritt vergessen wurde.
