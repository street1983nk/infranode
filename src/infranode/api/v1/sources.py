"""Source-Status-Route /sources (API-03).

Listet je bekannter Upstream-Quelle ihren ``enabled``-Zustand (aus den
``enable_*``-Settings) und den Circuit-Breaker-State (CLOSED/OPEN/HALF_OPEN aus
der prozessweiten ``app.state.breakers``-Registry). So sehen Clients und Agenten
auf einen Blick, welche Quelle aktiv ist und ob ihr Breaker getrippt hat
(Graceful-Degradation-Transparenz).

Der Breaker wird ueber die bestehende ``BreakerRegistry`` lazy angelegt; ein noch
nie aufgerufener Breaker meldet seinen Default-State CLOSED. KEINE eigene
HTTPException/try-except mit Detail-Leak: der zentrale Handler bleibt zustaendig.
"""

from __future__ import annotations

from asgi_correlation_id import correlation_id
from fastapi import APIRouter, Depends, Request, Response

from infranode.api.v1.pagination import PageParams, page_params, paginate
from infranode.api.v1.ratelimit import ANON_LIMIT, limiter

router = APIRouter()

# Whitelist der sortier-/filterbaren Felder fuer /sources (T-11-FILTER-INJ): nur
# diese Feldnamen sind als sort erlaubt, ein unbekanntes Feld -> 400, BEVOR roher
# User-String interpretiert wird (nie in eine Query/einen Cache-Key interpoliert).
_SOURCES_SORT_WHITELIST = {"source", "enabled", "license"}

# Bekannte Quellen, deren enable_*-Flag in den Settings existiert (config.py).
# wikidata ist die erste verdrahtete Quelle (Phase 4); die uebrigen folgen ab
# Phase 5/6, ihr Toggle ist aber bereits gesetzt.
# Hinweis Phase 7: getattr nutzt enable_lhp (nicht enable_hochwasser); die Quelle
# heisst im _KNOWN_SOURCES-Tuple und im Toggle "lhp", die SourceId-Enum aber
# HOCHWASSER="hochwasser" (Quellen-/Toggle-Name lhp, License-/Record-Tag hochwasser).
_KNOWN_SOURCES = (
    "wikidata",
    "openaq",
    "dwd",
    "overpass",
    "autobahn",
    "hvv",
    "delfi",
    "bnetza",
    "uba",
    "pegelonline",
    "lhp",
    "dwd_pollen",
    # Phase 8: Name MUSS exakt zum enable_<name>-Toggle (config.py) passen.
    "genesis",
    "zensus",
    "mastr",
    "bkg",
    "bundeswahl",
    "divi",
    "feiertage",
    # Phase 9: Name MUSS exakt zum enable_<name>-Toggle (config.py) passen.
    # "X von 28"-Abdeckung (DATA-15) entsteht durch dieses erweiterte Tuple.
    "berlin_viz",
    "hamburg_baustellen",
    "koeln_verkehr",
    "muenchen_baustellen",
    "mobidata_bw",
    "autobahn_webcam",
    # Phase 10: Stadt-Events. Name MUSS exakt zum enable_<name>-Toggle (config.py)
    # passen. destination_one ist account-gated (licensekey), koeln_events keylos.
    "destination_one",
    "koeln_events",
    # Phase 20: Live-Quellen ueber den Mobilithek-mTLS-Pull (getrennte /live-
    # Kategorie). Name MUSS exakt zum enable_<name>-Toggle (config.py) UND zum
    # SourceId-Wert (enums.py) passen: getattr(settings, f"enable_{name}").
    "koeln_traffic_flow",
    "koeln_baustellen_live",
    "koeln_ereignisse_live",
    "koeln_lez_live",
    "berlin_verkehrsmeldungen",
    "dortmund_parking",
    "kiel_zaehlstellen",
    "eround_charging",
    # Phase 19: GTFS-Realtime Trip Updates (Live-ÖPNV). Name MUSS exakt zum
    # enable_<name>-Toggle (config.py) UND zum SourceId-Wert (enums.py) passen:
    # getattr(settings, f"enable_gtfs_rt").
    "gtfs_rt",
    # DATA-24: HVV-Geofox-GTI Live-Abfahrten (Hamburg). Name == enable_hvv_geofox
    # (config.py) == SourceId.HVV_GEOFOX (enums.py).
    "hvv_geofox",
)


