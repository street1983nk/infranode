"""Kanonische Enums der Normalisierungs-Library (CORE-01).

Definiert die festen Wertebereiche für Lizenz-Tier, Lizenz-ID und Quelle als
``StrEnum``. ``StrEnum`` serialisiert verlustfrei zu JSON-Strings und dient als
Pflicht-Anker für die tier-getrennte Datenhaltung (GOV-Fundament): kein
Datensatz darf ohne korrektes Tier-Tag ins System gelangen.
"""

from __future__ import annotations

from enum import StrEnum


class LicenseTier(StrEnum):
    """Lizenz-Tier zur tier-getrennten Datenhaltung (GOV-Fundament).

    Kennzeichnet (GOV-02/04) die Lizenz je Datensatz für korrekte Attribution
    und Weiternutzung, ohne das Schema zu ändern. Pflichtfeld am Envelope, damit
    kein Datensatz ohne Tier durchrutscht.
    """

    A = "A"  # permissiv (CC0, CC-BY, DL-DE/BY, DL-DE/Zero, GeoNutzV)
    B = "B"  # copyleft (ODbL, CC-BY-SA): getrennt kennzeichnen
    C = "C"  # live-only (z.B. ParkenDD): nur Live-Anzeige


class LicenseId(StrEnum):
    """Konkrete Lizenz je Datensatz (Attribution- und Tier-Zuordnung)."""

    CC0 = "cc0"
    CC_BY_4_0 = "cc_by_4_0"
    DL_DE_BY_2_0 = "dl_de_by_2_0"
    DL_DE_ZERO_2_0 = "dl_de_zero_2_0"
    GEONUTZV = "geonutzv"
    ODBL = "odbl"
    CC_BY_SA_4_0 = "cc_by_sa_4_0"
    # EU-Wiederverwendungs-Policy (Commission Decision 2011/833/EU, faktisch
    # CC BY 4.0): EU-JRC-Daten wie PVGIS sind frei nutzbar (auch kommerziell), wenn
    # die Quelle genannt wird ("PVGIS © European Communities"). Permissiv = Tier A.
    EC_REUSE = "ec_reuse"
    # Ehrlicher Tag für Quellen mit heterogener/unbekannter Lizenz je Datensatz
    # (z.B. ParkenDD, dessen Lizenz pro Stadt variiert): verhindert ein
    # falsches pauschales CC-BY-Tag im Envelope (GOV-01/03-Compliance).
    UNKNOWN = "unknown"
    # § 5 Abs. 2 UrhG: amtliches Werk, gemeinfrei. Die Weiterverbreitung ist
    # erlaubt, solange der Inhalt UNVERAENDERT bleibt und die Quelle genannt wird
    # (Aenderungsverbot). Faktisch permissiv (auch kommerziell) -> Tier A. Genutzt
    # fuer die amtlichen BBK-NINA-Bevoelkerungsschutz-Warntexte.
    AMTLICHES_WERK = "amtliches_werk"


# Umstellung 2026-08-01 (Stufe 4, Owner-bestätigt): 30 deutsche SourceId-Werte
# tragen seitdem englische Namen. Diese Tabelle (alt -> neu) ist die EINE Quelle
# der Wahrheit für alle Legacy-Leser: SourceId._missing_ (persistierte Bestands-
# Records mit alten Werten, store.py/transit_store.py/export/reader.py) und der
# Archiv-Verzeichnis-Fallback (archive/store.py, export/reader.py). Neue Werte
# werden hier NICHT ergänzt; die Tabelle ist eingefroren.
LEGACY_SOURCE_IDS: dict[str, str] = {
    "hochwasser": "lhp",
    "feiertage": "holidays",
    "hamburg_baustellen": "hamburg_roadworks",
    "muenchen_baustellen": "muenchen_roadworks",
    "dortmund_baustellen": "dortmund_roadworks",
    "rostock_baustellen": "rostock_roadworks",
    "bremen_baustellen": "bremen_roadworks",
    "koeln_baustellen_live": "koeln_roadworks_live",
    "koeln_verkehr": "koeln_road_events",
    "koeln_ereignisse_live": "koeln_incidents_live",
    "berlin_verkehrsmeldungen": "berlin_traffic_reports",
    "hannover_verkehrsmeldungen": "hannover_traffic_reports",
    "hamburg_verkehrslage": "hamburg_traffic_situation",
    "kiel_zaehlstellen": "kiel_counting_stations",
    "muenchen_radzaehl": "muenchen_bike_counts",
    "leipzig_radzaehl": "leipzig_bike_counts",
    "hamburg_radzaehl": "hamburg_bike_counts",
    "berlin_radzaehl": "berlin_bike_counts",
    "stuttgart_radzaehl": "stuttgart_bike_counts",
    "koeln_radzaehl": "koeln_bike_counts",
    "essen_radzaehl": "essen_bike_counts",
    "duesseldorf_radzaehl": "duesseldorf_bike_counts",
    "denkmal": "heritage",
    "baumkataster": "tree_cadastre",
    "koeln_wartezeiten": "koeln_wait_times",
    "muenchen_parkhaeuser": "muenchen_parking",
    "muenchen_parkraum": "muenchen_parking_onstreet",
    "muenchen_park_ride": "muenchen_park_and_ride",
    "muenchen_mobilitaetspunkte": "muenchen_mobility_points",
    "muenchen_radparken": "muenchen_bike_parking",
}


