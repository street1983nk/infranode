"""Versionierter API-Router /api/v1 (FND-05, REST-Regel 1)."""

from __future__ import annotations

from fastapi import APIRouter

from . import cities, compare, health, live, openapi, sources

api_v1 = APIRouter(prefix="/api/v1")
api_v1.include_router(health.router, tags=["meta"])
api_v1.include_router(cities.router, tags=["cities"])
api_v1.include_router(sources.router, tags=["meta"])
api_v1.include_router(openapi.router, tags=["meta"])
api_v1.include_router(compare.router, tags=["compare"])
# Phase 20: getrennte Live-Kategorie (LIVE-01/02/03). Eigener Namespace /live +
# eigener OpenAPI-Tag "Live" (eigene Doku-Sektion). Prefix + Tag werden hier
# gesetzt (analog cities.py), daher liegt der finale Pfad unter /api/v1/live/...
api_v1.include_router(live.router, prefix="/live", tags=["Live"])
