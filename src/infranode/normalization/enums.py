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
    # Phase 19: GTFS-Realtime Trip Updates, Tier B CC-BY-SA, gtfs.de/Mobilithek-
    # DELFI; kein neuer LicenseId-Wert (CC_BY_SA_4_0 existiert bereits), kein
    # Umlaut (StrEnum, ASCII-lowercase). Toggle-Name == SourceId-Wert ==
    # _KNOWN_SOURCES-Eintrag: getattr(settings, f"enable_{name}").
    GTFS_RT = "gtfs_rt"
    # DATA-24: HVV-Geofox-GTI Live-Abfahrten (Hamburg), Tier C live-only
    # (Geofox-Lizenz nicht offen). Eigene SourceId getrennt von HVV (= statische
    # GTFS-Stops). Toggle-Name == SourceId-Wert == _KNOWN_SOURCES-Eintrag.
    HVV_GEOFOX = "hvv_geofox"
