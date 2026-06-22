"""Kanonische Enums der Normalisierungs-Library (CORE-01).

Definiert die festen Wertebereiche fuer Lizenz-Tier, Lizenz-ID und Quelle als
``StrEnum``. ``StrEnum`` serialisiert verlustfrei zu JSON-Strings und dient als
Pflicht-Anker fuer die tier-getrennte Datenhaltung (GOV-Fundament): kein
Datensatz darf ohne korrektes Tier-Tag ins System gelangen.
"""

from __future__ import annotations

from enum import StrEnum


class LicenseTier(StrEnum):
    """Lizenz-Tier zur tier-getrennten Datenhaltung (GOV-Fundament).

    Kennzeichnet (GOV-02/04) die Lizenz je Datensatz fuer korrekte Attribution
    und Weiternutzung, ohne das Schema zu aendern. Pflichtfeld am Envelope, damit
    kein Datensatz ohne Tier durchrutscht.
    """

    A = "A"  # permissiv (CC0, CC-BY, DL-DE/BY, DL-DE/Zero, GeoNutzV)
    B = "B"  # copyleft (ODbL, CC-BY-SA): getrennt kennzeichnen
    C = "C"  # live-only (OpenAQ): nur Live-Anzeige


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
    # Ehrlicher Tag fuer Quellen mit heterogener/unbekannter Lizenz je Datensatz
    # (konkret OpenAQ, dessen Lizenz pro Provider variiert): verhindert ein
    # falsches pauschales CC-BY-Tag im Envelope (GOV-01/03-Compliance).
    UNKNOWN = "unknown"