# Lizenz + wortgenaue Attribution je Quelle (API-02, GOV-03). Single source of
# truth, VERBATIM aus DATA-LICENSES.md uebernommen: license_id + die dort
# verbindlichen Attribution-Wortlaute. Die deutschen Umlaute sind Teil der Prosa-
# Wortlaute und MUESSEN exakt wie in DATA-LICENSES.md stehen (kein ASCII-Ersatz),
# sonst bricht der Wortlaut-Gleichheits-Test (T-11-SRC-DRIFT). Jeder
# _KNOWN_SOURCES-Eintrag hat genau einen Eintrag (Vollstaendigkeit erzwungen
# durch tests/unit/test_source_license_map.py).
#
# Sonderfaelle (wie in DATA-LICENSES.md dokumentiert):
# - openaq -> "unknown" (Tier C live-only, heterogene Provider-Lizenz je Station).
# - destination_one -> "mixed": die Lizenz wird PRO Datensatz aus dem schema.org-
#   Lizenzfeld abgeleitet (cc0/cc_by_4_0/cc_by_sa_4_0/unknown via map_license),
#   nicht pauschal getaggt. Hier nur der quellenweite Hinweis.
# - feiertage -> "gemeinfrei" (keine schoepfungshoehefaehige Datenbank).
SOURCE_LICENSE: dict[str, dict[str, str]] = {
    "wikidata": {"license_id": "cc0", "attribution": "Wikidata"},
    "openaq": {"license_id": "unknown", "attribution": "OpenAQ"},
    "dwd": {
        "license_id": "geonutzv",
        "attribution": "Datenbasis: Deutscher Wetterdienst, eigene Elemente ergänzt",
    },
    "overpass": {
        "license_id": "odbl",
        "attribution": "© OpenStreetMap contributors",
    },
    "autobahn": {
        "license_id": "dl_de_by_2_0",
        "attribution": "Bundesanstalt für Straßenwesen (BASt) / Autobahn GmbH",
    },
    "hvv": {
        "license_id": "dl_de_by_2_0",
        "attribution": "Hamburger Verkehrsverbund GmbH (HVV)",
    },
    "delfi": {
        "license_id": "cc_by_4_0",
        "attribution": (
            "Datenquelle: DELFI e.V. / Mobilitätsdaten Deutschland, CC-BY 4.0"
        ),
    },
    "bnetza": {
        "license_id": "cc_by_4_0",
        "attribution": "Bundesnetzagentur.de",
    },
    "uba": {
        "license_id": "dl_de_by_2_0",
        "attribution": "Umweltbundesamt (UBA)",
    },
    "pegelonline": {
        "license_id": "dl_de_zero_2_0",
        "attribution": (
            "PEGELONLINE, Wasserstraßen- und Schifffahrtsverwaltung des Bundes (WSV)"
        ),
    },
    "lhp": {
        "license_id": "cc_by_4_0",
        "attribution": "Datenquelle: www.hochwasserzentralen.de, Stand: <Zeitstempel>",
    },
    "dwd_pollen": {
        "license_id": "geonutzv",
        "attribution": "Datenbasis: Deutscher Wetterdienst, eigene Elemente ergänzt",
    },
    "genesis": {
        "license_id": "dl_de_by_2_0",
        "attribution": "Statistisches Bundesamt (Destatis) / Regionalstatistik",
    },
    "zensus": {
        "license_id": "dl_de_by_2_0",
        "attribution": "Statistisches Bundesamt (Destatis) / Regionalstatistik",
    },
    "mastr": {
        "license_id": "dl_de_by_2_0",
        "attribution": "Bundesnetzagentur - Marktstammdatenregister",
    },
    "bkg": {
        "license_id": "dl_de_by_2_0",
        "attribution": "(c) GeoBasis-DE / BKG (Jahr)",
    },
    "bundeswahl": {
        "license_id": "dl_de_by_2_0",
        "attribution": "Die Bundeswahlleiterin",
    },
    "divi": {
        "license_id": "cc_by_4_0",
        "attribution": (
            "Robert Koch-Institut (RKI), DIVI-Intensivregister, Stand: <datum>"
        ),
    },
    "feiertage": {
        "license_id": "gemeinfrei",
        "attribution": "Feiertage und Schulferien je Bundesland, gemeinfrei",
    },
    "berlin_viz": {
        "license_id": "dl_de_by_2_0",
        "attribution": "Verkehrsinformationszentrale Berlin (VIZ)",
    },
    "hamburg_baustellen": {
        "license_id": "dl_de_by_2_0",
        "attribution": "Freie und Hansestadt Hamburg",
    },
    "koeln_verkehr": {
        "license_id": "dl_de_by_2_0",
        "attribution": "Stadt Köln",
    },
    "muenchen_baustellen": {
        "license_id": "dl_de_by_2_0",
        "attribution": "Landeshauptstadt München",
    },
    "mobidata_bw": {
        "license_id": "dl_de_by_2_0",
        "attribution": "Verkehrsministerium Baden-Württemberg / MobiData BW",
    },
    "autobahn_webcam": {
        "license_id": "dl_de_by_2_0",
        "attribution": "Bundesanstalt für Straßenwesen (BASt) / Autobahn GmbH",
    },
    "destination_one": {
        "license_id": "mixed",
        "attribution": "destination.one",
    },
    "koeln_events": {
        "license_id": "dl_de_by_2_0",
        "attribution": "Stadt Köln",
    },
    # Phase 20 Live-Quellen (Mobilithek-mTLS-Pull). Stadt-Verkehrsquellen
    # DL-DE/BY 2.0 mit traegergenauer Attribution. eRound: license_id "unknown"
    # bis Plan 07 die Lizenz am realen Abo verifiziert (NICHT pauschal Tier A,
    # GOV-02/04). Umlaute exakt (kein ASCII-Ersatz, T-11-SRC-DRIFT).
    "koeln_traffic_flow": {
        "license_id": "dl_de_by_2_0",
        "attribution": "Stadt Köln",
    },
    "koeln_baustellen_live": {
        "license_id": "dl_de_by_2_0",
        "attribution": "Stadt Köln",
    },
    "koeln_ereignisse_live": {
        "license_id": "dl_de_by_2_0",
        "attribution": "Stadt Köln",
    },
    "koeln_lez_live": {
        "license_id": "dl_de_by_2_0",
        "attribution": "Stadt Köln",
    },
    "berlin_verkehrsmeldungen": {
        "license_id": "dl_de_by_2_0",
        "attribution": (
            "Senatsverwaltung für Mobilität, Verkehr, Klimaschutz und Umwelt (SenMVKU)"
        ),
    },
    "dortmund_parking": {
        "license_id": "dl_de_by_2_0",
        "attribution": "Stadt Dortmund",
    },
    "kiel_zaehlstellen": {
        "license_id": "dl_de_by_2_0",
        "attribution": "Landeshauptstadt Kiel",
    },
    # eRound: Lizenz am realen Abo verifiziert (Mobilithek-Portal 2026-06-12,
    # Angebot 961629419076456448, Tab Nutzungsbedingungen): Standard-Lizenz
    # Creative Commons CC Zero -> license_id "cc0" (Tier A, Plan 20-07,
    # Checkpoint cc0-tier-a). CC0 verlangt keine Attribution; Projekt-Konvention
    # fuehrt sie dennoch konsistent.
    "eround_charging": {
        "license_id": "cc0",
        "attribution": "Hamburger Energienetze GmbH / eRound",
    },
    # Phase 19: GTFS-Realtime Trip Updates. CC-BY-SA = Tier B (copyleft, strikt
    # vom Tier-A-Archiv getrennt, KEIN append_record). Die quellenweite Zeile
    # traegt die Primaerquelle gtfs.de; ein Mobilithek-DELFI-Quellenwechsel wuerde
    # je Record "DELFI e.V." attribuieren, die SOURCE_LICENSE-Zeile bleibt aber
    # gtfs.de = Primaerquelle (T-11-SRC-DRIFT, Umlaute exakt).
    "gtfs_rt": {
        "license_id": "cc_by_sa_4_0",
        "attribution": "gtfs.de",
    },
    # DATA-24: HVV-Geofox-GTI Live-Abfahrten. Tier C live-only: die Geofox-Lizenz
    # ist nicht offen (registrierungspflichtige API), daher "unknown" (analog
    # openaq), reine Live-Anzeige, kein Archiv/Weitergabe.
    "hvv_geofox": {
        "license_id": "unknown",
        "attribution": "Hamburger Verkehrsverbund GmbH (HVV) / Geofox",
    },
}


