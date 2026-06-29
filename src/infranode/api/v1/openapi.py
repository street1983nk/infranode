"""OpenAPI-YAML-Auslieferungsroute /openapi.yaml (API-09, design-first).

FastAPI serviert das generierte Schema intern nur als JSON unter /openapi.json.
Die stabile, design-first gepflegte Spec liegt als ``docs/openapi.yaml`` im Repo
(REST-Regel 11) und wird hier unverändert als ``application/yaml`` ausgeliefert.

Sicherheit (T-04-10): ``_SPEC`` ist eine hartkodierte Konstante ohne
User-Input-Anteil (kein Pfad-Parameter -> kein Path-Traversal). ``include_in_schema
=False`` hält die Route aus dem generierten Schema heraus (keine Rekursion in
/openapi.json bzw. den Drift-Detektor).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import Response

router = APIRouter()

# Hartkodierter Pfad zur design-first-Spec (kein User-Input, T-04-10). Die Spec
# ist statisch; sie wird einmal beim Import gelesen (kein blockierendes
# Datei-I/O je Request, ruff ASYNC240) und unverändert ausgeliefert.
_SPEC_PATH = Path("docs/openapi.yaml")
_SPEC_TEXT = _SPEC_PATH.read_text(encoding="utf-8")


@router.get("/openapi.yaml", include_in_schema=False)
async def openapi_yaml() -> Response:
    """Liefert die design-first OpenAPI-Spec als YAML (API-09)."""
    return Response(_SPEC_TEXT, media_type="application/yaml")
