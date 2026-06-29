"""Gemeinsame, env-overridebare Auflösung des Seed-Verzeichnisses (CR-01).

Eine Quelle der Wahrheit für den Pfad der committeten Seeds (REST-Regel 6,
keine Duplikate). Früher lösten ``collector/plan.py``, ``mappers/holidays.py``,
``registry/cities.py`` und ``export/enrich.py`` den Pfad je einzeln per
``Path(__file__).resolve().parents[...] / "data" / "seeds"`` auf und ignorierten
dabei ``INFRANODE_SEEDS_DIR`` (Live-Report 2026-06-12, M1): im Prod-Container
verschattet das Named Volume ``infranode_data`` den Pfad ``/app/data``, weshalb
das Dockerfile die Seeds nach ``/app/seeds`` legt und ``INFRANODE_SEEDS_DIR``
darauf setzt. Wurde der Env-Override ignoriert, fehlten Seeds (holidays no_data,
56 fehlende Städte aus registry_extended.json).

KRITISCH: Lazy zur Laufzeit auflösen (``os.environ`` bei jedem Aufruf lesen),
NIE auf Modul-Import-Zeit in eine Konstante einfrieren. Sonst können Tests den
Env-Override nicht mehr setzen (Settings-Singleton-Caching).
"""

from __future__ import annotations

import os
from pathlib import Path

# Repo-Layout-Fallback: diese Datei liegt unter src/infranode/infra/seeds.py,
# also ist der Repo-Root parents[3]; data/seeds/ liegt direkt darunter.
_REPO_SEED_DIR = Path(__file__).resolve().parents[3] / "data" / "seeds"


def seeds_dir() -> Path:
    """Loest das Seed-Verzeichnis lazy auf (Env-Override gewinnt, sonst Repo-Layout).

    ``INFRANODE_SEEDS_DIR`` (Prod-Container: ``/app/seeds``) hat Vorrang; ohne
    gesetzten Override gilt das Repo-Layout (lokal, Tests). Wird bei jedem Aufruf
    frisch aus ``os.environ`` gelesen, damit per-Test gesetzte Overrides greifen.
    """
    override = os.environ.get("INFRANODE_SEEDS_DIR")
    if override:
        return Path(override)
    return _REPO_SEED_DIR
