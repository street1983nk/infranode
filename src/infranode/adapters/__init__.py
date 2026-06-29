"""Quellen-Adapter: keylose/leichte Upstream-Fetcher (DATA-01).

Re-exportiert die öffentliche Adapter-API. Jeder Adapter lädt eine Upstream-
Quelle und liefert ein flaches raw-dict, das der zugehörige reine Mapper aus
der Normalisierungs-Library erwartet. Der Adapter koppelt NICHT an Pydantic und
kennt KEIN Cache/Breaker (das liefert die Resilienz-Fassade). Muster analog
``infranode.normalization`` (Paket-__init__ re-exportiert die öffentliche API).
"""

from __future__ import annotations

from infranode.adapters.autobahn import fetch_traffic
from infranode.adapters.dwd import fetch_weather
from infranode.adapters.overpass import fetch_pois
from infranode.adapters.wikidata import fetch_city_base

__all__ = [
    "fetch_city_base",
    "fetch_pois",
    "fetch_traffic",
    "fetch_weather",
]
