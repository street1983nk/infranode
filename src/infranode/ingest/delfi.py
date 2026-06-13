"""Public-Teil von delfi: nur das stop_id->Slug-Mapping (reine Funktion).

Der DELFI-Batch-Ingest (ZIP-Stream + Snapshot-Schreiben) ist privat und
NICHT Teil des oeffentlichen Live-Proxys.
"""

from __future__ import annotations

import re

from infranode.registry import list_cities

_DE_PREFIX = re.compile(r"^de:(\d+):")

# AGS (5-stelliger Kreis-Praefix der amtlichen Gemeindekennziffer) -> Slug,
# vollstaendig aus dem Register abgeleitet (kollisionsfrei, 84 Praefixe).
AGS_TO_SLUG: dict[str, str] = {_e.ags[:5]: _e.slug for _e in list_cities()}


def city_for_stop(stop_id: str) -> str | None:
    """Mappt eine DELFI-stop_id ueber den AGS-Prefix auf einen Slug oder None."""
    m = _DE_PREFIX.match(stop_id)
    if not m:
        return None
    return AGS_TO_SLUG.get(m.group(1))