@router.get("/sources")
@limiter.limit(ANON_LIMIT)
async def sources(
    request: Request,
    response: Response,
    page: PageParams = Depends(page_params),  # noqa: B008 - FastAPI-Dependency-Idiom
) -> dict:
    """Listet je Quelle enabled (aus den Settings) + Breaker-State (API-03).

    Rate-limitiert (API-06): @limiter.limit unter @router.get, ``request`` ist
    Pflicht-Param (Pitfall 4). ``response`` ist Pflicht, damit slowapi die
    Standard-RateLimit-Header auf die Erfolgsantwort injizieren kann; bei
    Ueberschreitung greift der 429-Envelope-Handler.

    Keylos/offen: kein API-Key noetig, das IP-Limit (ANON_LIMIT) gilt fuer alle.

    Paginiert (API-04, REST-Best-Practice #3/#8): ``Depends(page_params)`` liest
    page/limit/offset/sort/order; ``paginate`` schneidet die Seite Whitelist-
    gesichert (unbekanntes sort -> 400, T-11-FILTER-INJ) und liefert bei Offset-
    Overflow eine leere Liste mit 200 (nie 500). ``limit > MAX_LIMIT`` wird ueber
    ``Query(le=MAX_LIMIT)`` als 422 abgewiesen.
    """
    settings = request.app.state.settings
    breakers = request.app.state.breakers

    data = [
        {
            "source": name,
            "enabled": bool(getattr(settings, f"enable_{name}", False)),
            "breaker_state": breakers.get(name).state.value,
            "license": SOURCE_LICENSE.get(name, {}).get("license_id"),
            "attribution": SOURCE_LICENSE.get(name, {}).get("attribution"),
        }
        for name in _KNOWN_SOURCES
    ]

    # Whitelist-gesicherte Sortierung VOR dem Slice (sort nur aus der Whitelist,
    # sonst 400 in paginate). order steuert die Richtung, beides ist validiert.
    if page.sort:
        data.sort(
            key=lambda row: (row.get(page.sort) is None, row.get(page.sort)),
            reverse=(page.order == "desc"),
        )

    page_items = paginate(data, page, sort_whitelist=_SOURCES_SORT_WHITELIST)
    return {
        "data": page_items,
        "meta": {
            "correlation_id": correlation_id.get(),
            "page": page.page,
            "limit": page.limit,
            "offset": page.offset,
            "total": len(data),
        },
    }
