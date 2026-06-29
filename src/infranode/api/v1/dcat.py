"""DCAT-AP-Katalog-Endpunkt ``/api/v1/catalog.jsonld`` (EU-Harvesting).

Liefert einen maschinenlesbaren DCAT-AP-Katalog (JSON-LD) der von InfraNode
bereitgestellten Datensätze. Ziel: von ``data.europa.eu`` / GovData / sonstigen
CKAN-Harvestern indexierbar machen, ohne dass InfraNode selbst eine öffentliche
Stelle sein muss (der Katalog beschreibt die *Distributionen* = API-Endpunkte +
die offen lizenzierten Bulk-Snapshots auf Zenodo/Hugging Face).

Bewusst KEINE neue RDF-Dependency: JSON-LD ist Teil von DCAT-AP und wird hier als
reines dict serialisiert. Die kuratierten Datensatz-Definitionen liegen in
``dcat_datasets.json`` (neben diesem Modul, einmal beim Import gelesen wie
``openapi.py`` die Spec liest). Lizenz-URL wird aus dem hier gepflegten
``_LICENSE_URI`` und die Attribution aus ``sources.SOURCE_LICENSE`` abgeleitet
(Single Source of Truth, kein Duplizieren von Lizenztexten).

Die Route ist ``include_in_schema=False`` (wie ``openapi.py``): der Katalog ist ein
eigenes JSON-LD-Dokument, kein Teil des Daten-Envelopes, und soll nicht in
``/openapi.json`` bzw. den Drift-Detektor geraten.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import Response

from infranode.api.v1.sources import SOURCE_LICENSE

router = APIRouter()

BASE = "https://infranode.dev/api/v1"
HOMEPAGE = "https://infranode.dev"
PUBLISHER_NAME = "InfraNode"

# EU-Daten-Themen-Vokabular (Authority-Table publications.europa.eu).
_THEME = "http://publications.europa.eu/resource/authority/data-theme/{}"
GERMANY = "http://publications.europa.eu/resource/authority/country/DEU"
_FILE_TYPE = "http://publications.europa.eu/resource/authority/file-type/{}"

# Kuratierte Datensatz-Definitionen (Topic-Granularität) ausgelagert, damit die
# langen mehrsprachigen Texte nicht der Python-Zeilenlänge unterliegen.
_DATA_PATH = Path(__file__).parent / "dcat_datasets.json"
_DATA = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
_DATASETS: list[dict] = _DATA["datasets"]
_SNAPSHOT_DISTRIBUTIONS: list[dict] = _DATA["snapshot_distributions"]

# license_id (String wie in SOURCE_LICENSE) -> (Label, URI). Spiegelt
# manifest._SPDX_MAP + ergänzt die Nicht-Tier-A-Fälle (odbl/gemeinfrei), die im
# Katalog ehrlich ausgewiesen werden. unknown/mixed -> keine Lizenz-URI.
_LICENSE_URI: dict[str, tuple[str, str]] = {
    "cc0": ("CC0-1.0", "https://creativecommons.org/publicdomain/zero/1.0/"),
    "cc_by_4_0": ("CC-BY-4.0", "https://creativecommons.org/licenses/by/4.0/"),
    "dl_de_by_2_0": ("DL-DE-BY-2.0", "https://www.govdata.de/dl-de/by-2-0"),
    "dl_de_zero_2_0": ("DL-DE-ZERO-2.0", "https://www.govdata.de/dl-de/zero-2-0"),
    "geonutzv": (
        "GeoNutzV",
        "https://www.dwd.de/DE/service/rechtliche_hinweise/rechtliche_hinweise.html",
    ),
    "gemeinfrei": (
        "Public Domain",
        "https://creativecommons.org/publicdomain/zero/1.0/",
    ),
    "odbl": ("ODbL-1.0", "https://opendatacommons.org/licenses/odbl/1-0/"),
}


def _publisher() -> dict:
    return {
        "@type": "foaf:Agent",
        "foaf:name": PUBLISHER_NAME,
        "foaf:homepage": {"@id": HOMEPAGE},
    }


def _lang(de: str, en: str) -> list[dict]:
    """DCAT-AP-Mehrsprachigkeit als JSON-LD language-tagged Literale."""
    return [{"@value": de, "@language": "de"}, {"@value": en, "@language": "en"}]


def _license_node(license_id: str) -> dict | None:
    entry = _LICENSE_URI.get(license_id)
    if not entry:
        return None
    label, uri = entry
    return {"@id": uri, "@type": "dct:LicenseDocument", "rdfs:label": label}


def _dataset_node(d: dict) -> dict:
    src = SOURCE_LICENSE.get(d["source"], {})
    license_id = src.get("license_id", "")
    attribution = src.get("attribution", "")
    access = f"{BASE}/cities/{{slug}}/{d['endpoint']}"
    license_node = _license_node(license_id)
    distribution = {
        "@type": "dcat:Distribution",
        "dct:title": _lang(
            f"InfraNode API: /cities/{{slug}}/{d['endpoint']}",
            f"InfraNode API: /cities/{{slug}}/{d['endpoint']}",
        ),
        "dcat:accessURL": {"@id": access},
        "dct:format": {"@id": _FILE_TYPE.format("JSON")},
        "dcat:mediaType": "application/json",
        "dct:conformsTo": {"@id": f"{BASE}/openapi.yaml"},
    }
    if license_node:
        distribution["dct:license"] = license_node
    node = {
        "@type": "dcat:Dataset",
        "@id": f"{HOMEPAGE}/catalog/{d['id']}",
        "dct:identifier": d["id"],
        "dct:title": _lang(d["title_de"], d["title_en"]),
        "dct:description": _lang(d["desc_de"], d["desc_en"]),
        "dcat:theme": [{"@id": _THEME.format(d["theme"])}],
        "dcat:keyword": d["keywords"],
        "dct:spatial": {"@id": GERMANY},
        "dct:publisher": _publisher(),
        "dct:accrualPeriodicity": {
            "@id": "http://publications.europa.eu/resource/authority/frequency/CONT"
        },
        "dcat:distribution": [distribution],
    }
    if license_node:
        node["dct:license"] = license_node
    if attribution:
        node["dct:rights"] = attribution
    return node


def _snapshot_dataset() -> dict:
    dists = []
    for s in _SNAPSHOT_DISTRIBUTIONS:
        label, uri = s["license"]
        dists.append(
            {
                "@type": "dcat:Distribution",
                "dct:title": _lang(s["title"], s["title"]),
                "dcat:accessURL": {"@id": s["accessURL"]},
                "dcat:downloadURL": {"@id": s["accessURL"]},
                "dct:format": {"@id": _FILE_TYPE.format("CSV")},
                "dcat:mediaType": s["mediaType"],
                "dct:license": {
                    "@id": uri,
                    "@type": "dct:LicenseDocument",
                    "rdfs:label": label,
                },
            }
        )
    return {
        "@type": "dcat:Dataset",
        "@id": f"{HOMEPAGE}/catalog/german-cities-snapshot",
        "dct:identifier": "german-cities-snapshot",
        "dct:title": _lang(
            "InfraNode Querschnitt deutscher Staedte (Open-Data-Snapshot)",
            "InfraNode German Cities Open-Data Snapshot",
        ),
        "dct:description": _lang(
            "Reproduzierbarer, offen lizenzierter Querschnitt offener Daten fuer "
            "deutsche Staedte (Stammdaten, Wetter, Luftqualitaet u.a.), CSV/Parquet.",
            "Reproducible, openly licensed cross-section of open data for German "
            "cities (base data, weather, air quality and more), as CSV/Parquet.",
        ),
        "dcat:theme": [{"@id": _THEME.format("REGI")}],
        "dcat:keyword": ["open data", "Germany", "cities", "Staedte", "snapshot"],
        "dct:spatial": {"@id": GERMANY},
        "dct:publisher": _publisher(),
        "dcat:distribution": dists,
    }


def build_catalog() -> dict:
    """Baut den DCAT-AP-Katalog als JSON-LD-Dokument (reine Funktion, testbar)."""
    datasets = [_dataset_node(d) for d in _DATASETS]
    datasets.append(_snapshot_dataset())
    return {
        "@context": {
            "dcat": "http://www.w3.org/ns/dcat#",
            "dct": "http://purl.org/dc/terms/",
            "foaf": "http://xmlns.com/foaf/0.1/",
            "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
        },
        "@type": "dcat:Catalog",
        "@id": f"{HOMEPAGE}/catalog",
        "dct:title": _lang(
            "InfraNode Open-Data-Katalog deutscher Staedte",
            "InfraNode Open Data Catalogue for German cities",
        ),
        "dct:description": _lang(
            "DCAT-AP-Katalog der ueber die InfraNode-API bereitgestellten offenen "
            "Datensaetze deutscher Staedte. InfraNode buendelt amtliche offene "
            "Quellen (DWD, UBA, BNetzA, BORIS, Destatis u.a.) hinter einer "
            "einheitlichen, keylosen REST-API; je Datensatz sind Quelle, Lizenz "
            "und Pflicht-Attribution ausgewiesen.",
            "DCAT-AP catalogue of the open datasets for German cities provided via "
            "the InfraNode API. InfraNode bundles official open sources (DWD, UBA, "
            "BNetzA, BORIS, Destatis and others) behind one keyless REST API; each "
            "dataset states its source, license and required attribution.",
        ),
        "dct:publisher": _publisher(),
        "foaf:homepage": {"@id": HOMEPAGE},
        "dct:language": [
            {"@id": "http://publications.europa.eu/resource/authority/language/DEU"},
            {"@id": "http://publications.europa.eu/resource/authority/language/ENG"},
        ],
        "dcat:dataset": datasets,
    }


@router.get("/catalog.jsonld", include_in_schema=False)
async def catalog_jsonld() -> Response:
    """Liefert den DCAT-AP-Katalog als JSON-LD (EU-Harvesting, kein Envelope)."""
    body = json.dumps(build_catalog(), ensure_ascii=False, indent=2)
    return Response(body, media_type="application/ld+json")
