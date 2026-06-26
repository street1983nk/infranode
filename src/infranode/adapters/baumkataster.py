"""Keyloser Baumkataster-WFS-Adapter fetch_trees (DATA-OSM-Tier-2, Baumkataster).

Staedtische Baumkataster sind KOMMUNALES Open Data: jede Stadt fuehrt ihr eigenes
Kataster, meist als WFS. Es gibt keinen bundesweiten Endpunkt. Der Adapter ist
daher per STADT konfiguriert: ``BAUM_WFS`` mappt einen Stadt-Slug auf eine WFS-
Konfiguration (analog zur foederierten ``DENKMAL_WFS``, dort je Bundesland).

Stand: Berlin (verifiziert, GeoJSON-WFS, DL-DE/Zero 2.0; ~900k Strassenbaeume).
Weitere Staedte (Hamburg/Koeln/Frankfurt) folgen nach WFS-Verifikation.

Groessenschutz: Kataster sind sehr gross (Berlin > 900.000 Baeume); ``count``
cappt die je Anfrage geladene Feature-Zahl (Stichprobe, kein Vollabzug). Die
Antwort liefert je Baum den Punkt + ausgewaehlte Attribute (Art, Pflanzjahr,
Hoehe, Strasse, Bezirk).

Sicherheit (T-SSRF): Host + typeName stammen ausschliesslich aus der hartkodierten
``BAUM_WFS``-Registry (KEIN User-Input). Rein (kein Cache/Breaker, das liefert die
Fassade); ``resp.raise_for_status()`` ist Pflicht (STALE-ON-ERROR).
"""

from __future__ import annotations

from typing import NamedTuple

import httpx

# Obergrenze der je Anfrage geladenen Baum-Features (Groessen-/DoS-Schutz). Kataster
# sind sehr gross -> bewusste Stichprobe, in der Doku als gedeckelt gekennzeichnet.
_COUNT_CAP = 500


class BaumSource(NamedTuple):
    """WFS-Konfiguration eines staedtischen Baumkatasters."""

    url: str
    typename: str
    fields: tuple[str, ...]
    license_id: str
    license_tier: str
    attribution: str


# Stadt-Slug -> WFS-Konfiguration. Nur verifizierte, offen lizenzierte Staedte
# (fail-closed). Berlin: GetCapabilities + Lizenz (DL-DE/Zero 2.0) verifiziert
# 2026-06-26 (Fees-Feld der Capabilities).
BAUM_WFS: dict[str, BaumSource] = {
    "berlin": BaumSource(
        url="https://gdi.berlin.de/services/wfs/baumbestand",
        typename="baumbestand:strassenbaeume",
        fields=(
            "art_dtsch",
            "art_bot",
            "gattung_deutsch",
            "pflanzjahr",
            "baumhoehe",
            "strname",
            "bezirk",
        ),
        license_id="dl_de_zero_2_0",
        license_tier="A",
        attribution="Geoportal Berlin / Straßen- und Anlagenbaumbestand",
    ),
}


async def fetch_trees(
    http: httpx.AsyncClient,
    *,
    slug: str,
) -> dict:
    """Holt das staedtische Baumkataster per WFS GetFeature (GeoJSON, WGS84).

    ``slug`` waehlt die WFS-Konfiguration; eine nicht abgedeckte Stadt loest ein
    ``KeyError`` aus (die Route prueft jedoch vorher ``is_covered`` und liefert
    dann ``not_covered``). Rueckgabe-Keys (das, was ``map_trees`` erwartet):
    ``slug``, ``fields``, ``license_id``/``license_tier``/``attribution`` und
    ``features`` (rohe GeoJSON-Features, gedeckelt auf ``_COUNT_CAP``).
    """
    src = BAUM_WFS[slug]
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": src.typename,
        "count": str(_COUNT_CAP),
        "outputFormat": "application/json",
        "srsName": "EPSG:4326",
    }
    resp = await http.get(src.url, params=params)
    resp.raise_for_status()
    return {
        "slug": slug,
        "fields": list(src.fields),
        "license_id": src.license_id,
        "license_tier": src.license_tier,
        "attribution": src.attribution,
        "features": resp.json().get("features", []),
    }
