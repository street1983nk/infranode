# InfraNode API - Multi-Stage uv-Build (FND-01)
# Quelle: uv Docker Guide (https://docs.astral.sh/uv/guides/integration/docker/) [CITED: STACK.md]
# Basis: python:3.13-slim-bookworm (multi-arch; laeuft auf der Prod-Box als
# linux/amd64, AMD EPYC-Genoa/x86_64); bewusst slim-bookworm statt musl-basierter
# Images (musl-Wheel-Recompiles, langsam/OOM).

# --- Builder-Stage: Deps + Projekt installieren -----------------------------
FROM python:3.13-slim-bookworm AS builder

# uv als statisches Binary aus dem offiziellen Image kopieren (kein pip-Install noetig).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# UV_COMPILE_BYTECODE: schnellere Container-Starts; UV_LINK_MODE=copy: kein Hardlink-Warnen ueber Layer-Grenzen.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app

# Zweistufig fuer optimales Layer-Caching: erst nur Lockfiles -> Deps,
# dann Projekt-Quellen -> Projekt-Install. Aenderungen am Code invalidieren nicht den Dep-Layer.
# --group explorer zieht duckdb (sonst aus dem Live-Image ausgeschlossen) hinzu,
# damit der Admin-Daten-Explorer funktioniert. duckdb bleibt NUR eine Gruppe, NIE
# in [project] dependencies (T-17-IMG, test_explorer_not_in_live_path) und wird im
# Code ausschliesslich lazy importiert. --no-dev laesst Test-/Lint-Gruppen weg.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --group explorer --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev --group explorer

# --- Final-Stage: schlankes Laufzeit-Image, non-root --------------------------
FROM python:3.13-slim-bookworm

# Non-root-User (T-02-02: keine Elevation, kein uv/Compiler im finalen Image).
RUN useradd -m app
WORKDIR /app

# Nur das fertige venv + die Quellen aus dem Builder uebernehmen.
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

# Konfigurations-Seeds an einen Pfad AUSSERHALB des Daten-Volumes legen
# (CR-01): das Prod-Volume infranode_data mountet auf /app/data und wuerde dort
# liegende Seeds verschatten. Gelesen ueber INFRANODE_SEEDS_DIR.
COPY data/seeds /app/seeds

# OpenAPI-first-Vertrag: api/v1/openapi.py liest docs/openapi.yaml beim Import
# (relativ zu WORKDIR /app). Ohne diese Datei crasht der Container beim Start.
COPY docs/openapi.yaml /app/docs/openapi.yaml

# venv-Binaries (uvicorn) in den PATH; Quellen importierbar machen.
# INFRANODE_SEEDS_DIR zeigt auf die ins Image kopierten Seeds (volume-frei).
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    INFRANODE_SEEDS_DIR="/app/seeds"

USER app
EXPOSE 8000

# Container-interner Healthcheck gegen die versionierte /api/v1/health-Route.
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/v1/health').status==200 else 1)"]

# infranode.main:app ist der Modul-Ebenen-app aus Plan 01-01 (create_app()-Factory).
CMD ["uvicorn", "infranode.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