class SourceId(StrEnum):
    """Bekannte Upstream-Quellen, die in das kanonische Schema abgebildet werden.

    Legacy-Leser: persistierte Bestands-Records (JSONL-Archiv, Stores) können
    noch die alten deutschen Werte tragen. ``_missing_`` bildet sie über
    ``LEGACY_SOURCE_IDS`` auf das neue Member ab, damit
    ``CanonicalRecord.model_validate`` weiter funktioniert; NEU geschriebene
    Records tragen ausschließlich die englischen Werte.
    """

    @classmethod
    def _missing_(cls, value: object) -> SourceId | None:
        """Legacy-Alias: alter deutscher Wert -> neues englisches Member."""
        if isinstance(value, str):
            new = LEGACY_SOURCE_IDS.get(value)
            if new is not None:
                return cls(new)
        return None

    WIKIDATA = "wikidata"
    DWD = "dwd"
    OSM = "osm"
    AUTOBAHN = "autobahn"
    BNETZA = "bnetza"
    UBA = "uba"
    DELFI = "delfi"
    HVV = "hvv"
    # Phase 7: Tier-A-Quellen (E-Mobilität und erweiterte Umweltdaten).
    # LHP = Landeshochwasserportale (www.hochwasserzentralen.de); seit 2026-08-01
    # ist Toggle-Name == SourceId-Wert == "lhp" (frueher Record-Tag "hochwasser").
    PEGELONLINE = "pegelonline"
    LHP = "lhp"
    DWD_POLLEN = "dwd_pollen"
    # DWD Waldbrand-/Graslandfeuerindex (keylos, GeoNutzV, Tier A, stationsnah).
    DWD_FIRE = "dwd_fire"
    # EEA Badegewaesserqualitaet (keylos, CC-BY 4.0, Tier A, ortsnah/Umland).
    EEA_BATHING = "eea_bathing"
    # Bundes-Klinik-Atlas (keylos, Lizenz UNKNOWN -> Tier C fail-closed, ortsnah).
    KLINIK_ATLAS = "klinik_atlas"
    # DB FaSta Aufzug-/Rolltreppen-Status (key-gated DB-Marketplace, CC-BY, Tier A).
    DB_FASTA = "db_fasta"
    # Phase 8: Statistik-, Energie- und Geo-Quellen. GENESIS und
    # ZENSUS sind account-gated (POST-API), MASTR/BKG/BUNDESWAHL/HOLIDAYS sind
    # keylose Bulk-/Seed-Quellen. Alle Werte ASCII (StrEnum).
    GENESIS = "genesis"
    ZENSUS = "zensus"
    MASTR = "mastr"
    SMARD = "smard"
    DWD_WARNINGS = "dwd_warnings"
    BKG = "bkg"
    BUNDESWAHL = "bundeswahl"
    HOLIDAYS = "holidays"
    # Phase 9: keylose Stadt-Verkehrs-Quellen (Baustellen/Sperrungen) je Stadt.
    # Alle Werte ASCII (StrEnum), kein Umlaut (Slugs muenchen/koeln). Toggle-Name
    # == SourceId-Wert == _KNOWN_SOURCES-Eintrag. Autobahn-Webcams (DATA-22) am
    # 2026-10-18 ausgebaut (Quelle lieferte bundesweit 0 Items). Kein neuer
    # LicenseId-Wert (alle Phase-9-Quellen sind DL-DE/BY 2.0 = DL_DE_BY_2_0,
    # bereits vorhanden).
    BERLIN_VIZ = "berlin_viz"
    HAMBURG_ROADWORKS = "hamburg_roadworks"
    KOELN_ROAD_EVENTS = "koeln_road_events"
    MUENCHEN_ROADWORKS = "muenchen_roadworks"
    DORTMUND_ROADWORKS = "dortmund_roadworks"
    ROSTOCK_ROADWORKS = "rostock_roadworks"
    # SPERRINFOSYS Sachsen (LISt GmbH): EINE sachsenweite Quelle für Dresden +
    # Leipzig (VKZ-Filter im Adapter), DL-DE/BY 2.0.
    SPERRINFOSYS = "sperrinfosys"
    MOBIDATA_BW = "mobidata_bw"
    # Phase 10: Stadt-Events/Veranstaltungen. DESTINATION_ONE ist die account-
    # gated eT4.META-Quelle (licensekey, gemischte Lizenzen pro Record, GOV-04),
    # KOELN_EVENTS der keylose Köln-Direkt-Feed (fix DL-DE/Zero, D-06). Alle Werte
    # ASCII (StrEnum), kein Umlaut (Slug koeln). Toggle-Name == SourceId-Wert ==
    # _KNOWN_SOURCES-Eintrag. Kein neuer LicenseId-Wert nötig (CC0/CC_BY_4_0/
    # CC_BY_SA_4_0/DL_DE_ZERO_2_0/UNKNOWN existieren bereits).
    DESTINATION_ONE = "destination_one"
    KOELN_EVENTS = "koeln_events"
    # Phase 20: Live-Quellen über den Mobilithek-mTLS-Pull (getrennte /live-
    # Kategorie). Alle Werte ASCII-lowercase, kein Umlaut (Slugs koeln/berlin/
    # dortmund/kiel/eround). Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-
    # Eintrag: getattr(settings, f"enable_{name}"). Kein neuer LicenseId-Wert
    # (DL_DE_BY_2_0/CC0/UNKNOWN existieren; eRound erst nach Lizenz-Verifikation).
    KOELN_TRAFFIC_FLOW = "koeln_traffic_flow"
    KOELN_ROADWORKS_LIVE = "koeln_roadworks_live"
    KOELN_INCIDENTS_LIVE = "koeln_incidents_live"
    KOELN_LEZ_LIVE = "koeln_lez_live"
    BERLIN_TRAFFIC_REPORTS = "berlin_traffic_reports"
    DORTMUND_PARKING = "dortmund_parking"
    KIEL_COUNTING_STATIONS = "kiel_counting_stations"
    EROUND_CHARGING = "eround_charging"
    # Frankfurt am Main Parkdaten (Mobilithek DATEX II V3 Parking, statisch +
    # dynamisch gejoint, DL-DE/BY 2.0 = Tier A). EINZIGE DATEX-II-V3-XML-Quelle
    # (eRound ist V3-JSON, Köln ist V2-XML): eigener V3-XML-Parser
    # (adapters/mobilithek_datex3). Toggle-Name == SourceId-Wert ==
    # _KNOWN_SOURCES-Eintrag: getattr(settings, f"enable_{name}").
    FRANKFURT_PARKING = "frankfurt_parking"
    # Wuppertal Parkdaten (Mobilithek DATEX II V2 ParkingFacility-Profil, statisch
    # + dynamisch gejoint, DL-DE/Zero 2.0 = Tier A). Eigenes V2-Profil
    # (parkingFacilityStatus/-Reference), getrennt vom Köln-parkingStatus-Pfad.
    # Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag.
    WUPPERTAL_PARKING = "wuppertal_parking"
    # Magdeburg Parkdaten (Mobilithek DATEX II V2 ParkingFacility-Profil, statisch
    # + dynamisch gejoint; teilt den Wuppertal-V2-Parser). Anbieter ifak e.V.,
    # Datenquelle Landeshauptstadt Magdeburg -> deren Open-Data-Nutzungsbedingungen
    # legen mangels anderer Kennzeichnung Datenlizenz Deutschland Namensnennung 2.0
    # fest (license_id=dl_de_by_2_0, Tier A; Recherche 2026-06-30, magdeburg.de
    # Offene-Verwaltungsdaten). Toggle-Name == SourceId-Wert.
    MAGDEBURG_PARKING = "magdeburg_parking"
    # Köln Parkdaten (Mobilithek DATEX II V2 ParkingStatusPublication-Light-
    # Profil, statisch + dynamisch gejoint; eigener parkingRecordStatus-Parser,
    # NICHT das Wuppertal-ParkingFacility-Profil; live-verifiziert 2026-07-23).
    # DL-DE/Zero 2.0 = Tier A (Köln-Mobilithek-Bestand, siehe
    # KOELN_TRAFFIC_FLOW-Block). Ersetzt den bei ParkenDD eingefrorenen
    # Köln-Feed (quick-260723-gaq). Toggle-Name == SourceId-Wert ==
    # _KNOWN_SOURCES-Eintrag.
    KOELN_PARKING = "koeln_parking"
    # Phase 19: GTFS-Realtime Trip Updates, Tier B CC-BY-SA, gtfs.de/Mobilithek-
    # DELFI; kein neuer LicenseId-Wert (CC_BY_SA_4_0 existiert bereits), kein
    # Umlaut (StrEnum, ASCII-lowercase). Toggle-Name == SourceId-Wert ==
    # _KNOWN_SOURCES-Eintrag: getattr(settings, f"enable_{name}").
    GTFS_RT = "gtfs_rt"
    # DATA-24: HVV-Geofox-GTI Live-Abfahrten (Hamburg), Tier C live-only
    # (Geofox-Lizenz nicht offen). Eigene SourceId getrennt von HVV (= statische
    # GTFS-Stops). Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag.
    HVV_GEOFOX = "hvv_geofox"
    # DATA-25: VGN/VAG-Nürnberg Live-Abfahrten (Puls-API start.vag.de), Tier A
    # (CC-BY 4.0, offen, opendata.vag.de) -> sauber verwertbar, anders als HVV.
    # Keylos, KEINE Mobilithek. Toggle-Name == SourceId-Wert == _KNOWN_SOURCES.
    VGN = "vgn"
    # Quick-260707-mmi: RMV/Rhein-Main Live-Abfahrten (HAPI/HAFAS-ReST
    # www.rmv.de/hapi, Frankfurt am Main), Tier C live-only. Die Lizenz ist nicht
    # offen (registrierungspflichtiger accessId), analog HVV_GEOFOX -> UNKNOWN,
    # reine Live-Anzeige, KEIN Archiv. accessId ist nur ein Query-Param (KEIN
    # HMAC). Eigene SourceId neben HVV_GEOFOX/VGN.
    RMV = "rmv"
    # Quick-260707-p9c: VRR/Rhein-Ruhr Live-Abfahrten (generischer Mentz-EFA-
    # rapidJSON-Adapter, efa.vrr.de, sechs Kernstaedte Duesseldorf/Dortmund/Essen/
    # Duisburg/Bochum/Wuppertal), Tier C live-only. Keylos, aber die EFA-Lizenz ist
    # nicht klar offen -> UNKNOWN, reine Live-Anzeige, KEIN Archiv (analog HVV_GEOFOX/
    # RMV). Eigene SourceId; der generische EFA-Adapter/Mapper ist ueber base_url/
    # source/attribution parametrisiert (VVS Stuttgart plugt spaeter ein).
    VRR = "vrr"
    # Quick-260708-73a: VVS Stuttgart Live-Abfahrten, die zweite keylose Mentz-EFA-
    # Instanz (base_url www3.vvs.de, rapidJSON, deckt Stuttgart ab). Reine
    # Konfiguration ueber denselben generischen EFA-Adapter/Mapper wie VRR: nur
    # base_url/source/attribution unterscheiden sich. Tier C live-only, EFA-Lizenz
    # nicht klar offen -> UNKNOWN, KEIN Archiv (analog VRR/HVV_GEOFOX/RMV).
    VVS = "vvs"
    # DATA-26: Hamburg-Verkehrslage (Echtzeit-Verkehrsfluss je Straßenabschnitt,
    # OAF/GeoJSON api.hamburg.de), Tier A (DL-DE/BY 2.0, offen, keylos). Anders als
    # HVV_GEOFOX (Tier C, nicht offen) sauber verwertbar. KEINE Mobilithek.
    # Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag.
    HAMBURG_TRAFFIC_SITUATION = "hamburg_traffic_situation"
    # DATA-27: KBA Pkw-Bestand + Elektro-Anteil je Zulassungsbezirk (keylose
    # Bulk-Quelle, DL-DE/BY 2.0, Tier A). Read-only Store-Lesung im Request-Pfad
    # (wie MASTR), kein resilient_client. Toggle-Name == SourceId-Wert ==
    # _KNOWN_SOURCES-Eintrag: getattr(settings, f"enable_{name}").
    KBA = "kba"
    # DATA-29: Unfallatlas (Straßenverkehrsunfälle je Kreis, keylose Bulk-CSV,
    # DL-DE/BY 2.0, Tier A). Read-only Store-Lesung (wie KBA/MASTR), kein
    # resilient_client. Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag.
    UNFALLATLAS = "unfallatlas"
    # DATA-30: Tankerkönig Spritpreise (MTS-K), aggregiert je Stadt. Keyed Live-
    # Quelle (resilient_client), CC-BY 4.0 = Tier A (offen, verwertbar). Toggle-
    # Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag: getattr(settings,
    # f"enable_{name}"); der Key ist ein eigenes SecretStr-Feld.
    TANKERKOENIG = "tankerkoenig"
    # DATA-31: Bremen Baustellen/Arbeitsstellen (Verkehrsmanagementzentrale Bremen,
    # Mobilithek DATEX II V2 SituationPublication, DL-DE/BY 2.0, Tier A). Live-
    # Quelle wie koeln_roadworks_live. Toggle-Name == SourceId-Wert ==
    # _KNOWN_SOURCES-Eintrag.
    BREMEN_ROADWORKS = "bremen_roadworks"
    # Hannover Verkehrsmeldungen (Landeshauptstadt Hannover, Fachbereich Tiefbau,
    # Mobilithek DATEX II V2 SituationPublication: Baustellen/Veranstaltungen/
    # Verkehrsstörungen, Mobilithek-Angebot "freie Nutzung/Open Data" = DL-DE/BY
    # 2.0 = Tier A, analog Bremen/Berlin). Live-Quelle wie bremen_roadworks.
    # Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag.
    HANNOVER_TRAFFIC_REPORTS = "hannover_traffic_reports"
    # DATA-33: GBFS-Bike-/Scooter-Sharing je Stadt (Live, aggregiert). Primär
    # Nextbike (CC0 = Tier A); je System wird die Lizenz aus GBFS
    # ``system_information.license_id`` fail-closed gegen eine Tier-A-Allowlist
    # geprüft (GOV-02/04). Keyed-los, resilient_client. Toggle-Name == SourceId-
    # Wert == _KNOWN_SOURCES-Eintrag: getattr(settings, f"enable_{name}").
    GBFS = "gbfs"
    # DATA-32: INKAR/BBSR sozialökonomische Indikatoren je Kreis (keylose Bulk-
    # Quelle, DL-DE/BY 2.0, Tier A). Read-only Store-Lesung im Request-Pfad (wie
    # KBA/UNFALLATLAS), kein resilient_client. Toggle-Name == SourceId-Wert ==
    # _KNOWN_SOURCES-Eintrag: getattr(settings, f"enable_{name}").
    INKAR = "inkar"
    # Wegweiser Kommune der Bertelsmann Stiftung (keylose Bulk-Quelle, CC0,
    # Tier A). Anders als INKAR gemeindescharf und mit ZEITREIHEN (2006-2040)
    # statt Einzelwerten. Read-only Store-Lesung im Request-Pfad (wie INKAR),
    # kein resilient_client. Toggle-Name == SourceId-Wert ==
    # _KNOWN_SOURCES-Eintrag: getattr(settings, f"enable_{name}").
    WEGWEISER = "wegweiser"
    # PKS-01: BKA Polizeiliche Kriminalstatistik je Kreis (keylose Bulk-XLSX,
    # DL-DE/BY 2.0, Tier A). Read-only Store-Lesung im Request-Pfad (wie KBA/
    # UNFALLATLAS), kein resilient_client. Toggle-Name == SourceId-Wert ==
    # _KNOWN_SOURCES-Eintrag: getattr(settings, f"enable_{name}").
    BKA_PKS = "bka_pks"
    # DATA-34: DB Timetables (Live-Abfahrtstafel Metropolen-Hbf inkl. Fernverkehr +
    # Echtzeit-Verspätung). Keyed Live-Quelle (resilient_client, Header-Auth),
    # CC-BY 4.0 = Tier A. Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag;
    # die Keys sind eigene SecretStr-Felder (db_client_id/db_api_key).
    DB_TIMETABLES = "db_timetables"
    # DATA-35: BORIS amtliche Bodenrichtwerte je Stadt (Bulk, keylos). BORIS ist
    # pro Bundesland föderiert (je Land ein eigener WFS, kein bundesweiter
    # Single-Endpoint) -> die BORIS_WFS-Registry (api.v1.cities) mappt Bundesland
    # -> WFS-Config. Lizenz Berlin = DL-DE/Zero 2.0 (DL_DE_ZERO_2_0 existiert
    # bereits). Read-only Store-Lesung im Request-Pfad (wie INKAR/KBA), kein
    # resilient_client. Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag:
    # getattr(settings, f"enable_{name}").
    BORIS = "boris"
    # DATA-36: StaDa Station Data (Bahnhofs-Katalog je Stadt: alle Bahnhöfe einer
    # Stadt mit EVA, Geo, Kategorie). Keyed Live-Quelle über denselben DB-API-
    # Marketplace wie DB_TIMETABLES (gleiche db_client_id/db_api_key), CC BY 4.0 =
    # Tier A. Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag.
    STADA = "stada"
    # DATA-37: Regionalstatistik.de (GENESIS-Webservice der Statistischen Ämter):
    # Realsteuer-Hebesätze (71231, GEMEINDE-genau) + Gewerbean-/-abmeldungen
    # (52311, KREIS-genau). Bulk-Ingest -> SQLite (kein Live-Call im Request-Pfad,
    # wie INKAR/BORIS), aber die GENESIS-API verlangt seit 05/2025 eine
    # Registrierung (Header-Auth username/password, NUR im Ingest, regio_user/
    # regio_pass). Lizenz DL-DE/BY 2.0 = Tier A (DL_DE_BY_2_0 existiert bereits).
    # Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag.
    REGIONALSTATISTIK = "regionalstatistik"
    # DATA-38 (Stufe 1): PVGIS-Solar-Einstrahlung + normierter PV-Ertrag je Stadt
    # (EU JRC, keylose Live-Rechen-API re.jrc.ec.europa.eu PVcalc). PVGIS rechnet
    # jede EU-Koordinate -> alle Register-Städte ohne Stadt-Allowlist. EU-Reuse-
    # Policy (EC_REUSE) = Tier A. Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-
    # Eintrag: getattr(settings, f"enable_{name}").
    SOLAR = "solar"
    # DATA-39 (Stufe 2): Dach-Solarkataster je Stadt (installiertes + installierbares
    # PV-Potenzial je Gemeinde). Föderiert je Bundesland wie BORIS; NRW-Pilot aus dem
    # amtlichen Gemeinde-Aggregat (Solarkataster NRW, MaStR/LANUK/Geobasis NRW,
    # DL-DE/Zero 2.0 = Tier A). Seed-basiert (kein Live-Fremd-API). Toggle-Name ==
    # SourceId-Wert == _KNOWN_SOURCES-Eintrag: getattr(settings, f"enable_{name}").
    SOLAR_CADASTRE = "solar_cadastre"
    # DATA-40: München Open Data, statische/halbstatische Stadtquellen via CKAN
    # (opendata.muenchen.de, DL-DE/BY 2.0 = Tier A). PARKHÄUSER = Parkhaus-
    # Standortkatalog (KEINE Live-Belegung); RADZÄHL = Raddauerzählstellen
    # (Rad-Zählungen je Zählstelle, monatlich aktualisiert). Toggle-Name ==
    # SourceId-Wert == _KNOWN_SOURCES-Eintrag: getattr(settings, f"enable_{name}").
    MUENCHEN_PARKING = "muenchen_parking"
    MUENCHEN_BIKE_COUNTS = "muenchen_bike_counts"
    # Quick-260729-muc: drei neue Datenarten zum ruhenden Verkehr München, alle
    # keylos und DL-DE/BY 2.0 = Tier A. PARKRAUM = Straßenparkraum (Parkseiten,
    # PRM-Gebiete, Behindertenparkplätze, Laden/Liefern; WFS Mobilitätsreferat);
    # PARK_RIDE = P+R- und B+R-Anlagen samt Belegungsprognose (CKAN, P+R GmbH);
    # MOBILITAETSPUNKTE = Mobilitätspunkte + Carsharing-Parkflächen (WFS).
    # EIGENE SourceId je Datenart, weil der Cache-Key aus Quelle + Stadt gebaut
    # wird (gemeinsame Id -> Key-Kollision zwischen den Endpunkten). Toggle-Name
    # == SourceId-Wert == _KNOWN_SOURCES-Eintrag.
    MUENCHEN_PARKING_ONSTREET = "muenchen_parking_onstreet"
    MUENCHEN_PARK_AND_RIDE = "muenchen_park_and_ride"
    MUENCHEN_MOBILITY_POINTS = "muenchen_mobility_points"
    # Quick-260729-mrp: RADPARKEN = Fahrrad- und Lastenradabstellanlagen aus zwei
    # weiteren WFS-Layern desselben Referats (Hinweis aus dem Austausch mit dem
    # IT-Referat der Stadt). Eigene SourceId aus demselben Grund wie oben.
    MUENCHEN_BIKE_PARKING = "muenchen_bike_parking"
    # DATA-40: bike-counts je Stadt (kommunale Radzählstellen-Open-Data, Tier A,
    # je Ursprung lizenzverifiziert). Toggle-Name == SourceId-Wert == _KNOWN_SOURCES.
    LEIPZIG_BIKE_COUNTS = "leipzig_bike_counts"
    HAMBURG_BIKE_COUNTS = "hamburg_bike_counts"
    BERLIN_BIKE_COUNTS = "berlin_bike_counts"
    STUTTGART_BIKE_COUNTS = "stuttgart_bike_counts"
    KOELN_BIKE_COUNTS = "koeln_bike_counts"
    ESSEN_BIKE_COUNTS = "essen_bike_counts"
    DUESSELDORF_BIKE_COUNTS = "duesseldorf_bike_counts"
    # DATA-40: ParkenDD-Aggregator (api.parkendd.de, keylos) = bevorzugte Live-
    # Parkhaus-Belegung für viele Städte (EIN Adapter, Dedup-Prinzip). Lizenz
    # heterogen je Stadt -> UNKNOWN/Tier C (Tier-C-Muster), Attribution "ParkenDD".
    # Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag.
    PARKENDD = "parkendd"
    # DATA-OSM-Tier-2: Denkmallisten je Bundesland (Landessache, föderiert wie
    # BORIS). On-demand-WFS (GeoJSON), Repräsentativpunkt je Objekt. Berlin
    # verifiziert (DL-DE/Zero 2.0 = Tier A); Bayern CC-BY-ND = NICHT nutzbar
    # (fail-closed). Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag.
    HERITAGE = "heritage"
    # DATA-OSM-Tier-2: Baumkataster je Stadt (kommunales Open Data, On-demand-WFS,
    # Punkte). Berlin verifiziert (DL-DE/Zero 2.0 = Tier A, ~900k Straßenbäume,
    # gedeckelte Stichprobe). Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag.
    TREE_CADASTRE = "tree_cadastre"
    # DATA-OSM-Tier-2: Zensus-2022-100m-Gitter (keyloser ArcGIS-FeatureServer, NICHT
    # die account-gated GENESIS-ZENSUS-POST-API). Einwohnerdichte je Stadt exakt per
    # AGS-Aggregation. DL-DE/BY 2.0 = Tier A. Toggle == SourceId == _KNOWN_SOURCES.
    ZENSUS_GRID = "zensus_grid"
    # Phase 21: Öffentliche Auftragsvergabe je Stadt (Datenservice Öffentlicher
    # Einkauf, oeffentlichevergabe.de, OCDS-1.1-Bekanntmachungen, CC0 = Tier A).
    # Bulk-Download (OCDS-ZIP), Stadt-Zuordnung über den Geo-Crosswalk-Seed
    # (NUTS-3/PLZ). Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag:
    # getattr(settings, f"enable_{name}"). Wert ASCII (StrEnum), kein Umlaut.
    OEFFENTLICHEVERGABE = "oeffentlichevergabe"
    # DATA-41: Fernwärme-/Wärmenetz-Versorgung je Stadt aus der kommunalen
    # Wärmeplanung. Föderiert je Stadt-WFS (wie BORIS/solar-roofs, je Ursprung
    # lizenzverifiziert): Berlin = Energienetze-WFS (Fernwärme-Netzgebiet inkl.
    # 250 m Puffer, DL-DE/Zero 2.0); Hamburg = WFS "Gebiete mit Wärmenetz" der
    # kommunalen Wärmeplanung (DL-DE/BY 2.0). Beide Tier A. Batch-Ingest -> Archiv
    # (kein WFS-Call im Request-Pfad, wie bnetza), Route liest read-only. Lizenz/
    # Attribution stehen je Stadt im Record (Mapper liest sie aus der WFS-Registry).
    # Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag.
    DISTRICT_HEATING = "district_heating"
    # Quick-260705-jgt: Koeln Behoerden-Wartezeiten (office-wait-times). Keyloser
    # Direkt-HTTP gegen waiting-od.php (wie KOELN_EVENTS), DL-DE/Zero 2.0 = Tier A.
    # Reine Live-Daten (kein Archiv). Wert ASCII-lowercase (StrEnum), kein Umlaut.
    # Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag: getattr(settings,
    # f"enable_{name}").
    KOELN_WAIT_TIMES = "koeln_wait_times"
    # Quick-260705-ufv: BBK NINA Bevoelkerungsschutz-Warnungen (civil-protection-
    # warnings). Keyloser GET gegen warnung.bund.de/api31/dashboard/{ARS}.json,
    # ARS aus dem Register-AGS abgeleitet. Reine Live-Warnungen (kein Archiv),
    # amtlicher Warntext verbatim (LicenseId.AMTLICHES_WERK, Tier A). Wert ASCII-
    # lowercase (StrEnum), kein Umlaut. Toggle-Name == SourceId-Wert ==
    # _KNOWN_SOURCES-Eintrag: getattr(settings, f"enable_{name}").
    BBK_NINA = "bbk_nina"
    # Quick-260708-tsv: kommunale Ratsinformationen (OParl-1.x "Paper" = Vorlagen,
    # Anträge, Beschlüsse) der acht lizenzgeklärten Städte (Dresden, Köln,
    # Düsseldorf, Münster, Leipzig, Magdeburg, Osnabrück, Freiburg im Breisgau).
    # Schwester-Datenart zu public-tenders: keyloser
    # OParl-Adapter -> Batch-Ingest -> SQLite-Store -> read-only Route. Namespace:
    # SourceId/Toggle/SOURCE_SPECS = "council", Endpoint/Resource = "council-papers".
    # Wert ASCII (StrEnum), kein Umlaut. Per-Stadt-Lizenz in mappers/oparl.py.
    COUNCIL = "council"
    # Phase 25: Parken-Direktbezug (ParkenDD-Abloesung). Geschichtete Direktquellen
    # statt Aggregator. Alle Werte ASCII-lowercase (StrEnum), kein Umlaut (Slugs
    # muenster/koeln). Invariante Toggle==SourceId==source_spec==_KNOWN_SOURCES-
    # Eintrag: getattr(settings, f"enable_{name}"). SourceId.PARKENDD bleibt in
    # Welle 0 unangetastet (Abbau erst 25-08). Kein neuer LicenseId-Wert noetig
    # (DL_DE_BY_2_0/DL_DE_ZERO_2_0/CC0/CC_BY_4_0 existieren; per-Stadt-Lizenzen
    # der MobiData-Staedte liegen im Mapper mappers/mobidata_parkapi).
    # MobiData BW ParkAPI v3 (keylos, EIN GET je source_uid, statisch+realtime
    # inline; per-Stadt-Lizenz im Mapper, generische Quellen-Attribution im spec).
    MOBIDATA_PARKAPI = "mobidata_parkapi"
    # P+R Hessen (ivm GmbH, Mobilithek DATEX II, LICENSE_FREE_USE_OPEN_DATA ->
    # DL-DE/BY 2.0 = Tier A). Gated (Cert + Abo), Default False.
    PR_HESSEN_PARKING = "pr_hessen_parking"
    # DB BahnPark (~315 Bahnhof-Parkhaeuser bundesweit, DB API Marketplace,
    # Header-Auth db_client_id/db_api_key, DL-DE/BY 2.0 = Tier A). Gated, Default
    # False (Owner-Subscription noetig).
    DB_BAHNPARK = "db_bahnpark"
    # Stadt-OpenData-Direktquellen (keylos, je Ursprung lizenzverifiziert): loesen
    # die bei ParkenDD eingefrorenen Staedte durch Direktbezug wieder live.
    MUENSTER_PARKING = "muenster_parking"
    AACHEN_PARKING = "aachen_parking"
    OLDENBURG_PARKING = "oldenburg_parking"
    KAISERSLAUTERN_PARKING = "kaiserslautern_parking"
    DRESDEN_PARKING = "dresden_parking"
    # Karlsruhe Parkleitsystem (web1.karlsruhe.de, HTML-Scraper, keylos). Direkter
    # Ersatz fuer den ParkenDD-Karlsruhe-Bezug (gleiche Ursprungsseite). Lizenz am
    # Direktendpunkt NICHT offen deklariert (Owner-Entscheid 2026-07-19) ->
    # UNKNOWN/Tier C (live-only, NICHT public bis Lizenzklaerung).
    KARLSRUHE_PARKING = "karlsruhe_parking"
    # Hamburg-Parken via Mobilithek (NICHT api.hamburg.de: Box-IP-Block), gated
    # (Cert + Abo), Default False. DL-DE/BY 2.0 = Tier A.
    HAMBURG_PARKING = "hamburg_parking"
