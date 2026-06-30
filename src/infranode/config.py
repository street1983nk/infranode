"""Zentrale Konfiguration (FND-02).

Eine einzige ``Settings``-Quelle liest ``.env`` + Umgebungsvariablen mit dem
Prefix ``INFRANODE_``. Per-Source ``enable_*``-Flags ermöglichen Graceful
Degradation; Schlüssel-Felder sind ``SecretStr | None`` (Default None =
Quelle nicht nutzbar, kein Secret im Code).

WARTBARKEIT (2026-06-21): Die Felder sind in thematische Mixin-Klassen
gruppiert (CoreSettings, RateLimitSettings, AdminSettings, SourceToggleSettings,
CredentialSettings, MobilithekSettings, TransitSettings, BulkPathSettings,
MonitoringSettings). ``Settings`` erbt von allen; pydantic merged die Felder zu
EINER flachen Klasse. Das ist bewusst KEINE verschachtelte Struktur
(``settings.admin.password``): die Felder bleiben flach (``settings.enable_vgn``),
weil (a) die Quellen-Toggles an mehreren Stellen dynamisch über
``getattr(settings, f"enable_{name}")`` aufgelöst werden (sources/live/cities/
watchdog/admin) und (b) verschachtelte Modelle die Env-Variablennamen ändern
würden (``INFRANODE_ADMIN__PASSWORD`` statt ``INFRANODE_ADMIN_PASSWORD``), was
die produktive .env bräche. Neue Felder in die thematisch passende Mixin-Klasse.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class CoreSettings(BaseSettings):
    """Infrastruktur und Laufzeit: Logging, Redis, CORS, HTTP, Datenpfad."""

    log_level: str = "INFO"
    redis_url: str = "redis://redis:6379/0"
    # CORS: die öffentliche API ist KEYLOS, READ-ONLY und liefert offene Daten,
    # die explizit für beliebige Browser-/Client-Apps gedacht sind (Vibecoder,
    # Dashboards, Starter-Templates auf Vercel/Netlify/localhost). Für so eine
    # öffentliche Datendienst-API ist "*" der Standard (vgl. Open-Meteo,
    # Nominatim): die alte Whitelist hat jeden Cross-Origin-Browser-Client still
    # blockiert. Bewusste Abkehr von der früheren "nie *"-Regel; sie galt für
    # credentialed APIs. Hier wird allow_credentials in main.py auf False
    # gesetzt, sobald "*" aktiv ist (CORS-Spec: "*" + credentials schließen sich
    # aus). Das Admin-Dashboard ist same-origin (Cookie cs_admin SameSite=strict)
    # und von CORS unberührt. Per INFRANODE_CORS_ORIGINS auf eine Whitelist
    # einschränkbar (dann wird wieder credentialed CORS verwendet).
    cors_origins: list[str] = ["*"]

    # Optionaler Override des Upstream-User-Agents (RES-05). None = die
    # USER_AGENT-Konstante aus infra/http.py greift; per INFRANODE_HTTP_USER_AGENT
    # überschreibbar (z.B. für Staging-Kennzeichnung).
    http_user_agent: str | None = None

    # Wurzelpfad des lokalen Datenverzeichnisses. Per INFRANODE_ARCHIVE_DIR
    # überschreibbar, damit Tests nach tmp_path schreiben statt ins echte data/.
    # (Feld-/Env-Name aus Kompatibilitätsgründen unverändert.)
    archive_dir: str = "data/archive"


class RateLimitSettings(BaseSettings):
    """IP-Rate-Limiting (API-06). Echter DoS-Schutz liegt bei Cloudflare."""

    # limits/slowapi-Format ("<zahl>/<einheit>"). Die API ist keylos/offen; das
    # IP-Budget gilt für ALLE Clients (DoS-/Scraping-Schutz). Gestaffelt
    # (Security-Härtung 2026-06-21): ein BURST-Budget pro Minute für kurze
    # Data-Science-/Dashboard-Spitzen UND ein nachhaltiges STUNDEN-Budget gegen
    # Dauer-Scraping. Beide gelten gleichzeitig: ANON_LIMIT kombiniert sie
    # semikolon-getrennt, slowapi/limits ``parse_many`` liest das als MEHRERE
    # Limits. Per INFRANODE_LIMIT_ANON überschreibbar (z.B. Tests).
    # Historie: früher pauschal 300/min (=18.000/h), dann 120/min + 3000/h
    # (Härtung 2026-06-21). Owner 2026-06-24 auf 300/min Burst + 6000/h nachhaltig
    # angehoben (Schnitt 100/min), damit KI-Agenten/Power-User-Flows nicht in 429
    # laufen. Unkritisch: Box mit großer Reserve (~30% Load, 6 freie Kerne) +
    # CF-Edge-Cache/SWR + Breaker; das Limit ist Missbrauchs-Schutz, kein
    # Kapazitätsregler (Zielgröße bis Jahresende klar < 1000 Nutzer/Tag).
    limit_anon: str = "300/minute"
    # Nachhaltiges Zweit-Limit über ein längeres Fenster (leer = nur limit_anon).
    limit_anon_sustained: str = "6000/hour"
    # Striktes Budget am Admin-Login gegen Passwort-Brute-Force (Security-Audit
    # 2026-06-10, HIGH-1). Eigener strenger @limiter.limit-Decorator auf der Route.
    limit_admin_login: str = "5/minute"
    # Sync-Redis-URI für slowapis eigene limits-Storage (Pitfall 1: slowapi teilt
    # NICHT den async-Pool app.state.redis, sondern öffnet eine eigene sync-
    # Verbindung zum SELBEN Redis-Server). None = in der Anwendung auf redis_url
    # zurückfallen (gleicher Server, getrennte Verbindung).
    limit_storage_uri: str | None = None
    # Aggregiertes Subnetz-Limit gegen VERTEILTE Bots (Scraping-Härtung): das
    # IP-Limit oben fasst nur eine einzelne IP; ein Botnet/Cloud-Range mit vielen
    # IPs umgeht es. Dieses Zweit-Limit bremst pro /24 (IPv4) bzw. /64 (IPv6).
    # BEWUSST hoch (Default 3000/min = ~10x das IP-Burst-Budget), damit legitime
    # NAT-/Campus-Nutzer hinter einer gemeinsamen IP NICHT getroffen werden; es
    # greift erst, wenn aus EINEM Subnetz untypisch viele Anfragen kommen. Leer
    # ("") = deaktiviert. Per INFRANODE_LIMIT_SUBNET überschreibbar.
    # Owner 2026-06-24 von 1200 auf 3000/min mitgezogen (proportional zum auf
    # 300/min angehobenen IP-Burst, Verhältnis ~10x bleibt -> keine Lücke für
    # Bot-Schwärme, NAT-Schutz erhalten).
    limit_subnet: str = "3000/minute"
    subnet_ipv4_prefix: int = 24
    subnet_ipv6_prefix: int = 64
    # Optionaler Cloudflare-Bot-Score-Schwellwert (1-99; 0 = deaktiviert). Greift
    # NUR, wenn Cloudflare den Header ``cf-bot-score`` setzt (Bot Management /
    # Enterprise). Bei Free/Pro fehlt der Header -> der Check ist ein No-op-Hook,
    # der automatisch wirksam wird, sobald Scores verfügbar sind. Anfragen mit
    # Score < Schwellwert werden mit 403 abgelehnt (sehr wahrscheinlich Bots).
    bot_score_min: int = 0


class AdminSettings(BaseSettings):
    """Admin-Dashboard (OPS-01/02): Cookie-Session, Netzwerk-Guard."""

    # admin_password schützt /admin per Cookie-Session (fail-closed: None = Login
    # unmöglich, Best-Practice 2). Beide Secret-Felder sind SecretStr, damit der
    # Wert nie im Klartext geloggt/serialisiert wird. admin_session_secret signiert
    # das Session-Cookie (itsdangerous, >=32 Byte empfohlen). admin_log_max
    # begrenzt den Redis-Ringpuffer der Request-Logs. admin_cookie_https_only setzt
    # das Secure-Flag des Cookies (Default True; nur in Tests/lokal ohne TLS auf
    # False stellbar).
    admin_password: SecretStr | None = None
    admin_session_secret: SecretStr | None = None
    admin_log_max: int = 200
    admin_cookie_https_only: bool = True
    # Defense-in-Depth für /admin (T-18-15): Code-seitiger Netzwerk-Guard.
    # Betrieblich ist /admin bereits Tailnet-only (Caddy gibt öffentlich 404,
    # ``tailscale serve`` läuft ohne Funnel, ufw öffnet 80/443 nur für
    # Cloudflare). Dieser Guard blockt zusätzlich JEDE Anfrage mit öffentlich-
    # routbarer Client-IP (real_client_ip) mit 404, falls die Caddy-404-Regel je
    # entfällt. Loopback/private/Tailnet-CGNAT (100.64.0.0/10) sind als nicht-
    # global routbar immer erlaubt; admin_trusted_networks erlaubt optional
    # zusätzliche (auch global routbare) CIDR (leer = nur die nicht-globale Regel).
    admin_trusted_networks: list[str] = []


class SourceToggleSettings(BaseSettings):
    """Per-Quelle ``enable_*``-Toggles (Graceful Degradation).

    WICHTIG: Jeder Toggle-Name MUSS exakt zum SourceSpec-Namen in der Quellen-
    Registry (registry/source_specs.py, daraus wird _KNOWN_SOURCES abgeleitet) und
    zum SourceId-Wert passen, da er dynamisch über
    ``getattr(settings, f"enable_{name}")`` aufgelöst wird. Deshalb bleiben diese
    Felder flach auf der Settings-Klasse (keine Verschachtelung). Der Drift-Test
    tests/unit/test_source_specs_registry.py erzwingt, dass zu jeder Registry-Quelle
    ein enable_<name>-Toggle existiert. Keyed Live-Quellen stehen trotz Default True
    ohne Credentials auf "disabled".
    """

    # Phase 4/6: Basis-Quellen.
    enable_wikidata: bool = True
    enable_dwd: bool = True
    enable_overpass: bool = True
    # Overpass-Endpunkt operator-konfigurierbar (INFRANODE_OVERPASS_BASE_URL). Die
    # öffentliche Instanz untersagt Drittnutzer-Backends im Dauerbetrieb (Fair-Use);
    # für Produktion auf eine eigene Instanz (Planet-Dump) oder einen kommerziellen
    # Dienst (z.B. Geofabrik) umstellen. Env = Operator-Input (kein User-Input) ->
    # SSRF-Invariante bleibt gewahrt.
    overpass_base_url: str = "https://overpass-api.de/api/interpreter"
    # Audit K9: Element-Limit der OSM-/Overpass-Stichprobe (POIs + alle Feature-
    # Datenarten). Früher hart 200 -> kappte ~67-87% aller Objekte still (Köln
    # Spielplätze 200 statt 1540). Default jetzt 2000; der echte Gesamtbestand
    # kommt unabhängig über Overpass ``out count;`` als ``total_available`` +
    # ``truncated``-Flag. Per INFRANODE_OVERPASS_MAX_ELEMENTS anpassbar.
    overpass_max_elements: int = 2000
    enable_autobahn: bool = True
    enable_hvv: bool = False
    enable_delfi: bool = False
    # Phase 7: keylose, bundesweite Tier-A-Quellen (Default True analog enable_dwd).
    # enable_lhp = Hochwasser (Record-Tag hochwasser). enable_bnetza steuert NUR die
    # /charging-Route (Snapshot-Read aus offline CSV seit dem ArcGIS-Aus, nicht live).
    enable_bnetza: bool = True
    enable_uba: bool = True
    enable_pegelonline: bool = True
    enable_lhp: bool = True
    enable_dwd_pollen: bool = True
    # DWD Waldbrand-/Graslandfeuerindex (keylos, GeoNutzV, Tier A). Daten ueber
    # einen oeffentlichen ArcGIS-FeatureServer (DWD-Daten-Re-Host). Host operator-
    # konfigurierbar (INFRANODE_DWD_FIRE_BASE_URL); Env = Operator-Input (kein
    # User-Input) -> SSRF-Invariante bleibt gewahrt.
    enable_dwd_fire: bool = True
    dwd_fire_base_url: str = "https://services2.arcgis.com/7wuv6DH7DYhDuwvU/ArcGIS/rest/services/DWD/FeatureServer"
    # EEA Badegewaesserqualitaet (keylos, CC-BY 4.0, Tier A). Jahres-MapServer der
    # EEA DiscoMap; der Jahres-Teil der URL + eea_bathing_year werden nachgezogen,
    # sobald die EEA die neue Badesaison bewertet. Host operator-konfigurierbar
    # (INFRANODE_EEA_BATHING_BASE_URL) -> SSRF-Invariante bleibt gewahrt.
    enable_eea_bathing: bool = True
    eea_bathing_base_url: str = (
        "https://water.discomap.eea.europa.eu/arcgis/rest/services/BathingWater/"
        "BathingWater_Dyna_WM_2025/MapServer/3"
    )
    eea_bathing_year: int = 2025
    # Bundes-Klinik-Atlas (BMG/IQTIG): standortgenaue Krankenhausliste. FAIL-CLOSED:
    # KEINE explizite offene Lizenz ausgewiesen -> Default DEAKTIVIERT (Tier C/UNKNOWN),
    # bis BMG/IQTIG die Lizenz bestaetigt. Host operator-konfigurierbar.
    enable_klinik_atlas: bool = False
    klinik_atlas_base_url: str = (
        "https://bundes-klinik-atlas.de/fileadmin/json/locations.json"
    )
    # DB FaSta Aufzug-/Rolltreppen-Status (DB API Marketplace, CC-BY 4.0, Tier A).
    # KEY-GATED: braucht einen kostenlosen Marketplace-Schluessel (Plan Free4All).
    # Toggle Default True, aber ohne db_fasta_client_id/db_fasta_api_key liefert die
    # Route source_status=disabled (Konvention keyed Live-Quellen). Host operator-
    # konfigurierbar; Secrets in der Box-.env.
    enable_db_fasta: bool = True
    db_fasta_base_url: str = (
        "https://apis.deutschebahn.com/db-api-marketplace/apis/fasta/v2/facilities"
    )
    db_fasta_client_id: SecretStr | None = None
    db_fasta_api_key: SecretStr | None = None
    # Phase 8: account-gated Quellen Default False (bis Credentials gesetzt sind);
    # keylose Bulk-/Seed-Quellen Default True (Toggle steuert nur die Route, nicht
    # den Offline-Ingest). enable_genesis = Demografie + Krankenhaus, enable_zensus
    # = Zensus-Host, enable_divi = klinikscharfe DIVI-Live-Quelle (Tier C, optional).
    enable_genesis: bool = False
    # GENESIS-Regionalstatistik-Trio (Arbeitslosenquote/Tourismus/Bautaetigkeit je
    # Kreis, DATA-28). Eigener Toggle mit korrektem Header-Auth-Adapter, ohne den
    # Demografie-Pfad zu berühren. Braucht dieselben genesis_username/-password.
    enable_genesis_regio: bool = True
    enable_zensus: bool = False
    enable_divi: bool = False
    enable_mastr: bool = True
    # SMARD-Strommarktdaten (Verbrauch/Netzlast + Day-ahead-Preis), keylos CC BY 4.0.
    enable_smard: bool = True
    # DWD-Wetterwarnungen (amtliche Warnungen, WarnApp-JSON), keylos GeoNutzV.
    enable_dwd_warnings: bool = True
    # KBA Pkw-Bestand + Elektro-Anteil je Zulassungsbezirk (Bulk, keylos DL-DE/BY).
    enable_kba: bool = True
    # Unfallatlas (Straßenverkehrsunfälle je Kreis, Bulk-CSV, keylos DL-DE/BY).
    enable_unfallatlas: bool = True
    # INKAR/BBSR sozialökonomische Indikatoren je Kreis (Bulk, keylos DL-DE/BY).
    enable_inkar: bool = True
    # BKA-PKS Kriminalstatistik je Kreis (Bulk-XLSX, keylos DL-DE/BY, Tier A).
    enable_bka_pks: bool = True
    # Tankerkönig Spritpreise (MTS-K, CC BY 4.0). KEYED: Default True, aber ohne
    # tankerkoenig_key liefert die Route 200 disabled. Toggle-Name == SourceId.
    enable_tankerkoenig: bool = True
    # DATA-33: GBFS-Bike-/Scooter-Sharing (Live, aggregiert, Primär Nextbike CC0).
    # Keylos -> Default True; pro System Lizenz fail-closed gegen Tier-A-Allowlist.
    enable_gbfs: bool = True
    # DATA-34: DB Timetables (Bahnhof-Abfahrten Metropolen-Hbf inkl. Fernverkehr).
    # KEYED: ohne db_client_id/db_api_key liefert die Route 200 disabled.
    enable_db_timetables: bool = True
    # DATA-35: BORIS amtliche Bodenrichtwerte je Stadt (Bulk, keylos, föderierter
    # WFS pro Bundesland). Read-only Store-Lesung im Request-Pfad.
    enable_boris: bool = True
    # DATA-36: StaDa Station Data (Bahnhofs-Katalog je Stadt). Keyed über denselben
    # DB-API-Marketplace wie db_timetables (db_client_id/db_api_key, kein eigener Key).
    enable_stada: bool = True
    # DATA-37: Regionalstatistik.de (Realsteuer-Hebesätze 71231 + Gewerbean-/
    # -abmeldungen 52311). Bulk-Ingest -> SQLite (Read-only im Request-Pfad); ohne
    # regio_user/regio_pass 200 disabled (Daten könnten nie ingestet werden).
    enable_regionalstatistik: bool = True
    # DATA-38 (Stufe 1): PVGIS-Solar (EU JRC PVcalc, keylose Live-Rechen-API). PVGIS
    # rechnet jede EU-Koordinate -> alle Register-Städte abgedeckt. Keylos ->
    # Default True. Toggle-Name == SourceId.SOLAR == _KNOWN_SOURCES-Eintrag.
    enable_solar: bool = True
    # DATA-39 (Stufe 2): Dach-Solarkataster je Stadt (Seed-basiert, NRW-Pilot,
    # DL-DE/Zero 2.0). Teilabgedeckt (NRW), föderiert je Bundesland wie BORIS.
    enable_solar_cadastre: bool = True
    # DATA-40: München Open Data (CKAN, keylos, DL-DE/BY 2.0). parkhäuser =
    # statischer Parkhaus-Standortkatalog; radzähl = Raddauerzählstellen
    # (monatlich aktualisiert). Beide keylos -> Default True. Teilabgedeckt
    # (nur muenchen), bis weitere Städte erschlossen sind.
    enable_muenchen_parkhaeuser: bool = True
    enable_muenchen_radzaehl: bool = True
    # DATA-40 bike-counts: kommunale Radzählstellen je Stadt (keylos, Tier A).
    enable_leipzig_radzaehl: bool = True
    enable_hamburg_radzaehl: bool = True
    enable_berlin_radzaehl: bool = True
    enable_stuttgart_radzaehl: bool = True
    # DATA-40: ParkenDD-Aggregator (keylos) = bevorzugte Live-Parkbelegung für
    # viele Städte. Default True (keylos). Löst /live/dortmund/parking ab (Dedup).
    enable_parkendd: bool = True
    # DATA-OSM-Tier-2: Denkmallisten je Bundesland (On-demand-WFS, keylos). Default
    # True. Coverage-gated (registry.coverage), nur verifizierte offene Länder.
    enable_denkmal: bool = True
    # DATA-OSM-Tier-2: Baumkataster je Stadt (kommunaler On-demand-WFS, keylos).
    # Default True. Coverage-gated, nur verifizierte offen lizenzierte Städte.
    enable_baumkataster: bool = True
    # DATA-OSM-Tier-2: Zensus-2022-100m-Gitter (keyloser ArcGIS-FeatureServer) für
    # die Einwohnerdichte je Stadt. Default True (keylos, DL-DE/BY).
    enable_zensus_grid: bool = True
    # Phase 21: Öffentliche Auftragsvergabe je Stadt (oeffentlichevergabe.de OCDS,
    # CC0 = Tier A). Bulk-Download, keylos. Default True.
    enable_oeffentlichevergabe: bool = True
    enable_bkg: bool = True
    enable_bundeswahl: bool = True
    enable_feiertage: bool = True
    # Phase 9: keylose Stadt-Verkehrs-Quellen (Baustellen/Sperrungen) je Stadt +
    # Autobahn-Webcam-Sub-Service. Alle keylos, daher Default True.
    enable_berlin_viz: bool = True
    enable_hamburg_baustellen: bool = True
    enable_koeln_verkehr: bool = True
    enable_muenchen_baustellen: bool = True
    enable_mobidata_bw: bool = True
    enable_autobahn_webcam: bool = True
    # Phase 10: Stadt-Events/Veranstaltungen. destination.one ist KEYLOS (Experience
    # "open-data" frei zugänglich, Support-Bestätigung 2026-06-10) -> Default True.
    enable_destination_one: bool = True
    enable_koeln_events: bool = True
    # Phase 19: GTFS-Realtime Trip Updates (Live-OePNV-Verspätungen). Default False
    # bis aktiv geschaltet. Auflösung via getattr(settings, "enable_gtfs_rt").
    enable_gtfs_rt: bool = False
    # DATA-24/25/26: Live-Abfahrten/-Verkehrslage. enable_hvv_geofox KEYED (Default
    # False, braucht hvv_api_key + hvv_user). enable_vgn keylos (offene VAG-Puls-
    # API, CC-BY 4.0). enable_hamburg_verkehrslage keylos (OAF/GeoJSON, DL-DE/BY 2.0).
    enable_hvv_geofox: bool = False
    enable_vgn: bool = True
    enable_hamburg_verkehrslage: bool = True
    # Phase 20: Mobilithek-mTLS-Live-Quellen (Live = Cert + Abo nötig, daher alle
    # Default False bis Zertifikat und Abo-ID gesetzt sind). Ausnahme:
    # dortmund_parking ist seit 2026-06-13 KEYLOS (direkter Opendatasoft-Feed) ->
    # Default True; dortmund_parking_abo_id ungenutzt (bleibt für SSRF-Konsistenz).
    enable_koeln_traffic_flow: bool = False
    enable_koeln_baustellen_live: bool = False
    enable_koeln_ereignisse_live: bool = False
    enable_koeln_lez_live: bool = False
    enable_berlin_verkehrsmeldungen: bool = False
    enable_dortmund_parking: bool = True
    enable_kiel_zaehlstellen: bool = False
    enable_eround_charging: bool = False
    # DATA-31: Bremen Baustellen (Mobilithek DATEX II Situation, DL-DE/BY 2.0).
    enable_bremen_baustellen: bool = False
    # Hannover Verkehrsmeldungen (Mobilithek DATEX II V2 Situation, DL-DE/BY 2.0).
    # Live = Cert + Abo nötig -> Default False, bis Zertifikat + Abo-ID gesetzt.
    enable_hannover_verkehrsmeldungen: bool = False
    # Frankfurt am Main Parkdaten (Mobilithek DATEX II V3 Parking, statisch +
    # dynamisch gejoint, DL-DE/BY 2.0). Live = Cert + Abo nötig -> Default False,
    # bis Zertifikat und beide Abo-IDs gesetzt sind.
    enable_frankfurt_parking: bool = False
    # Wuppertal Parkdaten (Mobilithek DATEX II V2 ParkingFacility, statisch +
    # dynamisch gejoint, DL-DE/Zero 2.0). Live = Cert + Abo -> Default False.
    enable_wuppertal_parking: bool = False
    # Magdeburg Parkdaten (Mobilithek DATEX II V2 ParkingFacility, statisch +
    # dynamisch). Teilt den Wuppertal-V2-Parser; Occupancy ist bei Magdeburg
    # bereits Prozent (nicht Anteil 0..1). Default False, bis Abo-IDs + Live-Verify.
    enable_magdeburg_parking: bool = False


class CredentialSettings(BaseSettings):
    """API-Keys/Credentials externer Quellen. Alle Secrets als SecretStr | None.

    None = Quelle nicht nutzbar (Graceful Degradation). Secrets gehen NUR in
    Header/Body/Query des jeweiligen Upstream-Requests, NIE in Cache-Key/Response/
    Log. Werte stammen aus der gitignored .env (Env-Namen über den Prefix).
    """

    # Phase 8 GENESIS/Zensus (account-gated POST-API). Feldname genesis_username,
    # weil der Owner genau INFRANODE_GENESIS_USERNAME (+ _PASSWORD) in der .env
    # gesetzt hat. Zensus nutzt evtl. einen getrennten Account (eigene Felder).
    genesis_username: str | None = None
    genesis_password: SecretStr | None = None
    zensus_user: str | None = None
    zensus_password: SecretStr | None = None
    # HVV-Geofox-GTI Live-Abfahrten (DATA-24): hvv_api_key = HMAC-Secret, hvv_user =
    # geofox-auth-user. Beide nur in Header/Body des signierten Geofox-Requests.
    hvv_api_key: SecretStr | None = None
    hvv_user: str | None = None
    # DATA-30: Tankerkönig-API-Key. Nur in den Query-Parameter ``apikey``. None ->
    # Route liefert 200 source_status="disabled". Env INFRANODE_TANKERKOENIG_KEY.
    tankerkoenig_key: SecretStr | None = None
    # DATA-34: DB-Timetables-Credentials (DB API Marketplace). Nur in die Header
    # DB-Client-Id/DB-Api-Key. None -> Route 200 disabled.
    db_client_id: SecretStr | None = None
    db_api_key: SecretStr | None = None
    # DATA-37: Regionalstatistik.de GENESIS-Webservice (Header-Auth username/
    # password). Nur in die Ingest-Request-Header. None -> /tax-rates +
    # /business-registrations 200 disabled (Bulk könnte nie ingestet werden).
    regio_user: SecretStr | None = None
    regio_pass: SecretStr | None = None


class MobilithekSettings(BaseSettings):
    """Mobilithek-mTLS: Zertifikat + Per-Quelle-Abo-IDs (SSRF-Allowlist).

    Die aboId im Mobilithek-Pull-URL stammt NIE aus User-Input, nur aus diesen
    Feldern (RESEARCH Pitfall 7). None = Quelle nicht auflösbar. Abo-IDs aus
    mobilithek.info -> Meine Abonnements -> Detailseite (HTTPS-Zugriffspunkt).
    """

    # cert_path optional (None = keine Live-Quelle nutzbar); cert_password SecretStr
    # (nie im Klartext geloggt). httpx/ssl können .p12 nicht direkt lesen ->
    # cryptography konvertiert beim Start zu PEM (infra/mobilithek.py).
    mobilithek_cert_path: str | None = None
    mobilithek_cert_password: SecretStr | None = None
    koeln_traffic_flow_abo_id: str | None = None
    koeln_baustellen_live_abo_id: str | None = None
    koeln_ereignisse_live_abo_id: str | None = None
    koeln_lez_live_abo_id: str | None = None
    berlin_verkehrsmeldungen_abo_id: str | None = None
    # dortmund_parking seit 2026-06-13 keylos -> ungenutzt, bleibt für SSRF-Konsistenz.
    dortmund_parking_abo_id: str | None = None
    kiel_zaehlstellen_abo_id: str | None = None
    eround_charging_abo_id: str | None = None
    bremen_baustellen_abo_id: str | None = None
    # Hannover Verkehrsmeldungen (DATEX II V2 SituationPublication, path-Pull).
    # Abo-ID aus dem Portal (Detailseite HTTPS-Zugriffspunkt); SSRF-Allowlist
    # (aboId NIE aus User-Input).
    hannover_verkehrsmeldungen_abo_id: str | None = None
    # Frankfurt Parkdaten: ZWEI Abos (DATEX II V3, container-Pull). Das dynamische
    # Abo trägt die Belegung (frei/Auslastung), das statische die Stammdaten
    # (Name/Geo/Kapazitaet); der Adapter joint beide über die parkingRecord-ID.
    # Beide als SSRF-Allowlist (aboId NIE aus User-Input).
    frankfurt_parking_abo_id: str | None = None
    frankfurt_parking_static_abo_id: str | None = None
    # Wuppertal Parkdaten: ZWEI Abos (DATEX II V2 ParkingFacility, path-Pull).
    # dynamisch = Belegung, statisch = Stammdaten; Join über parkingFacility-ID.
    wuppertal_parking_abo_id: str | None = None
    wuppertal_parking_static_abo_id: str | None = None
    # Magdeburg Parkdaten: ZWEI Abos (DATEX II V2 ParkingFacility, path-Pull).
    # dynamisch = Belegung, statisch = Stammdaten; Join über parkingFacility-ID.
    # Beide als SSRF-Allowlist (aboId NIE aus User-Input).
    magdeburg_parking_abo_id: str | None = None
    magdeburg_parking_static_abo_id: str | None = None


class TransitSettings(BaseSettings):
    """GTFS-Realtime-Quellenumschaltung (Phase 19, Live-OePNV-Verspätungen)."""

    # Quellen-Umschaltung (RESEARCH Pattern 7): "gtfs_de" (verifizierte Primär-
    # quelle, kein Key) | "mobilithek_delfi" (mTLS-Pull, liefert Stand 2026-06-12
    # 422 = no_data). Default gtfs_de, bis das Mobilithek-Abo echte Pakete liefert.
    transit_rt_source: str = "gtfs_de"
    # Mobilithek-DELFI-Realtime-Abo-ID als SSRF-Allowlist (aboId NIE aus User-Input).
    # None = Quelle nicht auflösbar. Owner-Abo nur in der gitignored .env
    # (INFRANODE_TRANSIT_RT_DELFI_ABO_ID).
    transit_rt_delfi_abo_id: str | None = None


class BulkPathSettings(BaseSettings):
    """Lokale Pfade für Offline-/Batch-Ingest (NICHT im Request-Pfad).

    None = Batch nicht lauffähig bzw. der Batch holt die Quelle direkt keylo vom
    Upstream. Die Ingests laufen ausschließlich als manueller Batch (python -m).
    """

    # GTFS-ZIPs für den Batch-Ingest (DATA-05). None = Batch bricht mit Exit 2 ab.
    delfi_gtfs_path: str | None = None
    hvv_gtfs_path: str | None = None
    # Phase 19: SEPARATER Statik-Pfad für die GTFS-RT-Auflösung. Der gtfs.de-Free-
    # Feed referenziert die gtfs.de-EIGENE Statik (numerische IDs, CC-BY-SA Tier B,
    # wöchentlich via transit.refresh erneuert). Darf NICHT auf das DELFI-Zip
    # zeigen (CC-BY 4.0 Tier A), sonst vermischen sich die Lizenzräume. None =
    # Fallback auf delfi_gtfs_path (Tests/Mobilithek-Quelle mit DELFI-IDs).
    gtfs_rt_static_path: str | None = None
    # Phase 8: Bulk-Dateien für den Offline-Ingest (None = Batch bricht mit Exit 2 ab).
    mastr_zip_path: str | None = None
    bkg_path: str | None = None
    bundeswahl_csv_path: str | None = None
    divi_csv_path: str | None = None
    # KBA-Bulk (DATA-27): None = Batch holt den Datensatz direkt keylos vom KBA-Portal.
    kba_source_path: str | None = None
    # Unfallatlas-Bulk (DATA-29): None = Batch holt das jüngste Jahr vom NRW-Portal.
    unfallatlas_source_path: str | None = None
    # INKAR-Bulk (DATA-32): None = Batch holt die Indikatoren live von www.inkar.de.
    inkar_source_path: str | None = None
    # BKA-PKS-Bulk (PKS-02): None = Batch probt das jüngste Jahr live von www.bka.de.
    bka_pks_source_path: str | None = None
    # BORIS-Bulk (DATA-35): None = Batch holt die Bodenrichtwerte live vom Landes-WFS.
    boris_source_path: str | None = None
    # Regionalstatistik-Bulk (DATA-37): None = Batch holt die Tabellen live vom
    # GENESIS-Webservice (regio_user/regio_pass).
    regio_source_path: str | None = None


class MonitoringSettings(BaseSettings):
    """Monitoring/Alarmierung/Selbstheilung (OPS-06/07/08).

    Notifier-Kanäle (ntfy + E-Mail), Dead-Man-Ping, externer Liveness-Ping. Token
    und Passwort sind SecretStr | None = None (fail-closed: ohne Wert kein Versand).
    """

    # ntfy: Push-Kanal. ntfy_topic ist faktisch ein Passwort (nur a-z/0-9/_/-).
    ntfy_url: str | None = None
    ntfy_topic: str | None = None
    ntfy_token: SecretStr | None = None
    # SMTP: E-Mail-Backup-Kanal. smtp_ssl=False = STARTTLS Port 587 (Default),
    # smtp_ssl=True = SMTP_SSL Port 465 (Decision SMTP-Transport-Modus).
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    smtp_to: str | None = None
    smtp_ssl: bool = False
    # Benachrichtigungs-Drossel (Flut-/Crash-Schutz): max. Anzahl NICHT-kritischer
    # Pushes (INFO/WARNING) je Zeitfenster und Prozess. Wird der Cap überschritten,
    # werden weitere Pushes unterdrückt (genau EIN Hinweis pro Fenster geht
    # raus); CRITICAL ist ausgenommen und kommt immer durch. Schützt vor ntfy-/SMTP-
    # Floods (Thread-/Socket-Stau, Mail-Provider-Sperre) bei Erstkontakt-/MCP-Bursts.
    # 0 oder negativ = Drossel aus.
    notify_max_per_window: int = 20
    notify_window_seconds: int = 60
    # Dead-Man-Ping (Kuma-Push bzw. Healthchecks.io) je Timer-Job; per systemd-Drop-in
    # überschreibbar. None = kein Ping.
    deadman_url: str | None = None
    # Dead-Man-Ping für den 08:00-Digest (CR-05): eigener Kuma-Push-Monitor
    # ("digest", ~26 h Heartbeat). None = kein Ping (graceful).
    digest_deadman_url: str | None = None
    # Externer Box-Liveness-Ping (Finding 8): der Watchdog pingt diese URL am Ende
    # jedes erfolgreichen Laufs. Die URL trägt eine UUID und ist wie ein Secret zu
    # behandeln (nur via .env/systemd-Drop-in, nie ins Repo).
    healthchecks_url: str | None = None
    # Self-Heal-Reprobe (A, 2026-06-14): opt-in-Liste hart deaktivierter Quellen,
    # deren Upstream der Watchdog periodisch direkt anprobt, um beim Wiederaufleben
    # genau einen "X ist wieder reaktivierbar"-ntfy zu schicken. Format (komma-
    # separiert): ``source=https://probe.url,source2=https://probe.url2``. Nur für
    # Quellen, die man bei einer Störung BEWUSST per enable_*-Toggle abgeschaltet
    # hat; enabled gelassene Quellen heilen ohnehin über den persistenten Breaker.
    # Probe-URLs sind Owner-kontrolliert (kein User-Input -> kein SSRF). Leer = aus.
    selfheal_probes: str = ""


class Settings(
    CoreSettings,
    RateLimitSettings,
    AdminSettings,
    SourceToggleSettings,
    CredentialSettings,
    MobilithekSettings,
    TransitSettings,
    BulkPathSettings,
    MonitoringSettings,
):
    """Validierte Anwendungs-Settings aus Env/.env (Prefix INFRANODE_).

    Erbt alle Felder flach aus den thematischen Mixin-Klassen oben. ``model_config``
    steht NUR hier (greift via Vererbung für alle geerbten Felder). Zugriff bleibt
    flach: ``settings.enable_vgn``, ``getattr(settings, "enable_<name>")``,
    Env ``INFRANODE_<FELD>`` - unverändert gegenüber der früheren flachen Klasse.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="INFRANODE_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Singleton-Zugriff auf die Settings (gecached für den Prozess)."""
    return Settings()