class SourceId(StrEnum):
    """Bekannte Upstream-Quellen, die in das kanonische Schema abgebildet werden."""

    WIKIDATA = "wikidata"
    OPENAQ = "openaq"
    DWD = "dwd"
    OSM = "osm"
    AUTOBAHN = "autobahn"
    BNETZA = "bnetza"
    UBA = "uba"
    DELFI = "delfi"
    HVV = "hvv"
    # Phase 7: Tier-A-Quellen (E-Mobilitaet und erweiterte Umweltdaten).
    # Hinweis: Quellen-/Toggle-Name ist "lhp", der License-/Record-Tag aber
    # HOCHWASSER (Landeshochwasserportale, www.hochwasserzentralen.de).
    PEGELONLINE = "pegelonline"
    HOCHWASSER = "hochwasser"
    DWD_POLLEN = "dwd_pollen"
    # Phase 8: Statistik-, Energie- und Geo-Quellen. GENESIS und
    # ZENSUS sind account-gated (POST-API), MASTR/BKG/BUNDESWAHL/FEIERTAGE sind
    # keylose Bulk-/Seed-Quellen, DIVI ist die klinikscharfe Live-only-Quelle
    # (Tier C, DB-Schutzrecht). Alle Werte ASCII (StrEnum).
    GENESIS = "genesis"
    ZENSUS = "zensus"
    MASTR = "mastr"
    SMARD = "smard"
    DWD_WARNINGS = "dwd_warnings"
    BKG = "bkg"
    BUNDESWAHL = "bundeswahl"
    DIVI = "divi"
    FEIERTAGE = "feiertage"
    # Phase 9: keylose Stadt-Verkehrs-Quellen (Baustellen/Sperrungen) je Stadt.
    # Alle Werte ASCII (StrEnum), kein Umlaut (Slugs muenchen/koeln). Toggle-Name
    # == SourceId-Wert == _KNOWN_SOURCES-Eintrag. Webcams nutzen weiterhin
    # SourceId.AUTOBAHN als Live-Bild-Feature; daher gibt es hier KEINE eigene
    # Webcam-SourceId. Kein neuer LicenseId-Wert
    # (alle Phase-9-Quellen sind DL-DE/BY 2.0 = DL_DE_BY_2_0, bereits vorhanden).
    BERLIN_VIZ = "berlin_viz"
    HAMBURG_BAUSTELLEN = "hamburg_baustellen"
    KOELN_VERKEHR = "koeln_verkehr"
    MUENCHEN_BAUSTELLEN = "muenchen_baustellen"
    MOBIDATA_BW = "mobidata_bw"
    # Phase 10: Stadt-Events/Veranstaltungen. DESTINATION_ONE ist die account-
    # gated eT4.META-Quelle (licensekey, gemischte Lizenzen pro Record, GOV-04),
    # KOELN_EVENTS der keylose Koeln-Direkt-Feed (fix DL-DE/BY, D-06). Alle Werte
    # ASCII (StrEnum), kein Umlaut (Slug koeln). Toggle-Name == SourceId-Wert ==
    # _KNOWN_SOURCES-Eintrag. Kein neuer LicenseId-Wert noetig (CC0/CC_BY_4_0/
    # CC_BY_SA_4_0/DL_DE_BY_2_0/UNKNOWN existieren bereits).
    DESTINATION_ONE = "destination_one"
    KOELN_EVENTS = "koeln_events"
    # Phase 20: Live-Quellen ueber den Mobilithek-mTLS-Pull (getrennte /live-
    # Kategorie). Alle Werte ASCII-lowercase, kein Umlaut (Slugs koeln/berlin/
    # dortmund/kiel/eround). Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-
    # Eintrag: getattr(settings, f"enable_{name}"). Kein neuer LicenseId-Wert
    # (DL_DE_BY_2_0/CC0/UNKNOWN existieren; eRound erst nach Lizenz-Verifikation).
    KOELN_TRAFFIC_FLOW = "koeln_traffic_flow"
    KOELN_BAUSTELLEN_LIVE = "koeln_baustellen_live"
    KOELN_EREIGNISSE_LIVE = "koeln_ereignisse_live"
    KOELN_LEZ_LIVE = "koeln_lez_live"
    BERLIN_VERKEHRSMELDUNGEN = "berlin_verkehrsmeldungen"
    DORTMUND_PARKING = "dortmund_parking"
    KIEL_ZAEHLSTELLEN = "kiel_zaehlstellen"
    EROUND_CHARGING = "eround_charging"
    # Frankfurt am Main Parkdaten (Mobilithek DATEX II V3 Parking, statisch +
    # dynamisch gejoint, DL-DE/BY 2.0 = Tier A). EINZIGE DATEX-II-V3-XML-Quelle
    # (eRound ist V3-JSON, Koeln ist V2-XML): eigener V3-XML-Parser
    # (adapters/mobilithek_datex3). Toggle-Name == SourceId-Wert ==
    # _KNOWN_SOURCES-Eintrag: getattr(settings, f"enable_{name}").
    FRANKFURT_PARKING = "frankfurt_parking"
    # Wuppertal Parkdaten (Mobilithek DATEX II V2 ParkingFacility-Profil, statisch
    # + dynamisch gejoint, DL-DE/Zero 2.0 = Tier A). Eigenes V2-Profil
    # (parkingFacilityStatus/-Reference), getrennt vom Koeln-parkingStatus-Pfad.
    # Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag.
    WUPPERTAL_PARKING = "wuppertal_parking"
    # Phase 19: GTFS-Realtime Trip Updates, Tier B CC-BY-SA, gtfs.de/Mobilithek-
    # DELFI; kein neuer LicenseId-Wert (CC_BY_SA_4_0 existiert bereits), kein
    # Umlaut (StrEnum, ASCII-lowercase). Toggle-Name == SourceId-Wert ==
    # _KNOWN_SOURCES-Eintrag: getattr(settings, f"enable_{name}").
    GTFS_RT = "gtfs_rt"
    # DATA-24: HVV-Geofox-GTI Live-Abfahrten (Hamburg), Tier C live-only
    # (Geofox-Lizenz nicht offen). Eigene SourceId getrennt von HVV (= statische
    # GTFS-Stops). Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag.
    HVV_GEOFOX = "hvv_geofox"
    # DATA-25: VGN/VAG-Nuernberg Live-Abfahrten (Puls-API start.vag.de), Tier A
    # (CC-BY 4.0, offen, opendata.vag.de) -> sauber verwertbar, anders als HVV.
    # Keylos, KEINE Mobilithek. Toggle-Name == SourceId-Wert == _KNOWN_SOURCES.
    VGN = "vgn"
    # DATA-26: Hamburg-Verkehrslage (Echtzeit-Verkehrsfluss je Strassenabschnitt,
    # OAF/GeoJSON api.hamburg.de), Tier A (DL-DE/BY 2.0, offen, keylos). Anders als
    # HVV_GEOFOX (Tier C, nicht offen) sauber verwertbar. KEINE Mobilithek.
    # Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag.
    HAMBURG_VERKEHRSLAGE = "hamburg_verkehrslage"
    # DATA-27: KBA Pkw-Bestand + Elektro-Anteil je Zulassungsbezirk (keylose
    # Bulk-Quelle, DL-DE/BY 2.0, Tier A). Read-only Store-Lesung im Request-Pfad
    # (wie MASTR), kein resilient_client. Toggle-Name == SourceId-Wert ==
    # _KNOWN_SOURCES-Eintrag: getattr(settings, f"enable_{name}").
    KBA = "kba"
    # DATA-29: Unfallatlas (Strassenverkehrsunfaelle je Kreis, keylose Bulk-CSV,
    # DL-DE/BY 2.0, Tier A). Read-only Store-Lesung (wie KBA/MASTR), kein
    # resilient_client. Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag.
    UNFALLATLAS = "unfallatlas"
    # DATA-30: Tankerkoenig Spritpreise (MTS-K), aggregiert je Stadt. Keyed Live-
    # Quelle (resilient_client), CC-BY 4.0 = Tier A (offen, verwertbar). Toggle-
    # Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag: getattr(settings,
    # f"enable_{name}"); der Key ist ein eigenes SecretStr-Feld.
    TANKERKOENIG = "tankerkoenig"
    # DATA-31: Bremen Baustellen/Arbeitsstellen (Verkehrsmanagementzentrale Bremen,
    # Mobilithek DATEX II V2 SituationPublication, DL-DE/BY 2.0, Tier A). Live-
    # Quelle wie koeln_baustellen_live. Toggle-Name == SourceId-Wert ==
    # _KNOWN_SOURCES-Eintrag.
    BREMEN_BAUSTELLEN = "bremen_baustellen"
    # Hannover Verkehrsmeldungen (Landeshauptstadt Hannover, Fachbereich Tiefbau,
    # Mobilithek DATEX II V2 SituationPublication: Baustellen/Veranstaltungen/
    # Verkehrsstoerungen, Mobilithek-Angebot "freie Nutzung/Open Data" = DL-DE/BY
    # 2.0 = Tier A, analog Bremen/Berlin). Live-Quelle wie bremen_baustellen.
    # Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag.
    HANNOVER_VERKEHRSMELDUNGEN = "hannover_verkehrsmeldungen"
    # DATA-33: GBFS-Bike-/Scooter-Sharing je Stadt (Live, aggregiert). Primaer
    # Nextbike (CC0 = Tier A); je System wird die Lizenz aus GBFS
    # ``system_information.license_id`` fail-closed gegen eine Tier-A-Allowlist
    # geprueft (GOV-02/04). Keyed-los, resilient_client. Toggle-Name == SourceId-
    # Wert == _KNOWN_SOURCES-Eintrag: getattr(settings, f"enable_{name}").
    GBFS = "gbfs"
    # DATA-32: INKAR/BBSR sozialoekonomische Indikatoren je Kreis (keylose Bulk-
    # Quelle, DL-DE/BY 2.0, Tier A). Read-only Store-Lesung im Request-Pfad (wie
    # KBA/UNFALLATLAS), kein resilient_client. Toggle-Name == SourceId-Wert ==
    # _KNOWN_SOURCES-Eintrag: getattr(settings, f"enable_{name}").
    INKAR = "inkar"
    # DATA-34: DB Timetables (Live-Abfahrtstafel Metropolen-Hbf inkl. Fernverkehr +
    # Echtzeit-Verspaetung). Keyed Live-Quelle (resilient_client, Header-Auth),
    # CC-BY 4.0 = Tier A. Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag;
    # die Keys sind eigene SecretStr-Felder (db_client_id/db_api_key).
    DB_TIMETABLES = "db_timetables"
    # DATA-35: BORIS amtliche Bodenrichtwerte je Stadt (Bulk, keylos). BORIS ist
    # pro Bundesland foederiert (je Land ein eigener WFS, kein bundesweiter
    # Single-Endpoint) -> die BORIS_WFS-Registry (api.v1.cities) mappt Bundesland
    # -> WFS-Config. Lizenz Berlin = DL-DE/Zero 2.0 (DL_DE_ZERO_2_0 existiert
    # bereits). Read-only Store-Lesung im Request-Pfad (wie INKAR/KBA), kein
    # resilient_client. Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag:
    # getattr(settings, f"enable_{name}").
    BORIS = "boris"
    # DATA-36: StaDa Station Data (Bahnhofs-Katalog je Stadt: alle Bahnhoefe einer
    # Stadt mit EVA, Geo, Kategorie). Keyed Live-Quelle ueber denselben DB-API-
    # Marketplace wie DB_TIMETABLES (gleiche db_client_id/db_api_key), CC BY 4.0 =
    # Tier A. Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag.
    STADA = "stada"
    # DATA-37: Regionalstatistik.de (GENESIS-Webservice der Statistischen Aemter):
    # Realsteuer-Hebesaetze (71231, GEMEINDE-genau) + Gewerbean-/-abmeldungen
    # (52311, KREIS-genau). Bulk-Ingest -> SQLite (kein Live-Call im Request-Pfad,
    # wie INKAR/BORIS), aber die GENESIS-API verlangt seit 05/2025 eine
    # Registrierung (Header-Auth username/password, NUR im Ingest, regio_user/
    # regio_pass). Lizenz DL-DE/BY 2.0 = Tier A (DL_DE_BY_2_0 existiert bereits).
    # Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag.
    REGIONALSTATISTIK = "regionalstatistik"
    # DATA-38 (Stufe 1): PVGIS-Solar-Einstrahlung + normierter PV-Ertrag je Stadt
    # (EU JRC, keylose Live-Rechen-API re.jrc.ec.europa.eu PVcalc). PVGIS rechnet
    # jede EU-Koordinate -> alle Register-Staedte ohne Stadt-Allowlist. EU-Reuse-
    # Policy (EC_REUSE) = Tier A. Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-
    # Eintrag: getattr(settings, f"enable_{name}").
    SOLAR = "solar"
    # DATA-39 (Stufe 2): Dach-Solarkataster je Stadt (installiertes + installierbares
    # PV-Potenzial je Gemeinde). Foederiert je Bundesland wie BORIS; NRW-Pilot aus dem
    # amtlichen Gemeinde-Aggregat (Solarkataster NRW, MaStR/LANUK/Geobasis NRW,
    # DL-DE/Zero 2.0 = Tier A). Seed-basiert (kein Live-Fremd-API). Toggle-Name ==
    # SourceId-Wert == _KNOWN_SOURCES-Eintrag: getattr(settings, f"enable_{name}").
    SOLAR_CADASTRE = "solar_cadastre"
