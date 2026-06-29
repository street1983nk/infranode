"""Stadt-Zuordnung der Auftragsvergabe in der Normalisierungs-Lib (TENDER-03).

Plan-21-02-Artefakt: eine reine, deterministische Stadt-Zuordnungsfunktion in
der Normalisierungs-Bibliothek. Die eigentliche Matching-Logik lebt als die EINE
Quelle der Wahrheit in :mod:`infranode.tenders.matching` (REST-Regel 6, keine
Duplikate); dieses Modul stellt die in der Normalisierungs-Lib erwartete
Signatur ``match_tender_cities(buyer_address, place_addresses)`` bereit und
lädt dafür den Geo-Crosswalk-Seed (``tender_geo_crosswalk.json``) lazy +
gecacht über ``seeds_dir()`` (analog reiner Mapper-Seed-Load).

Reinheit: kein I/O außer dem einmaligen, gecachten Seed-Load; kein
``httpx``/``now()``/Logging. Die NUTS-3-/PLZ-Crosswalk-Maps und der
Register-Name-Fallback sind die einzige Auflösungsbasis (fail-closed:
mehrdeutige/unbekannte Adresse -> kein Treffer, T-21-MISMATCH).
"""

from __future__ import annotations

import json
from functools import lru_cache

from infranode.infra.seeds import seeds_dir
from infranode.tenders.matching import match_tender_cities as _match

__all__ = ["load_tender_crosswalk", "match_tender_cities"]

# Seed-Dateiname der NUTS-3-/PLZ-Crosswalk-Maps (Plan 21-01).
_CROSSWALK_SEED = "tender_geo_crosswalk.json"


@lru_cache(maxsize=1)
def load_tender_crosswalk() -> dict:
    """Laedt die NUTS-3-/PLZ-Crosswalk-Maps lazy + gecacht über ``seeds_dir()``.

    Einmaliger Seed-Load (Modul-Cache, analog ``ingest.delfi._ags8_to_slug``):
    ``data/seeds/tender_geo_crosswalk.json`` = ``{"nuts3": {...}, "plz_prefix":
    {...}, "_meta": {...}}``. Reiner Lese-Load, keine weiteren Seiteneffekte.
    """
    path = seeds_dir() / _CROSSWALK_SEED
    return json.loads(path.read_text(encoding="utf-8"))


def match_tender_cities(
    buyer_address: dict | None,
    place_addresses: list[dict],
) -> dict[str, list[str]]:
    """Bildet Buyer-Adresse + Erfüllungsorte auf ``slug -> sortierte matches`` ab.

    Reine Funktion in der Normalisierungs-Lib. Löst die Buyer-Adresse
    (-> ``buyer_city``) und jede Erfüllungsort-Adresse
    (-> ``place_of_performance``) getrennt gegen die Crosswalk-Maps + den
    Register-Name-Fallback auf; beide matches sind möglich. Je Slug werden die
    matches dedupliziert und sortiert. Fail-closed: unauflösbare Adressen
    tragen nichts bei (kein falscher Treffer).

    Delegiert an die eine Quelle der Wahrheit
    (:func:`infranode.tenders.matching.match_tender_cities`) mit dem
    lazy-geladenen Crosswalk-Seed.
    """
    return _match(buyer_address, place_addresses, load_tender_crosswalk())
