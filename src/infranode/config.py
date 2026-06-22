"""Zentrale Konfiguration (FND-02).

Eine einzige ``Settings``-Quelle liest ``.env`` + Umgebungsvariablen mit dem
Prefix ``INFRANODE_``. Per-Source ``enable_*``-Flags ermoeglichen Graceful
Degradation; Schluessel-Felder sind ``SecretStr | None`` (Default None =
Quelle nicht nutzbar, kein Secret im Code).

WARTBARKEIT (2026-06-21): Die Felder sind in thematische Mixin-Klassen
gruppiert (CoreSettings, RateLimitSettings, AdminSettings, SourceToggleSettings,
CredentialSettings, MobilithekSettings, TransitSettings, BulkPathSettings,
MonitoringSettings). ``Settings`` erbt von allen; pydantic merged die Felder zu
EINER flachen Klasse. Das ist bewusst KEINE verschachtelte Struktur
(``settings.admin.password``): die Felder bleiben flach (``settings.enable_vgn``),
weil (a) die Quellen-Toggles an mehreren Stellen dynamisch ueber
``getattr(settings, f"enable_{name}")`` aufgeloest werden (sources/live/cities/
watchdog/admin) und (b) verschachtelte Modelle die Env-Variablennamen aendern
wuerden (``INFRANODE_ADMIN__PASSWORD`` statt ``INFRANODE_ADMIN_PASSWORD``), was
die produktive .env braeche. Neue Felder in die thematisch passende Mixin-Klasse.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class CoreSettings(BaseSettings):
    """Infrastruktur und Laufzeit: Logging, Redis, CORS, HTTP, Datenpfad."""

    log_level: str = "INFO"
    redis_url: str = "redis://redis:6379/0"
    # CORS: die oeffentliche API ist KEYLOS, READ-ONLY und liefert offene Daten,
    # die explizit fuer beliebige Browser-/Client-Apps gedacht sind (Vibecoder,
    # Dashboards, Starter-Templates auf Vercel/Netlify/localhost). Fuer so eine
    # oeffentliche Datendienst-API ist "*" der Standard (vgl. Open-Meteo,
    # Nominatim): die alte Whitelist hat jeden Cross-Origin-Browser-Client still
    # blockiert. Bewusste Abkehr von der frueheren "nie *"-Regel; sie galt fuer
    # credentialed APIs. Hier wird allow_credentials in main.py auf False
    # gesetzt, sobald "*" aktiv ist (CORS-Spec: "*" + credentials schliessen sich
    # aus). Das Admin-Dashboard ist same-origin (Cookie cs_admin SameSite=strict)
    # und von CORS unberuehrt. Per INFRANODE_CORS_ORIGINS auf eine Whitelist
    # einschraenkbar (dann wird wieder credentialed CORS verwendet).
    cors_origins: list[str] = ["*"]

    # Optionaler Override des Upstream-User-Agents (RES-05). None = die
    # USER_AGENT-Konstante aus infra/http.py greift; per INFRANODE_HTTP_USER_AGENT
    # ueberschreibbar (z.B. fuer Staging-Kennzeichnung).
    http_user_agent: str | None = None

    # Wurzelpfad des lokalen Datenverzeichnisses. Per INFRANODE_ARCHIVE_DIR
    # ueberschreibbar, damit Tests nach tmp_path schreiben statt ins echte data/.
    # (Feld-/Env-Name aus Kompatibilitaetsgruenden unveraendert.)
    archive_dir: str = "data/archive"


class RateLimitSettings(BaseSettings):
    """IP-Rate-Limiting (API-06). Echter DoS-Schutz liegt bei Cloudflare."""

    # limits/slowapi-Format ("<zahl>/<einheit>"). Die API ist keylos/offen; das
    # IP-Budget gilt fuer ALLE Clients (DoS-/Scraping-Schutz). Gestaffelt
    # (Security-Haertung 2026-06-21): ein BURST-Budget pro Minute fuer kurze
    # Data-Science-/Dashboard-Spitzen UND ein nachhaltiges STUNDEN-Budget gegen
    # Dauer-Scraping. Frueher pauschal 300/min (= 18.000/h pro IP), was
    # nachhaltiges Abgrasen kaum bremste; jetzt 120/min Burst + 3000/h nachhaltig
    # (Schnitt 50/min). Beide gelten gleichzeitig: ANON_LIMIT kombiniert sie
    # semikolon-getrennt, slowapi/limits ``parse_many`` liest das als MEHRERE
    # Limits. Per INFRANODE_LIMIT_ANON ueberschreibbar (z.B. Tests).
    limit_anon: str = "120/minute"
    # Nachhaltiges Zweit-Limit ueber ein laengeres Fenster (leer = nur limit_anon).
    limit_anon_sustained: str = "3000/hour"
    # Striktes Budget am Admin-Login gegen Passwort-Brute-Force (Security-Audit
    # 2026-06-10, HIGH-1). Eigener strenger @limiter.limit-Decorator auf der Route.
    limit_admin_login: str = "5/minute"
    # Sync-Redis-URI fuer slowapis eigene limits-Storage (Pitfall 1: slowapi teilt
    # NICHT den async-Pool app.state.redis, sondern oeffnet eine eigene sync-
    # Verbindung zum SELBEN Redis-Server). None = in der Anwendung auf redis_url
    # zurueckfallen (gleicher Server, getrennte Verbindung).
    limit_storage_uri: str | None = None
    # Aggregiertes Subnetz-Limit gegen VERTEILTE Bots (Scraping-Haertung): das
    # IP-Limit oben fasst nur eine einzelne IP; ein Botnet/Cloud-Range mit vielen
    # IPs umgeht es. Dieses Zweit-Limit bremst pro /24 (IPv4) bzw. /64 (IPv6).
    # BEWUSST hoch (Default 1200/min = ~10x das IP-Burst-Budget), damit legitime
    # NAT-/Campus-Nutzer hinter einer gemeinsamen IP NICHT getroffen werden; es
    # greift erst, wenn aus EINEM Subnetz untypisch viele Anfragen kommen. Leer
    # ("") = deaktiviert. Per INFRANODE_LIMIT_SUBNET ueberschreibbar.
    limit_subnet: str = "1200/minute"
    subnet_ipv4_prefix: int = 24
    subnet_ipv6_prefix: int = 64
    # Optionaler Cloudflare-Bot-Score-Schwellwert (1-99; 0 = deaktiviert). Greift
    # NUR, wenn Cloudflare den Header ``cf-bot-score`` setzt (Bot Management /
    # Enterprise). Bei Free/Pro fehlt der Header -> der Check ist ein No-op-Hook,
    # der automatisch wirksam wird, sobald Scores verfuegbar sind. Anfragen mit
    # Score < Schwellwert werden mit 403 abgelehnt (sehr wahrscheinlich Bots).
    bot_score_min: int = 0


class AdminSettings(BaseSettings):
    """Admin-Dashboard (OPS-01/02): Cookie-Session, Netzwerk-Guard."""

    # admin_password schuetzt /admin per Cookie-Session (fail-closed: None = Login
    # unmoeglich, Best-Practice 2). Beide Secret-Felder sind SecretStr, damit der
    # Wert nie im Klartext geloggt/serialisiert wird. admin_session_secret signiert
    # das Session-Cookie (itsdangerous, >=32 Byte empfohlen). admin_log_max
    # begrenzt den Redis-Ringpuffer der Request-Logs. admin_cookie_https_only setzt
    # das Secure-Flag des Cookies (Default True; nur in Tests/lokal ohne TLS auf
    # False stellbar).
    admin_password: SecretStr | None = None
    admin_session_secret: SecretStr | None = None
    admin_log_max: int = 200
    admin_cookie_https_only: bool = True
    # Defense-in-Depth fuer /admin (T-18-15): Code-seitiger Netzwerk-Guard.
    # Betrieblich ist /admin bereits Tailnet-only (Caddy gibt oeffentlich 404,
    # ``tailscale serve`` laeuft ohne Funnel, ufw oeffnet 80/443 nur fuer
    # Cloudflare). Dieser Guard blockt zusaetzlich JEDE Anfrage mit oeffentlich-
    # routbarer Client-IP (real_client_ip) mit 404, falls die Caddy-404-Regel je
    # entfaellt. Loopback/private/Tailnet-CGNAT (100.64.0.0/10) sind als nicht-
    # global routbar immer erlaubt; admin_trusted_networks erlaubt optional
    # zusaetzliche (auch global routbare) CIDR (leer = nur die nicht-globale Regel).
    admin_trusted_networks: list[str] = []


class SourceToggleSettings(BaseSettings):
    """Per-Quelle ``enable_*``-Toggles (Graceful Degradation).

    WICHTIG: Jeder Toggle-Name MUSS exakt zum _KNOWN_SOURCES-Eintrag (sources.py)
    und zum SourceId-Wert passen, da er dynamisch ueber
    ``getattr(settings, f"enable_{name}")`` aufgeloest wird. Deshalb bleiben diese
    Felder flach auf der Settings-Klasse (keine Verschachtelung). Keyed Live-
    Quellen stehen trotz Default True ohne Credentials auf "disabled".
    """

    # Phase 4/6: Basis-Quellen.
    enable_wikidata: bool = True
    enable_openaq: bool = False
    enable_dwd: bool = True
    enable_overpass: bool = True
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
    # Phase 8: account-gated Quellen Default False (bis Credentials gesetzt sind);
    # keylose Bulk-/Seed-Quellen Default True (Toggle steuert nur die Route, nicht
    # den Offline-Ingest). enable_genesis = Demografie + Krankenhaus, enable_zensus
    # = Zensus-Host, enable_divi = klinikscharfe DIVI-Live-Quelle (Tier C, optional).
    enable_genesis: bool = False
    # GENESIS-Regionalstatistik-Trio (Arbeitslosenquote/Tourismus/Bautaetigkeit je
    # Kreis, DATA-28). Eigener Toggle mit korrektem Header-Auth-Adapter, ohne den
    # Demografie-Pfad zu beruehren. Braucht dieselben genesis_username/-password.
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
    # Unfallatlas (Strassenverkehrsunfaelle je Kreis, Bulk-CSV, keylos DL-DE/BY).
    enable_unfallatlas: bool = True
    # INKAR/BBSR sozialoekonomische Indikatoren je Kreis (Bulk, keylos DL-DE/BY).
    enable_inkar: bool = True
    # Tankerkoenig Spritpreise (MTS-K, CC BY 4.0). KEYED: Default True, aber ohne
    # tankerkoenig_key liefert die Route 200 disabled. Toggle-Name == SourceId.
    enable_tankerkoenig: bool = True
    # DATA-33: GBFS-Bike-/Scooter-Sharing (Live, aggregiert, Primaer Nextbike CC0).
    # Keylos -> Default True; pro System Lizenz fail-closed gegen Tier-A-Allowlist.
    enable_gbfs: bool = True
    # DATA-34: DB Timetables (Bahnhof-Abfahrten Metropolen-Hbf inkl. Fernverkehr).
    # KEYED: ohne db_client_id/db_api_key liefert die Route 200 disabled.
    enable_db_timetables: bool = True
    # DATA-35: BORIS amtliche Bodenrichtwerte je Stadt (Bulk, keylos, foederierter
    # WFS pro Bundesland). Read-only Store-Lesung im Request-Pfad.
    enable_boris: bool = True
    # DATA-36: StaDa Station Data (Bahnhofs-Katalog je Stadt). Keyed ueber denselben
    # DB-API-Marketplace wie db_timetables (db_client_id/db_api_key, kein eigener Key).
    enable_stada: bool = True
    # DATA-37: Regionalstatistik.de (Realsteuer-Hebesaetze 71231 + Gewerbean-/
    # -abmeldungen 52311). Bulk-Ingest -> SQLite (Read-only im Request-Pfad); ohne
    # regio_user/regio_pass 200 disabled (Daten koennten nie ingestet werden).
    enable_regionalstatistik: bool = True
    # DATA-38 (Stufe 1): PVGIS-Solar (EU JRC PVcalc, keylose Live-Rechen-API). PVGIS
    # rechnet jede EU-Koordinate -> alle Register-Staedte abgedeckt. Keylos ->
    # Default True. Toggle-Name == SourceId.SOLAR == _KNOWN_SOURCES-Eintrag.
    enable_solar: bool = True
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
    # "open-data" frei zugaenglich, Support-Bestaetigung 2026-06-10) -> Default True.
    enable_destination_one: bool = True
    enable_koeln_events: bool = True
    # Phase 19: GTFS-Realtime Trip Updates (Live-OePNV-Verspaetungen). Default False
    # bis aktiv geschaltet. Aufloesung via getattr(settings, "enable_gtfs_rt").
    enable_gtfs_rt: bool = False
    # DATA-24/25/26: Live-Abfahrten/-Verkehrslage. enable_hvv_geofox KEYED (Default
    # False, braucht hvv_api_key + hvv_user). enable_vgn keylos (offene VAG-Puls-
    # API, CC-BY 4.0). enable_hamburg_verkehrslage keylos (OAF/GeoJSON, DL-DE/BY 2.0).
    enable_hvv_geofox: bool = False
    enable_vgn: bool = True
    enable_hamburg_verkehrslage: bool = True
    # Phase 20: Mobilithek-mTLS-Live-Quellen (Live = Cert + Abo noetig, daher alle
    # Default False bis Zertifikat und Abo-ID gesetzt sind). Ausnahme:
    # dortmund_parking ist seit 2026-06-13 KEYLOS (direkter Opendatasoft-Feed) ->
    # Default True; dortmund_parking_abo_id ungenutzt (bleibt fuer SSRF-Konsistenz).
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
    # Live = Cert + Abo noetig -> Default False, bis Zertifikat + Abo-ID gesetzt.
    enable_hannover_verkehrsmeldungen: bool = False
    # Frankfurt am Main Parkdaten (Mobilithek DATEX II V3 Parking, statisch +
    # dynamisch gejoint, DL-DE/BY 2.0). Live = Cert + Abo noetig -> Default False,
    # bis Zertifikat und beide Abo-IDs gesetzt sind.
    enable_frankfurt_parking: bool = False
    # Wuppertal Parkdaten (Mobilithek DATEX II V2 ParkingFacility, statisch +
    # dynamisch gejoint, DL-DE/Zero 2.0). Live = Cert + Abo -> Default False.
    enable_wuppertal_parking: bool = False


class CredentialSettings(BaseSettings):
    """API-Keys/Credentials externer Quellen. Alle Secrets als SecretStr | None.

    None = Quelle nicht nutzbar (Graceful Degradation). Secrets gehen NUR in
    Header/Body/Query des jeweiligen Upstream-Requests, NIE in Cache-Key/Response/
    Log. Werte stammen aus der gitignored .env (Env-Namen ueber den Prefix).
    """

    openaq_api_key: SecretStr | None = None
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
    # DATA-30: Tankerkoenig-API-Key. Nur in den Query-Parameter ``apikey``. None ->
    # Route liefert 200 source_status="disabled". Env INFRANODE_TANKERKOENIG_KEY.
    tankerkoenig_key: SecretStr | None = None
    # DATA-34: DB-Timetables-Credentials (DB API Marketplace). Nur in die Header
    # DB-Client-Id/DB-Api-Key. None -> Route 200 disabled.
    db_client_id: SecretStr | None = None
    db_api_key: SecretStr | None = None
    # DATA-37: Regionalstatistik.de GENESIS-Webservice (Header-Auth username/
    # password). Nur in die Ingest-Request-Header. None -> /tax-rates +
    # /business-registrations 200 disabled (Bulk koennte nie ingestet werden).
    regio_user: SecretStr | None = None
    regio_pass: SecretStr | None = None


class MobilithekSettings(BaseSettings):
    """Mobilithek-mTLS: Zertifikat + Per-Quelle-Abo-IDs (SSRF-Allowlist).

    Die aboId im Mobilithek-Pull-URL stammt NIE aus User-Input, nur aus diesen
    Feldern (RESEARCH Pitfall 7). None = Quelle nicht aufloesbar. Abo-IDs aus
    mobilithek.info -> Meine Abonnements -> Detailseite (HTTPS-Zugriffspunkt).
    """

    # cert_path optional (None = keine Live-Quelle nutzbar); cert_password SecretStr
    # (nie im Klartext geloggt). httpx/ssl koennen .p12 nicht direkt lesen ->
    # cryptography konvertiert beim Start zu PEM (infra/mobilithek.py).
    mobilithek_cert_path: str | None = None
    mobilithek_cert_password: SecretStr | None = None
    koeln_traffic_flow_abo_id: str | None = None
    koeln_baustellen_live_abo_id: str | None = None
    koeln_ereignisse_live_abo_id: str | None = None
    koeln_lez_live_abo_id: str | None = None
    berlin_verkehrsmeldungen_abo_id: str | None = None
    # dortmund_parking seit 2026-06-13 keylos -> ungenutzt, bleibt fuer SSRF-Konsistenz.
    dortmund_parking_abo_id: str | None = None
    kiel_zaehlstellen_abo_id: str | None = None
    eround_charging_abo_id: str | None = None
    bremen_baustellen_abo_id: str | None = None
    # Hannover Verkehrsmeldungen (DATEX II V2 SituationPublication, path-Pull).
    # Abo-ID aus dem Portal (Detailseite HTTPS-Zugriffspunkt); SSRF-Allowlist
    # (aboId NIE aus User-Input).
    hannover_verkehrsmeldungen_abo_id: str | None = None
    # Frankfurt Parkdaten: ZWEI Abos (DATEX II V3, container-Pull). Das dynamische
    # Abo traegt die Belegung (frei/Auslastung), das statische die Stammdaten
    # (Name/Geo/Kapazitaet); der Adapter joint beide ueber die parkingRecord-ID.
    # Beide als SSRF-Allowlist (aboId NIE aus User-Input).
    frankfurt_parking_abo_id: str | None = None
    frankfurt_parking_static_abo_id: str | None = None
    # Wuppertal Parkdaten: ZWEI Abos (DATEX II V2 ParkingFacility, path-Pull).
    # dynamisch = Belegung, statisch = Stammdaten; Join ueber parkingFacility-ID.
    wuppertal_parking_abo_id: str | None = None
    wuppertal_parking_static_abo_id: str | None = None


class TransitSettings(BaseSettings):
    """GTFS-Realtime-Quellenumschaltung (Phase 19, Live-OePNV-Verspaetungen)."""

    # Quellen-Umschaltung (RESEARCH Pattern 7): "gtfs_de" (verifizierte Primaer-
    # quelle, kein Key) | "mobilithek_delfi" (mTLS-Pull, liefert Stand 2026-06-12
    # 422 = no_data). Default gtfs_de, bis das Mobilithek-Abo echte Pakete liefert.
    transit_rt_source: str = "gtfs_de"
    # Mobilithek-DELFI-Realtime-Abo-ID als SSRF-Allowlist (aboId NIE aus User-Input).
    # None = Quelle nicht aufloesbar. Owner-Abo nur in der gitignored .env
    # (INFRANODE_TRANSIT_RT_DELFI_ABO_ID).
    transit_rt_delfi_abo_id: str | None = None


class BulkPathSettings(BaseSettings):
    """Lokale Pfade fuer Offline-/Batch-Ingest (NICHT im Request-Pfad).

    None = Batch nicht lauffaehig bzw. der Batch holt die Quelle direkt keylo vom
    Upstream. Die Ingests laufen ausschliesslich als manueller Batch (python -m).
    """

    # GTFS-ZIPs fuer den Batch-Ingest (DATA-05). None = Batch bricht mit Exit 2 ab.
    delfi_gtfs_path: str | None = None
    hvv_gtfs_path: str | None = None
    # Phase 19: SEPARATER Statik-Pfad fuer die GTFS-RT-Aufloesung. Der gtfs.de-Free-
    # Feed referenziert die gtfs.de-EIGENE Statik (numerische IDs, CC-BY-SA Tier B,
    # woechentlich via transit.refresh erneuert). Darf NICHT auf das DELFI-Zip
    # zeigen (CC-BY 4.0 Tier A), sonst vermischen sich die Lizenzraeume. None =
    # Fallback auf delfi_gtfs_path (Tests/Mobilithek-Quelle mit DELFI-IDs).
    gtfs_rt_static_path: str | None = None
    # Phase 8: Bulk-Dateien fuer den Offline-Ingest (None = Batch bricht mit Exit 2 ab).
    mastr_zip_path: str | None = None
    bkg_path: str | None = None
    bundeswahl_csv_path: str | None = None
    divi_csv_path: str | None = None
    # KBA-Bulk (DATA-27): None = Batch holt den Datensatz direkt keylos vom KBA-Portal.
    kba_source_path: str | None = None
    # Unfallatlas-Bulk (DATA-29): None = Batch holt das juengste Jahr vom NRW-Portal.
    unfallatlas_source_path: str | None = None
    # INKAR-Bulk (DATA-32): None = Batch holt die Indikatoren live von www.inkar.de.
    inkar_source_path: str | None = None
    # BORIS-Bulk (DATA-35): None = Batch holt die Bodenrichtwerte live vom Landes-WFS.
    boris_source_path: str | None = None
    # Regionalstatistik-Bulk (DATA-37): None = Batch holt die Tabellen live vom
    # GENESIS-Webservice (regio_user/regio_pass).
    regio_source_path: str | None = None


class MonitoringSettings(BaseSettings):
    """Monitoring/Alarmierung/Selbstheilung (OPS-06/07/08).

    Notifier-Kanaele (ntfy + E-Mail), Dead-Man-Ping, externer Liveness-Ping. Token
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
    # Dead-Man-Ping (Kuma-Push bzw. Healthchecks.io) je Timer-Job; per systemd-Drop-in
    # ueberschreibbar. None = kein Ping.
    deadman_url: str | None = None
    # Dead-Man-Ping fuer den 08:00-Digest (CR-05): eigener Kuma-Push-Monitor
    # ("digest", ~26 h Heartbeat). None = kein Ping (graceful).
    digest_deadman_url: str | None = None
    # Externer Box-Liveness-Ping (Finding 8): der Watchdog pingt diese URL am Ende
    # jedes erfolgreichen Laufs. Die URL traegt eine UUID und ist wie ein Secret zu
    # behandeln (nur via .env/systemd-Drop-in, nie ins Repo).
    healthchecks_url: str | None = None
    # Self-Heal-Reprobe (A, 2026-06-14): opt-in-Liste hart deaktivierter Quellen,
    # deren Upstream der Watchdog periodisch direkt anprobt, um beim Wiederaufleben
    # genau einen "X ist wieder reaktivierbar"-ntfy zu schicken. Format (komma-
    # separiert): ``source=https://probe.url,source2=https://probe.url2``. Nur fuer
    # Quellen, die man bei einer Stoerung BEWUSST per enable_*-Toggle abgeschaltet
    # hat; enabled gelassene Quellen heilen ohnehin ueber den persistenten Breaker.
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
    steht NUR hier (greift via Vererbung fuer alle geerbten Felder). Zugriff bleibt
    flach: ``settings.enable_vgn``, ``getattr(settings, "enable_<name>")``,
    Env ``INFRANODE_<FELD>`` - unveraendert gegenueber der frueheren flachen Klasse.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="INFRANODE_",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Singleton-Zugriff auf die Settings (gecached fuer den Prozess)."""
    return Settings()
