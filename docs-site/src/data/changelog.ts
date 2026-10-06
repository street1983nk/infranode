// Single Source für den öffentlichen Changelog. Speist die Changelog-Seiten
// (src/pages/changelog.astro + en/changelog.astro) UND die RSS-Feeds
// (src/pages/changelog/feed.xml.ts + en/changelog/feed.xml.ts). Ein Eintrag
// beschreibt eine für Konsumenten sichtbare Änderung: neue Datenquelle/Stadt,
// Verhaltensänderung, Fix oder Deprecation. Neueste zuerst.
//
// kind steuert das Badge und die Einordnung:
//   added      neue Datenart, neue Stadt, neuer Endpunkt/Kanal
//   changed    geändertes Verhalten (relevant für produktive Nutzer)
//   fixed      Fehlerbehebung
//   deprecated angekündigte Abkündigung (mit Frist)
//   removed    entfernt
//
// date: ISO yyyy-mm-dd (Veröffentlichungsdatum der Änderung). Prosa mit echten
// Umlauten, keine Em-Dashes, keine Emojis. endpoint (optional) = operationId
// für einen Link in die API-Referenz.

export type ChangeKind = "added" | "changed" | "fixed" | "deprecated" | "removed";

export interface ChangelogLang {
  title: string;
  body: string;
}

export interface ChangelogEntry {
  date: string;
  kind: ChangeKind;
  de: ChangelogLang;
  en: ChangelogLang;
  endpoint?: string;
}

// Badge-Beschriftung je Sprache. Farben liegen im Seiten-CSS (data-kind).
export const KIND_LABEL: Record<ChangeKind, { de: string; en: string }> = {
  added: { de: "Neu", en: "Added" },
  changed: { de: "Geändert", en: "Changed" },
  fixed: { de: "Behoben", en: "Fixed" },
  deprecated: { de: "Abkündigung", en: "Deprecated" },
  removed: { de: "Entfernt", en: "Removed" },
};

export const changelog: ChangelogEntry[] = [
  {
    date: "2026-09-15",
    kind: "fixed",
    de: {
      title: "Spritpreise: Anfrage-Spitzen werden zeitversetzt beantwortet statt mit 503-Wellen",
      body:
        "Tankerkönig erlaubt eine Anfrage je Minute für alle Städte zusammen. " +
        "Dieser Platz wurde bisher nur in dem Moment vergeben, in dem jemand " +
        "fragte. Kommen viele Anfragen als Block über alle Städte, bekamen ein " +
        "bis zwei davon den Platz der Minute, der Rest ging leer aus. Selten " +
        "abgefragte Städte erreichten dadurch nie wieder eine Auffrischung, ihr " +
        "Zwischenstand lief aus, und danach kam für sie dauerhaft 503. Ab " +
        "sofort geht eine Anfrage, die den Platz der Minute verliert, nicht " +
        "mehr verloren: die Stadt wird vorgemerkt und der Abruf in den " +
        "folgenden Minuten nachgeholt, über denselben Weg und dieselbe Bremse " +
        "wie jede normale Anfrage. Ist der Platz gerade vergeben, wird still " +
        "gewartet statt gedrängelt. Für Nutzende heißt das: eine Stadt, die " +
        "lange niemand abgefragt hat, antwortet nach kurzer Zeit wieder mit " +
        "Daten statt mit 503. Abgerufen wird weiterhin nur, was jemand " +
        "tatsächlich angefragt hat; eine Vormerkung verfällt nach sechs " +
        "Stunden. An den Fenstern für Frische und Zwischenstand ändert sich " +
        "nichts.",
    },
    en: {
      title: "Fuel prices: request peaks are now answered with a delay instead of 503 waves",
      body:
        "Tankerkoenig allows one request per minute for all cities combined. " +
        "That slot used to be handed out only at the moment someone asked. " +
        "When many requests arrive as a sweep across all cities, one or two of " +
        "them won the slot and the rest got nothing. Rarely requested cities " +
        "therefore never got refreshed again, their cached value expired, and " +
        "from then on they returned 503 permanently. From now on a request " +
        "that loses the slot is no longer lost: the city is queued and the " +
        "fetch is caught up over the following minutes, using the same path " +
        "and the same rate limit as any normal request. If the slot is taken, " +
        "the run waits quietly instead of pushing. For consumers this means a " +
        "city nobody has queried for a long time answers with data again " +
        "shortly afterwards instead of 503. Only what someone actually " +
        "requested is ever fetched, and a queued entry expires after six " +
        "hours. The freshness and stale windows are unchanged.",
    },
    endpoint: "getCityFuelPrices",
  },
  {
    date: "2026-09-07",
    kind: "changed",
    de: {
      title: "Spritpreise: Frische nach dem Tagesverlauf, Zwischenstand für einen Tag",
      body:
        "Seit dem 1. April 2026 dürfen Kraftstoffpreise nur noch einmal je " +
        "Kalendertag steigen, und zwar um 12:00 Uhr; Senkungen bleiben " +
        "jederzeit möglich (Kraftstoffpreisanpassungsgesetz). Der Tagesverlauf " +
        "der Daten ist damit bekannt statt geraten, und das Frische-Fenster " +
        "der Spritpreise folgt ihm jetzt: zwischen 22 und 5 Uhr vier Stunden, " +
        "vormittags 60 Minuten, im Erhöhungsfenster von 11:50 bis 12:20 fünf " +
        "Minuten, von 12:20 bis 19 Uhr 20 Minuten und abends 45 Minuten. " +
        "Zusätzlich endet jedes Fenster spätestens um 11:50 Uhr: ein Preis, " +
        "der um 11 Uhr geholt wurde, gilt nicht über den Mittagssprung hinaus " +
        "als frisch. Die zehn Minuten Vorlauf haben einen Grund, das " +
        "Bundeskartellamt beobachtet 96,5 Prozent der Erhöhungen im Fenster " +
        "11:50 bis 12:10. Zweite Änderung: eine einmal abgefragte Stadt bleibt " +
        "jetzt bis zu 24 Stunden aus dem Cache beantwortbar, vorher drei " +
        "Stunden. Grund sind 151 Fehlerantworten (503) in 24 Stunden, knapp " +
        "29 Prozent der Anfragen. Tankerkönig erlaubt eine Anfrage je Minute " +
        "für alle Städte zusammen, und jede Stadt, die drei Stunden niemand " +
        "abfragte, war wieder kalt und verlor gegen dieses Limit. Damit das " +
        "ehrlich bleibt, nennt data.retrieved_at ab jetzt den Zeitpunkt des " +
        "Abrufs bei der Quelle und nicht mehr den der Antwort; cache_status " +
        "STALE weist den Zwischenstand weiterhin aus. Wer das Alter der Preise " +
        "prüfen will, liest also diese beiden Felder. Die Quelle sieht dadurch " +
        "keine einzige Anfrage mehr als vorher: es bleibt bei einer Anfrage je " +
        "Minute, nur auf Nutzeranfrage, ohne dauerhafte Speicherung und ohne " +
        "Abrufe im Hintergrund.",
    },
    en: {
      title: "Fuel prices: freshness follows the day, cached data for a day",
      body:
        "Since 1 April 2026, German fuel prices may rise only once per " +
        "calendar day, at 12:00 local time; decreases remain possible at any " +
        "time (Kraftstoffpreisanpassungsgesetz, the fuel price adjustment " +
        "act). The daily shape of the data is therefore known rather than " +
        "guessed, and the freshness window of the fuel prices now follows it: " +
        "four hours between 22:00 and 05:00, 60 minutes in the morning, five " +
        "minutes inside the increase window from 11:50 to 12:20, 20 minutes " +
        "from 12:20 to 19:00 and 45 minutes in the evening. On top of that, " +
        "every window ends at 11:50 at the latest: a price fetched at 11:00 " +
        "does not count as fresh beyond the noon step. The ten minutes of " +
        "lead time are deliberate, the federal cartel office observes 96.5 " +
        "percent of all increases in the window from 11:50 to 12:10. Second " +
        "change: a city that has been requested once now stays answerable " +
        "from the cache for up to 24 hours, previously three hours. The " +
        "reason is 151 error responses (503) in 24 hours, close to 29 percent " +
        "of all requests. Tankerkönig allows one request per minute for all " +
        "cities together, and every city that nobody asked for during three " +
        "hours was cold again and lost against that limit. To keep this " +
        "honest, data.retrieved_at now names the time of the upstream fetch " +
        "instead of the time of the response; cache_status STALE still marks " +
        "cached data. Reading both fields tells you exactly how old a price " +
        "is. The source sees no additional requests at all: it stays at one " +
        "request per minute, only on a user request, with nothing stored " +
        "permanently and nothing fetched in the background.",
    },
    endpoint: "getCityFuelPrices",
  },
  {
    date: "2026-09-06",
    kind: "changed",
    de: {
      title: "Spritpreise: drei Stunden Zwischenstand, eine Anfrage darf auf den freien Abruf warten",
      body:
        "Nachtrag zum selben Tag: das Stundenraster vieler Clients traf genau " +
        "das 60-Minuten-Fenster. Wer eine Stadt stündlich abfragt, kam an, " +
        "wenn der Zwischenstand gerade abgelaufen war, und ein kalter Eintrag " +
        "verliert gegen das Limit von einer Anfrage je Minute. Im Nachmittags" +
        "protokoll kamen 13 von 48 Bremsen-503 exakt 45 bis 61 Minuten nach " +
        "der vorigen Anfrage derselben Stadt. Deshalb zwei Änderungen. Erstens " +
        "bleibt eine einmal abgefragte Stadt jetzt bis zu drei Stunden aus dem " +
        "Cache beantwortbar, nach den ersten fünf Minuten als STALE " +
        "gekennzeichnet (cache_status); ein Stundenrhythmus findet damit " +
        "immer einen Zwischenstand. Zweitens darf genau EINE Anfrage je Quelle " +
        "auf den nächsten freien Abruf warten, höchstens 20 Sekunden; früher " +
        "wurde jede Restwartezeit über 12 Sekunden sofort abgewiesen, obwohl " +
        "27 von 48 dieser 503 nur Sekunden vom nächsten freien Abruf entfernt " +
        "waren. Jede weitere gleichzeitige Anfrage derselben Quelle wird " +
        "weiterhin sofort mit 503 und Retry-After beantwortet, statt sich " +
        "anzustellen. Die Quelle sieht dadurch keine einzige Anfrage mehr als " +
        "vorher: es bleibt bei einer Anfrage je Minute, nur auf Nutzeranfrage " +
        "und weiterhin ohne dauerhafte Speicherung und ohne Abrufe im " +
        "Hintergrund. Wer lieber sofort einen 503 als bis zu 20 Sekunden " +
        "Wartezeit sieht, kann den Betreiber-Schalter " +
        "INFRANODE_SOURCE_PACE_WAIT_MAX_S auf 12 setzen.",
    },
    en: {
      title: "Fuel prices: three hours of cached data, one request may wait for the free slot",
      body:
        "Follow-up on the same day: many clients poll on the hour, which hit " +
        "the 60 minute window exactly. Asking for a city once an hour meant " +
        "arriving just after the cached value had expired, and a cold entry " +
        "loses against the limit of one request per minute. In the afternoon " +
        "log, 13 of 48 brake 503s came exactly 45 to 61 minutes after the " +
        "previous request for the same city. Hence two changes. First, a city " +
        "that has been requested once now stays answerable from the cache for " +
        "up to three hours, marked STALE in cache_status after the first five " +
        "minutes, so an hourly rhythm always finds a cached value. Second, " +
        "exactly ONE request per source may wait for the next free upstream " +
        "call, at most 20 seconds; previously any remaining wait above 12 " +
        "seconds was rejected right away, even though 27 of 48 of those 503s " +
        "were only seconds away from the next free call. Every further " +
        "concurrent request for the same source still gets an immediate 503 " +
        "with Retry-After instead of queueing. The source sees no additional " +
        "requests at all: it stays at one request per minute, only on a user " +
        "request, still with nothing stored permanently and nothing fetched " +
        "in the background. If you prefer an immediate 503 over a wait of up " +
        "to 20 seconds, the operator switch INFRANODE_SOURCE_PACE_WAIT_MAX_S " +
        "can be set to 12.",
    },
    endpoint: "getCityFuelPrices",
  },
  {
    date: "2026-09-06",
    kind: "fixed",
    de: {
      title: "Spritpreise: weniger 503 unter dem Ein-Anfrage-pro-Minute-Limit, Retry-After am 503",
      body:
        "Die Bremse vom 4. September hält das Limit der Quelle ein, hatte aber " +
        "eine Nebenwirkung: eine Stadt, die eine Viertelstunde lang niemand " +
        "abgefragt hatte, fiel aus dem Cache und verlor dann gegen die Bremse, " +
        "also 503 statt Preise. Zwei Änderungen. Erstens bleibt eine einmal " +
        "abgefragte Stadt jetzt bis zu 60 Minuten aus dem Cache beantwortbar, " +
        "nach den ersten fünf Minuten als STALE gekennzeichnet (cache_status). " +
        "Es wird weiterhin nichts dauerhaft gespeichert und nichts im " +
        "Hintergrund abgerufen, die Quelle wird nur auf Nutzeranfrage gefragt. " +
        "Zweitens trägt ein 503, der aus " +
        "der Bremse stammt, jetzt einen Retry-After-Header mit den Sekunden bis " +
        "zum nächsten freien Abruf; Meldung und Hinweis im Fehler-Envelope sagen " +
        "das auch in Worten. Ein 503 ohne Retry-After bedeutet weiterhin, dass " +
        "die Quelle selbst nicht antwortet.",
    },
    en: {
      title: "Fuel prices: fewer 503s under the one-request-per-minute limit, Retry-After on 503",
      body:
        "The brake from 4 September keeps the source's limit, but it had a side " +
        "effect: a city nobody had asked for in fifteen minutes dropped out of " +
        "the cache and then lost against the brake, so 503 instead of prices. " +
        "Two changes. First, a city that has been requested once now stays " +
        "answerable from the cache for up to 60 minutes, marked STALE in " +
        "cache_status after the first five. Nothing is stored permanently and " +
        "nothing is fetched in the background; the source is only asked on a " +
        "user request. Second, a " +
        "503 that comes from the brake now carries a Retry-After header with the " +
        "seconds until the next free upstream call; message and hint in the error " +
        "envelope say the same in words. A 503 without Retry-After still means " +
        "the source itself is not answering.",
    },
    endpoint: "getCityFuelPrices",
  },
  {
    date: "2026-09-04",
    kind: "changed",
    de: {
      title: "Spritpreise: Aggregat-Bremse auf das Limit der Quelle gezogen",
      body:
        "Die Spritpreise stammen von Tankerkönig, und deren Limit ist eine " +
        "Anfrage pro Minute. Unsere Ausgangsbremse liess bisher deutlich mehr " +
        "zu, was in einer vorübergehenden Sperre unserer Server-Adresse " +
        "endete. Die Bremse entspricht jetzt dem Limit der Quelle. Für den " +
        "Normalfall ändert sich nichts: jede Stadt liegt fünf Minuten im " +
        "Cache, wiederholte Abfragen derselben Stadt sind also unverändert " +
        "schnell. Neu ist, dass eine Anfrage auf eine Stadt, die gerade nicht " +
        "im Cache liegt, mit 503 und dem Code upstream_unavailable antworten " +
        "kann, wenn der letzte Abruf bei der Quelle weniger als eine Minute " +
        "zurückliegt. Vorher wäre dieselbe Anfrage stattdessen lange hängen " +
        "geblieben. Wer viele Städte hintereinander abfragt, sollte 503 " +
        "abfangen und die Anfrage später wiederholen; der Hinweis in der " +
        "Antwort nennt GET /api/v1/health für den Zustand der Quellen.",
    },
    en: {
      title: "Fuel prices: outbound pacing aligned with the source limit",
      body:
        "Fuel prices come from Tankerkönig, whose limit is one request per " +
        "minute. Our outbound pacing allowed considerably more than that, " +
        "which ended in a temporary block of our server address. The pacing " +
        "now matches the source limit. Nothing changes for the normal case: " +
        "every city stays in the cache for five minutes, so repeated requests " +
        "for the same city are as fast as before. What is new is that a " +
        "request for a city that is currently not cached may answer with 503 " +
        "and the code upstream_unavailable when the last upstream call was " +
        "less than a minute ago. Previously the same request would have hung " +
        "for a long time instead. If you query many cities in sequence, catch " +
        "503 and retry later; the hint in the response points to " +
        "GET /api/v1/health for the state of the sources.",
    },
    endpoint: "getCityFuelPrices",
  },
  {
    date: "2026-08-31",
    kind: "removed",
    de: {
      title: "Alte Feldnamen entfernt (Abkündigung vom 01.08.)",
      body:
        "Die am 01.08.2026 abgekündigten alten Feldnamen sind fristgerecht " +
        "nach 30 Tagen aus den Antworten entfernt. Jedes betroffene Feld " +
        "trug den Wert seit dem 01.08. doppelt; ab jetzt gilt nur noch der " +
        "kanonische englische Name. Betroffen sind unter anderem stand " +
        "(jetzt as_of), bundesland (federal_state), stichtag " +
        "(reference_date), granularity (coverage_granularity), die " +
        "deutschen Steuer-, Gewerbe- und Insolvenzfelder, die rohen " +
        "Quell-Feldnamen von Baumkataster, Denkmalliste und Baustellen, " +
        "dist_km (distance_km), zip/category (post_code/station_category), " +
        "plz/ort (post_code/place), stop_id an den Bahnhofstafeln " +
        "(trip_stop_id) sowie die sechs camelCase-Rohfelder des " +
        "Autobahn-Feeds. Die vollständige Liste je Endpunkt steht im " +
        "Abkündigungs-Register der Dokumentation. Die abgekündigten " +
        "Altpfade unter /api/v1/live mit deutschen Slugs bleiben wie " +
        "zugesagt als Alias erhalten.",
    },
    en: {
      title: "Old field names removed (deprecated on 1 August)",
      body:
        "The old field names deprecated on 2026-08-01 have been removed " +
        "from responses after the announced 30-day window. Each affected " +
        "field had been carrying its value twice since 1 August; from now " +
        "on only the canonical English name is returned. This covers, " +
        "among others, stand (now as_of), bundesland (federal_state), " +
        "stichtag (reference_date), granularity (coverage_granularity), " +
        "the German tax, business-registration and insolvency fields, the " +
        "raw source field names of the tree cadastre, heritage register " +
        "and roadworks sources, dist_km (distance_km), zip/category " +
        "(post_code/station_category), plz/ort (post_code/place), stop_id " +
        "on the station boards (trip_stop_id), and the six camelCase raw " +
        "fields of the Autobahn feed. The full per-endpoint list lives in " +
        "the documentation's deprecation register. The deprecated legacy " +
        "paths under /api/v1/live with German slugs remain available as " +
        "aliases, as promised.",
    },
  },
  {
    date: "2026-08-31",
    kind: "deprecated",
    de: {
      title: "Veranstaltungen: title wird zu name (neue Frist bis 30.09.)",
      body:
        "Der Veranstaltungsname im Endpunkt /cities/{slug}/events heißt " +
        "jetzt kanonisch name, wie in allen anderen Datenarten. Das alte " +
        "Feld title liefert bis auf Weiteres denselben Wert und wird " +
        "frühestens am 30.09.2026 entfernt. Hintergrund: die Ankündigung " +
        "vom 01.08. hatte den Nachfolger name für die " +
        "destination.one-Städte nie ausgeliefert; ein Entfernen heute " +
        "hätte ein Feld ohne verfügbaren Ersatz gestrichen. Deshalb läuft " +
        "eine neue, saubere Frist.",
      },
    en: {
      title: "Events: title becomes name (new window until 30 September)",
      body:
        "The event name on /cities/{slug}/events is now canonically " +
        "called name, as in every other data type. The old field title " +
        "keeps returning the same value for now and will be removed no " +
        "earlier than 2026-09-30. Background: the 1 August announcement " +
        "never actually shipped the successor field name for the " +
        "destination.one cities, so removing title today would have " +
        "dropped a field without an available replacement. Hence a fresh, " +
        "clean window.",
    },
    endpoint: "getCityEvents",
  },
  {
    date: "2026-08-24",
    kind: "fixed",
    de: {
      title: "Bahnhofstafeln: ein gestörter Bahnhof reißt die Stadt-Tafel nicht mehr",
      body:
        "Die Endpunkte /cities/{slug}/station-departures und " +
        "/cities/{slug}/station-arrivals aggregieren mehrere Bahnhöfe einer " +
        "Stadt. Bisher führte eine Störung der Deutsche-Bahn-Schnittstelle " +
        "für einen einzelnen Bahnhof dazu, dass die gesamte Tafel mit 503 " +
        "antwortete, auch wenn die übrigen Bahnhöfe lieferten (so geschehen " +
        "am 24.08. für Berlin, rund 25 Minuten). Jetzt wird ein gestörter " +
        "Bahnhof übersprungen und die Tafel aus den erreichbaren Bahnhöfen " +
        "gebaut. Erst wenn alle Bahnhöfe einer Stadt gestört sind und kein " +
        "Cache vorliegt, antwortet der Endpunkt weiterhin ehrlich mit 503 " +
        "upstream_unavailable. Es werden dabei nie veraltete Abfahrten " +
        "ausgeliefert, nur weniger Bahnhöfe.",
    },
    en: {
      title: "Station boards: one disrupted station no longer breaks the city board",
      body:
        "The endpoints /cities/{slug}/station-departures and " +
        "/cities/{slug}/station-arrivals aggregate several stations per " +
        "city. Previously, an upstream failure of the Deutsche Bahn API for " +
        "a single station caused the whole board to respond with 503 even " +
        "though the remaining stations were fine (this happened on Aug 24 " +
        "for Berlin, for about 25 minutes). A disrupted station is now " +
        "skipped and the board is built from the healthy stations. Only if " +
        "every station of a city fails and no cache is available does the " +
        "endpoint still respond honestly with 503 upstream_unavailable. " +
        "Stale departures are never served, just fewer stations.",
    },
    endpoint: "getCityStationDepartures",
  },
  {
    date: "2026-08-11",
    kind: "removed",
    de: {
      title: "Intensivbetten-Daten entfernt (DIVI-Intensivregister)",
      body:
        "Der Endpunkt /cities/{slug}/icu-live entfällt ersatzlos, ebenso das " +
        "Feld icu_capacity und das Meta-Feld icu_latest unter " +
        "/cities/{slug}/health. Grund ist die Zweckbindung der Daten: Das " +
        "Robert Koch-Institut hat der Weiterverbreitung und der " +
        "Live-Durchleitung der Daten des DIVI-Intensivregisters " +
        "widersprochen. Sie werden nach Paragraf 13 Absatz 7 " +
        "Infektionsschutzgesetz ausschließlich zur Feststellung der " +
        "Auslastung von Krankenhauskapazitäten erhoben; eine Weitergabe an " +
        "Dritte ist davon nicht gedeckt. Das RKI prüft zudem, die Daten " +
        "künftig gar nicht mehr bereitzustellen. Der Endpunkt lieferte " +
        "zuletzt ohnehin keine Daten mehr aus (source_status disabled). " +
        "Alle übrigen Krankenhaus-Kennzahlen unter /health bleiben " +
        "unverändert.",
    },
    en: {
      title: "ICU bed data removed (DIVI intensive care registry)",
      body:
        "The endpoint /cities/{slug}/icu-live is discontinued without " +
        "replacement, as are the icu_capacity field and the icu_latest meta " +
        "field on /cities/{slug}/health. The reason is the purpose " +
        "limitation attached to the data: the Robert Koch Institute objected " +
        "to redistribution and live pass-through of DIVI intensive care " +
        "registry data. Under Section 13(7) of the German Infection " +
        "Protection Act the data is collected solely to assess hospital " +
        "capacity utilisation, which does not cover passing it on to third " +
        "parties. The institute is also considering discontinuing the data " +
        "entirely. The endpoint had already stopped serving data " +
        "(source_status disabled). All other hospital figures under /health " +
        "remain unchanged.",
    },
  },
  {
    date: "2026-08-01",
    kind: "changed",
    de: {
      title: "Einheitlich englische Quellnamen (meta.source)",
      body:
        "30 Quellnamen in meta.source, city_source und der Quellenliste " +
        "tragen jetzt einheitlich englische Namen. Die wichtigsten " +
        "Umbenennungen: hamburg_baustellen, muenchen_baustellen, " +
        "dortmund_baustellen, rostock_baustellen und bremen_baustellen " +
        "heißen jetzt *_roadworks; koeln_baustellen_live heißt " +
        "koeln_roadworks_live, koeln_ereignisse_live heißt " +
        "koeln_incidents_live, koeln_verkehr heißt koeln_road_events; " +
        "berlin_verkehrsmeldungen und hannover_verkehrsmeldungen heißen " +
        "*_traffic_reports; hamburg_verkehrslage heißt " +
        "hamburg_traffic_situation; kiel_zaehlstellen heißt " +
        "kiel_counting_stations; die acht *_radzaehl-Quellen (muenchen, " +
        "leipzig, hamburg, berlin, stuttgart, koeln, essen, duesseldorf) " +
        "heißen *_bike_counts; denkmal heißt heritage, baumkataster heißt " +
        "tree_cadastre, koeln_wartezeiten heißt koeln_wait_times, " +
        "hochwasser heißt lhp, feiertage heißt holidays; die München-Familie " +
        "muenchen_parkhaeuser/parkraum/park_ride/mobilitaetspunkte/" +
        "radparken heißt jetzt muenchen_parking, muenchen_parking_onstreet, " +
        "muenchen_park_and_ride, muenchen_mobility_points und " +
        "muenchen_bike_parking. Da meta.source ein Einzelwert ist, ist kein " +
        "Duplikat-Zeitraum mit beiden Namen möglich; der Wechsel ist hart. " +
        "Bestandsdaten und historische Daten mit alten Namen werden beim " +
        "Lesen automatisch auf die neuen Namen normalisiert. Alte " +
        "INFRANODE_*-Umgebungsvariablennamen bleiben als Alias gültig.",
    },
    en: {
      title: "Uniform English source names (meta.source)",
      body:
        "30 source names in meta.source, city_source and the sources list " +
        "now carry uniform English names. The most important renames: " +
        "hamburg_baustellen, muenchen_baustellen, dortmund_baustellen, " +
        "rostock_baustellen and bremen_baustellen are now *_roadworks; " +
        "koeln_baustellen_live is koeln_roadworks_live, " +
        "koeln_ereignisse_live is koeln_incidents_live, koeln_verkehr is " +
        "koeln_road_events; berlin_verkehrsmeldungen and " +
        "hannover_verkehrsmeldungen are *_traffic_reports; " +
        "hamburg_verkehrslage is hamburg_traffic_situation; " +
        "kiel_zaehlstellen is kiel_counting_stations; the eight " +
        "*_radzaehl sources (muenchen, leipzig, hamburg, berlin, " +
        "stuttgart, koeln, essen, duesseldorf) are *_bike_counts; denkmal " +
        "is heritage, baumkataster is tree_cadastre, koeln_wartezeiten is " +
        "koeln_wait_times, hochwasser is lhp, feiertage is holidays; the " +
        "Munich family muenchen_parkhaeuser/parkraum/park_ride/" +
        "mobilitaetspunkte/radparken is now muenchen_parking, " +
        "muenchen_parking_onstreet, muenchen_park_and_ride, " +
        "muenchen_mobility_points and muenchen_bike_parking. Because " +
        "meta.source is a single value, no dual-name transition period is " +
        "possible; the switch is hard. Stored and historical data with old " +
        "names are normalized to the new names on read. Old INFRANODE_* " +
        "environment variable names remain valid as aliases.",
    },
  },
  {
    date: "2026-08-01",
    kind: "deprecated",
    de: {
      title: "Einheitlich englische Feldnamen in elf Datenarten",
      body:
        "Elf Datenarten tragen ihre Payload-Felder jetzt zusätzlich unter " +
        "kanonischen englischen Namen: flood (stand heißt as_of), " +
        "fire-danger (bundesland heißt federal_state), election " +
        "(granularity heißt coverage_granularity, Werte city/partial statt " +
        "stadt/teilweise), icu-live (kreis_id/kreis_name/datum heißen " +
        "district_id/district_name/report_date; gilt ebenso für das " +
        "icu_capacity-Payload unter health), land-values (stichtag " +
        "heißt reference_date), tax-rates (gewerbesteuer_hebesatz/" +
        "grundsteuer_a/b/c/stichtag heißen trade_tax_rate/property_tax_a/" +
        "b/c/reference_date), business-registrations (anmeldungen/" +
        "abmeldungen/saldo/jahr heißen registrations/deregistrations/" +
        "balance/year) und insolvencies (unternehmensinsolvenzen/" +
        "uebrige_schuldner_insolvenzen/jahr heißen corporate_insolvencies/" +
        "other_debtor_insolvencies/year). Dazu kommen die Einzel-Einträge " +
        "in Listen: road-events je Stadtquelle (München, Rostock, Dortmund, " +
        "Dresden/Leipzig, Hamburg; z.B. beschreibung heißt description, " +
        "von/bis heißen start/end), die Klinik-Liste in icu-live " +
        "(bezeichnung/ort/letzte_meldung heißen name/place/last_report), " +
        "tree-cadastre (z.B. art_dtsch heißt species, pflanzjahr heißt " +
        "planting_year; die gedeckelte Stichprobe je Antwort liegt während " +
        "der Übergangszeit bei 225 statt 350 Bäumen) und heritage (z.B. typ " +
        "heißt type, bezeichnung heißt name). Die alten deutschen Felder " +
        "bleiben bis zum 31. August 2026 mit identischen Werten erhalten " +
        "und werden danach entfernt. Clients sollten auf die neuen " +
        "Feldnamen migrieren.",
    },
    en: {
      title: "Consistent English field names across eleven data types",
      body:
        "Eleven data types now also carry their payload fields under " +
        "canonical English names: flood (stand becomes as_of), fire-danger " +
        "(bundesland becomes federal_state), election (granularity becomes " +
        "coverage_granularity with the values city/partial instead of " +
        "stadt/teilweise), icu-live (kreis_id/kreis_name/datum become " +
        "district_id/district_name/report_date; this also applies to the " +
        "icu_capacity payload under health), land-values (stichtag " +
        "becomes reference_date), tax-rates (gewerbesteuer_hebesatz/" +
        "grundsteuer_a/b/c/stichtag become trade_tax_rate/property_tax_a/" +
        "b/c/reference_date), business-registrations (anmeldungen/" +
        "abmeldungen/saldo/jahr become registrations/deregistrations/" +
        "balance/year) and insolvencies (unternehmensinsolvenzen/" +
        "uebrige_schuldner_insolvenzen/jahr become corporate_insolvencies/" +
        "other_debtor_insolvencies/year). On top of that, the individual " +
        "entries inside lists follow suit: road-events per city source " +
        "(Munich, Rostock, Dortmund, Dresden/Leipzig, Hamburg; e.g. " +
        "beschreibung becomes description, von/bis become start/end), the " +
        "hospital list in icu-live (bezeichnung/ort/letzte_meldung become " +
        "name/place/last_report), tree-cadastre (e.g. art_dtsch becomes " +
        "species, pflanzjahr becomes planting_year; the capped sample per " +
        "response is 225 instead of 350 trees during the transition " +
        "period) and heritage (e.g. typ becomes type, bezeichnung becomes " +
        "name). The old German fields keep carrying identical values " +
        "until 31 August 2026 and will be removed afterwards. Clients " +
        "should migrate to the new field names.",
    },
  },
  {
    date: "2026-08-01",
    kind: "changed",
    endpoint: "getLiveHamburgTrafficSituation",
    de: {
      title: "Einheitlich englische Endpunkt-Namen für Live-Routen",
      body:
        "Sieben Live-Routen tragen jetzt englische kanonische Pfade: " +
        "/live/{city}/baustellen heißt /live/{city}/roadworks, " +
        "/live/{city}/ereignisse heißt /live/{city}/incidents, " +
        "/live/berlin/verkehrsmeldungen und /live/hannover/verkehrsmeldungen " +
        "heißen jeweils .../traffic-reports, /live/koeln/umweltzone heißt " +
        "/live/koeln/low-emission-zone, /live/kiel/zaehlstellen heißt " +
        "/live/kiel/counting-stations und /live/hamburg/verkehrslage heißt " +
        "/live/hamburg/traffic-situation. Die alten deutschen Pfade bleiben " +
        "als deprecated Aliases mit unverändertem Envelope erhalten und " +
        "tragen einen Deprecation- sowie einen Link-Header auf den " +
        "jeweiligen Nachfolger. Clients sollten auf die neuen Pfade " +
        "migrieren.",
    },
    en: {
      title: "Consistent English endpoint names for live routes",
      body:
        "Seven live routes now use English canonical paths: " +
        "/live/{city}/baustellen becomes /live/{city}/roadworks, " +
        "/live/{city}/ereignisse becomes /live/{city}/incidents, " +
        "/live/berlin/verkehrsmeldungen and /live/hannover/verkehrsmeldungen " +
        "become .../traffic-reports, /live/koeln/umweltzone becomes " +
        "/live/koeln/low-emission-zone, /live/kiel/zaehlstellen becomes " +
        "/live/kiel/counting-stations and /live/hamburg/verkehrslage becomes " +
        "/live/hamburg/traffic-situation. The old German paths remain " +
        "available as deprecated aliases with an unchanged envelope and " +
        "carry a Deprecation header plus a Link header pointing to the " +
        "respective successor. Clients should migrate to the new paths.",
    },
  },
  {
    date: "2026-08-01",
    kind: "fixed",
    endpoint: "getLiveHamburgVerkehrslage",
    de: {
      title: "Hamburg: Live-Verkehrslage wieder verfügbar",
      body:
        "Die Echtzeit-Verkehrslage für Hamburg (api.hamburg.de, OGC API " +
        "Features) war seit Mitte Juli vorübergehend deaktiviert, nachdem " +
        "Abrufe wiederholt in Zeitüberschreitungen liefen; der Endpunkt " +
        "meldete in dieser Zeit source_status disabled. Nach Rückmeldung " +
        "des Landesbetriebs Geoinformation und Vermessung Hamburg (keine " +
        "IP-Sperre, Upstream antwortet wieder zuverlässig) ist die Quelle " +
        "seit dem 1. August wieder aktiv und liefert wie zuvor die " +
        "Netz-Zusammenfassung sowie die nicht-fließenden Straßenabschnitte.",
    },
    en: {
      title: "Hamburg: live traffic situation available again",
      body:
        "The real-time traffic situation for Hamburg (api.hamburg.de, OGC " +
        "API Features) had been temporarily disabled since mid-July after " +
        "upstream requests repeatedly timed out; during that period the " +
        "endpoint reported source_status disabled. Following feedback from " +
        "the Hamburg state agency for geo-information (LGV) confirming no " +
        "IP block and a reliably responding upstream, the source is active " +
        "again since 1 August and delivers the network summary and " +
        "congested road segments as before.",
    },
  },
  {
    date: "2026-08-01",
    kind: "added",
    endpoint: "getCityCouncilPapers",
    de: {
      title: "Ratsinformationen: Freiburg im Breisgau als achte Stadt",
      body:
        "Die Datenart council-papers deckt jetzt acht lizenzgeklärte Städte " +
        "ab: Dresden, Köln, Düsseldorf, Münster, Leipzig, Magdeburg, " +
        "Osnabrück und neu Freiburg im Breisgau. Das Ratsbüro der Stadt " +
        "Freiburg hat die Lizenz der OParl-Schnittstelle auf Nachfrage " +
        "schriftlich bestätigt (Datenlizenz Deutschland Namensnennung 2.0), " +
        "im Bestand liegen rund 13.900 Vorlagen, Anträge und Beschlüsse ab " +
        "2014. Außerdem nennt die Antwort jetzt data.total, den " +
        "Gesamtbestand zu den aktiven Filtern; bisher war nur die " +
        "Seitenlänge (count) enthalten, den Bestand konnte ein Client nicht " +
        "ermitteln, ohne bis zur leeren Seite zu blättern.",
    },
    en: {
      title: "Council papers: Freiburg im Breisgau joins as the eighth city",
      body:
        "The council-papers data type now covers eight licence-cleared " +
        "cities: Dresden, Cologne, Düsseldorf, Münster, Leipzig, Magdeburg, " +
        "Osnabrück and, new, Freiburg im Breisgau. The city of Freiburg's " +
        "council office confirmed the licence of its OParl endpoint in " +
        "writing (Data licence Germany attribution 2.0); the corpus holds " +
        "roughly 13,900 papers, motions and resolutions from 2014 onwards. " +
        "Responses also carry data.total now, the full count for the active " +
        "filters; previously only the page length (count) was included, so " +
        "clients could not learn the corpus size without paging to the end.",
    },
  },
  {
    date: "2026-07-30",
    kind: "added",
    endpoint: "getCityBikeParking",
    de: {
      title: "Radparken München: 47.518 Stellplätze abrufbar",
      body:
        "Neu ist /cities/{slug}/bike-parking mit dem Radparkraum einer Stadt. " +
        "Für München sind das 3.233 Abstellanlagen mit 47.518 Stellplätzen, je " +
        "Anlage mit Bauform (Anlehnbügel, Rahmenhalter, Doppelstockanlage), " +
        "Überdachung, Beleuchtung und Bike-and-Ride-Kennzeichnung. 1.972 " +
        "Anlagen mit 33.060 Plätzen liegen an ÖPNV-Haltestellen, 316 sind " +
        "überdacht, 86 sind Doppelstockanlagen. Lastenradanlagen stehen " +
        "getrennt (103 Anlagen, 281 Plätze), weil sie für andere Fahrzeuge " +
        "ausgelegt sind. Dazu die zwanzig größten Standorte, die größte ist " +
        "die Riesstraße 69 mit 392 Plätzen. " +
        "Gezählt wird ausdrücklich nur der Bestand: die Quelle führt im selben " +
        "Datensatz auch 156 geplante, 306 abgebaute und 25 außer Betrieb " +
        "genommene Anlagen. Deren Plätze mitzuzählen würde den heutigen " +
        "Radparkraum um rund 17 Prozent zu hoch ausweisen, deshalb stehen sie " +
        "als eigene Zahlen daneben. Quelle ist das Mobilitätsreferat der " +
        "Landeshauptstadt München (DL-DE/BY 2.0), Anlass war ein Hinweis aus " +
        "dem IT-Referat der Stadt.",
    },
    en: {
      title: "Bike parking Munich: 47,518 spaces available",
      body:
        "New endpoint /cities/{slug}/bike-parking serves the bike parking " +
        "stock of a city. For Munich that is 3,233 facilities with 47,518 " +
        "spaces, each with construction type, covering, lighting and a " +
        "bike-and-ride flag. 1,972 facilities with 33,060 spaces sit at " +
        "public transport stops, 316 are covered, 86 are double-deck racks. " +
        "Cargo bike facilities are reported separately (103 facilities, 281 " +
        "spaces) because they are built for different vehicles. Plus the " +
        "twenty largest locations, the biggest being Riesstrasse 69 with 392 " +
        "spaces. " +
        "Only the in-service stock is counted: the source also lists 156 " +
        "planned, 306 removed and 25 out-of-service facilities in the same " +
        "dataset. Counting their spaces would overstate today's bike parking " +
        "by roughly 17 percent, so they are reported as separate figures. " +
        "Source is the mobility department of the City of Munich " +
        "(DL-DE/BY 2.0).",
    },
  },
  {
    date: "2026-07-29",
    kind: "added",
    endpoint: "getCityParkingOnstreet",
    de: {
      title: "Drei neue Parken-Datenarten für München: Straßenparkraum, P+R und Mobilitätspunkte",
      body:
        "Bisher lieferte /cities/muenchen/parking 73 Parkhäuser mit Name, " +
        "Adresse und Koordinate. Dazu kommen jetzt drei eigene Datenarten, " +
        "alle aus offenen Quellen der Landeshauptstadt München " +
        "(DL-DE/BY 2.0, keylos). " +
        "/cities/{slug}/parking-onstreet zeigt den Straßenparkraum: 13.657 " +
        "Segmente mit 101.615 Stellplätzen, aufgeschlüsselt nach 18 " +
        "Regelungsgruppen, 1.759 Straßen und 82 " +
        "Parkraummanagementgebieten, dazu 556 Behindertenparkplätze mit 909 " +
        "Plätzen und 560 Lieferzonen mit 1.806 Plätzen. Ausgeliefert werden " +
        "Summen und Aggregate, nicht die Rohsegmente. " +
        "/cities/{slug}/park-and-ride bringt 34 P+R-Anlagen mit 7.941 " +
        "Stellplätzen samt Preisen für Einzelfahrt, Zehnerkarte, Monat und " +
        "Jahr, Bauform, Einfahrtshöhe, Schrankenbetrieb und ÖPNV-Anbindung, " +
        "dazu 34 B+R-Anlagen mit 5.574 Radplätzen. 27 Anlagen tragen eine " +
        "Belegungsprognose. Die stammt aus historischen Erfahrungswerten und " +
        "ist als solche gekennzeichnet: eine Echtzeit-Belegung veröffentlicht " +
        "München nicht offen. " +
        "/cities/{slug}/mobility-points liefert 120 Mobilitätspunkte mit 636 " +
        "Carsharing-Stellplätzen, je Punkt mit Taxi-Stellplätzen, Ladepunkten " +
        "getrennt nach AC und DC, Abstellflächen für Roller, Leihräder, " +
        "Lastenräder und Mopeds, Radservicestation und Luftpumpe sowie der " +
        "Anbindung an Bus, Tram, U-Bahn und S-Bahn. Dazu 909 " +
        "Carsharing-Parkflächen, 710 allgemeine und 199 stationsbasierte, je " +
        "mit Anbieter, Stadtbezirk, Inbetriebnahme und Koordinate. " +
        "Alle drei Datenarten decken zunächst nur München ab: eine andere " +
        "Stadt liefert 200 mit source_status=\"not_covered\" und der Liste " +
        "der abgedeckten Städte, nie einen Fehler. Anlass war die Bitte aus " +
        "der Münchner Open-Source-Community, die Abdeckung beim Parken zu " +
        "maximieren.",
    },
    en: {
      title: "Three new parking data types for Munich: on-street, park and ride, mobility points",
      body:
        "So far /cities/muenchen/parking served 73 car parks with name, " +
        "address and coordinate. Three data types of their own now join it, " +
        "all from open sources of the City of Munich (DL-DE/BY 2.0, " +
        "keyless). " +
        "/cities/{slug}/parking-onstreet covers on-street parking: 13,657 " +
        "segments with 101,615 spaces, broken down by 18 regulation groups, " +
        "1,759 streets and 82 parking management zones, plus 556 accessible " +
        "bays with 909 spaces and 560 loading zones with 1,806 spaces. " +
        "Sums and aggregates are served, not the raw segments. " +
        "/cities/{slug}/park-and-ride adds 34 park and ride facilities with " +
        "7,941 spaces including prices for single trip, ten-trip ticket, " +
        "month and year, structure type, entrance height, barrier operation " +
        "and public transport access, plus 34 bike and ride facilities with " +
        "5,574 bike spaces. 27 facilities carry an occupancy forecast. It is " +
        "derived from historical experience and labelled as such: Munich " +
        "does not publish real-time occupancy openly. " +
        "/cities/{slug}/mobility-points serves 120 mobility points with 636 " +
        "car-sharing bays, each point with taxi bays, charging points split " +
        "into AC and DC, parking areas for scooters, shared bikes, cargo " +
        "bikes and mopeds, bike service station and pump, plus access to " +
        "bus, tram, subway and suburban rail. On top of that 909 car-sharing " +
        "parking areas, 710 general and 199 station-based, each with " +
        "provider, city district, date of entry into service and " +
        "coordinate. " +
        "All three data types cover Munich only for now: another city " +
        "returns 200 with source_status=\"not_covered\" and the list of " +
        "covered cities, never an error.",
    },
  },
  {
    date: "2026-07-29",
    kind: "added",
    endpoint: "getCitySustainability",
    de: {
      title: "Themenseite zu den Nachhaltigkeits- und SDG-Indikatoren",
      body:
        "Die Datenart sustainability hat jetzt eine eigene Seite unter " +
        "/daten/nachhaltigkeit-api. Sie erklärt, was in den bis zu 53 " +
        "kommunalen Nachhaltigkeitsindikatoren steckt, dass die Reihe von " +
        "2006 bis 2023 läuft und wie der Jahresfilter ?from= und ?to= die " +
        "Antwort verkleinert. Offen benannt ist auch der Unterschied im " +
        "Umfang: kreisfreie Städte erreichen bis zu 53 Indikatoren, " +
        "kreisangehörige weniger, weil ein Teil der Kennzahlen erst ab " +
        "Kreisebene erhoben wird. Reine Dokumentation, an der API ändert " +
        "sich nichts.",
    },
    en: {
      title: "Topic page for the sustainability and SDG indicators",
      body:
        "The sustainability data type now has a page of its own at " +
        "/en/data/sustainability-api. It explains what the up to 53 " +
        "municipal sustainability indicators contain, that the series runs " +
        "from 2006 to 2023 and how the year filter ?from= and ?to= shrinks " +
        "the response. It also states the difference in scope openly: " +
        "district-free cities reach up to 53 indicators, cities inside a " +
        "district fewer, because part of the measures is only collected at " +
        "district level. Documentation only, the API is unchanged.",
    },
  },
  {
    date: "2026-07-28",
    kind: "added",
    endpoint: "getCityPopulationStructure",
    de: {
      title: "Neun weitere Zeitreihen-Datenarten aus dem Wegweiser Kommune",
      body:
        "Der Wegweiser-Bestand ist jetzt vollstaendig erschlossen. Bisher war " +
        "nur ein Achtel davon abrufbar (sustainability), der Rest lag " +
        "ungenutzt im Datensatz. Neu sind neun Datenarten, alle mit voller " +
        "Zeitreihe: population-structure (Altersaufbau, 110 Kennzahlen, mit " +
        "Prognose bis 2040), population-trend (Bevoelkerungsentwicklung, 70), " +
        "municipal-finance (kommunale Finanzen, 30), labour-market " +
        "(Arbeitsmarkt und Pendler, 40), integration (26), childcare " +
        "(Kinderbetreuung, 20), education-stats (Bildungsstatistik, 33), " +
        "social-situation (soziale Lage, 17) und care (Pflege, 11). " +
        "Damit sind 391 Kennzahlen je Stadt abrufbar statt 53. " +
        "Neu ist auch ein Jahresfilter: alle Wegweiser-Datenarten nehmen " +
        "?from= und ?to= und liefern dann nur das gewuenschte Fenster. Das " +
        "ist bei den grossen Datenarten praktisch noetig, population-structure " +
        "wiegt ungefiltert rund 90 KB. Ohne Filter bleibt alles wie bisher. " +
        "Drei Datenarten sind teilabgedeckt, weil die Quelle sie nicht fuer " +
        "jede Stadt gemeindescharf fuehrt: childcare 83 Staedte, care 73, " +
        "education-stats 70 (dort fehlen die kreisangehoerigen Staedte). " +
        "Bestehende Datenarten bleiben unberuehrt: tax-rates, unemployment " +
        "und indicators fuehren weiter ihre eigenen, teils aktuelleren Werte.",
    },
    en: {
      title: "Nine more time-series data types from Wegweiser Kommune",
      body:
        "The Wegweiser dataset is now fully accessible. Until today only an " +
        "eighth of it could be queried (sustainability); the rest sat unused " +
        "in the store. Nine data types are new, all with a full time series: " +
        "population-structure (age structure, 110 metrics, incl. a forecast " +
        "to 2040), population-trend (70), municipal-finance (30), " +
        "labour-market (labour market and commuters, 40), integration (26), " +
        "childcare (20), education-stats (33), social-situation (17) and " +
        "care (long-term care, 11). That makes 391 metrics per city " +
        "available instead of 53. " +
        "There is also a new year filter: every Wegweiser data type accepts " +
        "?from= and ?to= and then returns only that window. This matters for " +
        "the large ones, population-structure weighs about 90 KB unfiltered. " +
        "Without the filter nothing changes. " +
        "Three data types are partially covered because the source does not " +
        "publish them per municipality everywhere: childcare 83 cities, care " +
        "73, education-stats 70 (missing the cities that are part of a " +
        "district). Existing data types are untouched: tax-rates, " +
        "unemployment and indicators keep their own, partly more recent " +
        "values.",
    },
  },
  {
    date: "2026-07-27",
    kind: "added",
    de: {
      title: "Sechs Themenseiten zu Statistik-Datenarten",
      body:
        "Nach den Live-Datenarten sind jetzt die statistischen dran: neue " +
        "Seiten zu Hebesätzen, Einwohnerzahlen und Dichte, " +
        "Kriminalstatistik, Unfallatlas, Arbeitsmarkt sowie Gewerbe- und " +
        "Insolvenzdaten, jeweils auf Deutsch und Englisch. Jede Seite nennt " +
        "die echten Antwortfelder, die Quelle mit ihrer Lizenz und die " +
        "räumliche Auflösung. Letzteres ist hier wichtiger als bei " +
        "Live-Daten: Kriminalstatistik, Unfallatlas, Arbeitsmarkt und " +
        "Gewerbedaten liegen je Kreis vor, für Städte ohne eigenen Kreis " +
        "gilt also der Kreiswert. Die Hebesätze sind dagegen gemeindegenau. " +
        "Beides steht jetzt auf den Seiten, statt dass man es sich aus der " +
        "Antwort erschließen muss.",
    },
    en: {
      title: "Six topic pages for the statistical data types",
      body:
        "After the live data types the statistical ones follow: new pages " +
        "for municipal tax rates, population and density, crime " +
        "statistics, road accidents, the labour market and business and " +
        "insolvency data, each in German and English. Every page names the " +
        "actual response fields, the source with its licence and the " +
        "spatial resolution. That last point matters more here than for " +
        "live data: crime statistics, accidents, labour market and " +
        "business data are published per district, so for a city that is " +
        "not a district of its own the district value applies. Tax rates, " +
        "by contrast, are reported per municipality. Both facts are now on " +
        "the pages instead of having to be inferred from the response.",
    },
  },
  {
    date: "2026-07-27",
    kind: "added",
    de: {
      title: "Sechs neue Themenseiten und sieben neue MCP-Seiten",
      body:
        "Bisher hatten nur neun der 67 Datenarten eine eigene Seite, die " +
        "erklärt, was drinsteckt, woher es kommt und unter welcher Lizenz es " +
        "steht. Neu dazu kommen Ladesäulen, Spritpreise, Parken, Baustellen, " +
        "Pegelstände und Unwetterwarnungen, jeweils auf Deutsch und Englisch " +
        "mit Feldliste, Abdeckung, Quelle, Lizenz und häufigen Fragen. " +
        "Parallel gibt es sieben neue Seiten zu den passenden MCP-Werkzeugen " +
        "für KI-Assistenten, darunter Ladesäulen, Parken, Unwetterwarnungen, " +
        "Solar, Solarkataster, Vergabe und Ratsinformationen. Die " +
        "Themenseiten verlinken jetzt außerdem direkt die größten Städte, in " +
        "denen die jeweilige Datenart wirklich vorliegt.",
    },
    en: {
      title: "Six new topic pages and seven new MCP pages",
      body:
        "So far only nine of the 67 data types had a page of their own " +
        "explaining what they contain, where they come from and under which " +
        "licence they stand. New are EV charging, fuel prices, parking, " +
        "roadworks, water levels and weather warnings, each in German and " +
        "English with field list, coverage, source, licence and frequently " +
        "asked questions. In parallel there are seven new pages for the " +
        "matching MCP tools for AI assistants, among them charging, parking, " +
        "weather warnings, solar, solar cadastre, procurement and council " +
        "information. The topic pages now also link directly to the largest " +
        "cities where the respective data type is actually available.",
    },
  },
  {
    date: "2026-07-27",
    kind: "added",
    endpoint: "getCitySustainability",
    de: {
      title: "Neue Datenart sustainability: SDG-Indikatoren als Zeitreihe",
      body:
        "Neu ist /cities/{slug}/sustainability mit kommunalen Nachhaltigkeits- " +
        "und SDG-Indikatoren aus dem Wegweiser Kommune der Bertelsmann " +
        "Stiftung: Flächeninanspruchnahme, Naherholungsflächen, erneuerbare " +
        "Energie im Wohnungsneubau, Breitbandversorgung, Beschäftigung, " +
        "Bildung, soziale Teilhabe und weitere. Die Daten stehen unter CC0 " +
        "und sind für alle 84 Städte da. " +
        "Das Besondere: jeder Indikator trägt seine ganze ZEITREIHE, in der " +
        "Regel von 2006 bis 2023, dazu latest_year und latest_value für den " +
        "jüngsten Punkt. Damit lässt sich erstmals eine Entwicklung abfragen " +
        "statt nur ein Momentwert. Jahre ohne Wert fehlen in der Reihe, es " +
        "wird nie eine Null erfunden. " +
        "53 der Indikatoren liegen bei der Quelle erst ab Kreisebene vor und " +
        "fehlen deshalb bei den 14 kreisangehörigen Städten wie Hannover, " +
        "Aachen oder Göttingen. " +
        "Bestehende Datenarten bleiben unberührt: indicators (INKAR/BBSR), " +
        "tax-rates und unemployment führen weiterhin ihre eigenen, teils " +
        "aktuelleren Werte, die Bestände werden bewusst nicht vermischt.",
    },
    en: {
      title: "New data type sustainability: SDG indicators as a time series",
      body:
        "New endpoint /cities/{slug}/sustainability serves municipal " +
        "sustainability and SDG indicators from Wegweiser Kommune by " +
        "Bertelsmann Stiftung: land take, local recreation areas, renewable " +
        "energy in new residential buildings, broadband coverage, employment, " +
        "education, social participation and more. The data is CC0 licensed " +
        "and available for all 84 cities. " +
        "What makes it different: every indicator carries its full TIME " +
        "SERIES, typically 2006 to 2023, plus latest_year and latest_value " +
        "for the most recent point. For the first time you can query a " +
        "development instead of a single snapshot. Years without a value are " +
        "absent from the series, a zero is never invented. " +
        "53 of the indicators are only published from district level upwards " +
        "and are therefore missing for the 14 cities that are part of a " +
        "district, such as Hanover, Aachen or Göttingen. " +
        "Existing data types are untouched: indicators (INKAR/BBSR), " +
        "tax-rates and unemployment keep their own, partly more recent " +
        "values, and the datasets are deliberately not mixed.",
    },
  },
  {
    date: "2026-07-27",
    kind: "fixed",
    de: {
      title: "Baustellen und Verkehrsmeldungen: Notreserve statt 503",
      body:
        "Fällt eine Quelle für Baustellen, Verkehrsmeldungen oder Sperrungen " +
        "kurz aus, wird jetzt bis zu sechs Stunden lang der zuletzt bekannte " +
        "Stand ausgeliefert, statt mit 503 abzubrechen. Solche Antworten sind " +
        "im meta-Block an cache_status stale_on_error erkennbar. Bisher " +
        "hatten nur einzelne Quellen dieses Fenster, gleichartige Quellen " +
        "anderer Städte dagegen nur zwei Minuten, was am 26. Juli bei den " +
        "Hamburger Baustellen zu kurzzeitigen 503 führte. Betroffen sind " +
        "Hamburg, Dortmund, München, Rostock, Berlin, Köln, Sachsen und " +
        "Baden-Württemberg. Die Verkehrslage bekommt als Flusswert 30 " +
        "Minuten, weil ein alter Verkehrsfluss wenig aussagt. Die Frische " +
        "ändert sich nirgends, alle Quellen bleiben minutenfrisch. Bewusst " +
        "ausgenommen bleiben Abfahrtszeiten, Leihfahrzeuge und Wartezeiten: " +
        "dort wäre ein veralteter Wert irreführend, deshalb bleibt es dort " +
        "bei einer ehrlichen Fehlermeldung.",
    },
    en: {
      title: "Roadworks and traffic messages: fallback instead of 503",
      body:
        "If a source for roadworks, traffic messages or closures briefly " +
        "fails, the last known state is now served for up to six hours " +
        "instead of failing with 503. Such responses are recognisable by " +
        "cache_status stale_on_error in the meta block. Until now only some " +
        "sources had this window while equivalent sources in other cities had " +
        "just two minutes, which caused brief 503s for the Hamburg roadworks " +
        "on 26 July. Affected are Hamburg, Dortmund, Munich, Rostock, Berlin, " +
        "Cologne, Saxony and Baden-Württemberg. Traffic flow gets 30 minutes " +
        "as a flow value, because stale flow data says little. Freshness is " +
        "unchanged everywhere, all sources stay minute-fresh. Deliberately " +
        "excluded are departure times, shared vehicles and waiting times: a " +
        "stale value would be misleading there, so an honest error remains.",
    },
  },
  {
    date: "2026-07-26",
    kind: "changed",
    de: {
      title: "Bessere Wegweiser: 404-Hinweis und Beispielwerte",
      body:
        "Wer den /cities-Präfix vergisst und etwa /api/v1/recklinghausen " +
        "aufruft, bekommt im 404-Hinweis jetzt den korrekten Pfad genannt, " +
        "solange das Segment wirklich eine bekannte Stadt ist. Vorher schlug " +
        "die Ähnlichkeitssuche stattdessen eine Datenart mit ähnlichem Namen " +
        "vor und führte damit in die Irre. Exonyme und Kurzformen lösen dabei " +
        "auf den kanonischen Slug auf, munich verweist also auf " +
        "/api/v1/cities/muenchen. Unabhängig davon trägt jetzt jeder " +
        "Pflichtparameter der API einen funktionierenden Beispielwert. Die " +
        "Codebeispiele auf den Endpunktseiten setzten dort bisher das Wort " +
        "example ein, was kopiert und abgeschickt einen Fehler ergab, etwa " +
        "bei stop_id der Live-Abfahrten oder type der POIs. Die " +
        "Parametertabelle zeigt den Beispielwert zusätzlich in einer eigenen " +
        "Spalte. Bei den flüchtigen GTFS-RT-Kennungen trip_id und route_id " +
        "steht dabei, woher frische IDs kommen und dass eine abgelaufene ID " +
        "kein Fehler ist, sondern no_data.",
    },
    en: {
      title: "Better signposts: 404 hint and example values",
      body:
        "Leaving out the /cities prefix, for example /api/v1/recklinghausen, " +
        "now yields a 404 hint naming the correct path, as long as the " +
        "segment really is a known city. Previously the similarity search " +
        "suggested a data type with a similar name instead and pointed the " +
        "caller the wrong way. Exonyms and short forms resolve to the " +
        "canonical slug, so munich points at /api/v1/cities/muenchen. " +
        "Separately, every required API parameter now carries a working " +
        "example value. The code samples on the endpoint pages used to insert " +
        "the word example there, which produced an error when copied and " +
        "sent, for instance for stop_id of the live departures or type of the " +
        "POIs. The parameter table now shows the example value in a column of " +
        "its own. For the volatile GTFS-RT identifiers trip_id and route_id it " +
        "also says where fresh ids come from and that an expired id is not an " +
        "error but no_data.",
    },
  },
  {
    date: "2026-07-26",
    kind: "changed",
    de: {
      title: "MCP: transit_departures weist Trip-Halt-IDs freundlich ab",
      body:
        "Wer dem MCP-Werkzeug transit_departures statt einer Haltestellen-ID " +
        "eine trip_stop_id aus einer Bahnhofstafel übergibt, bekommt jetzt " +
        "eine Antwort mit source_status no_data und einem Hinweis, woher " +
        "gültige Haltestellen-IDs kommen, statt eines 400 vom Live-Endpunkt. " +
        "Das Werkzeug erkennt das Muster der Trip-Halt-ID selbst und stellt " +
        "gar keine Anfrage mehr. Gültige DELFI-IDs im Format de:AGS:id und " +
        "rein numerische gtfs.de-IDs sind davon nicht betroffen. Am " +
        "Live-Endpunkt selbst ändert sich nichts: dort bleibt eine ungültige " +
        "stop_id ein 400.",
    },
    en: {
      title: "MCP: transit_departures rejects trip stop ids gracefully",
      body:
        "Passing a trip_stop_id from a station board to the MCP tool " +
        "transit_departures instead of a station id now returns a response " +
        "with source_status no_data and a note on where valid stop ids come " +
        "from, rather than a 400 from the live endpoint. The tool recognises " +
        "the trip stop id pattern itself and no longer issues a request at " +
        "all. Valid DELFI ids in the form de:AGS:id and purely numeric " +
        "gtfs.de ids are unaffected. The live endpoint itself is unchanged: " +
        "an invalid stop_id still yields a 400 there.",
    },
  },
  {
    date: "2026-07-25",
    kind: "added",
    endpoint: "getCityStationDepartures",
    de: {
      title: "Abfahrtstafel: stop_id heißt jetzt trip_stop_id",
      body:
        "In den Abfahrts- und Ankunftstafeln der Bahnhöfe hieß das Feld bisher " +
        "stop_id, obwohl es einen einzelnen Halt einer konkreten Zugfahrt " +
        "bezeichnet und keine Haltestelle. Der Name kollidierte mit der " +
        "Haltestellen-ID der Live-Abfahrten unter /live/{slug}/transit/" +
        "departures, die eine DELFI-ID im Format de:AGS:id erwartet. Wer den " +
        "Wert von einem Endpunkt zum anderen weiterreichte, bekam verlässlich " +
        "einen 400. Das Feld heißt deshalb jetzt trip_stop_id; stop_id trägt " +
        "denselben Wert weiter und ist abgekündigt. Die Fehlermeldung des " +
        "Live-Endpunkts benennt die Verwechslung jetzt ausdrücklich und sagt, " +
        "wo gültige Haltestellen-IDs herkommen.",
    },
    en: {
      title: "Departure board: stop_id is now trip_stop_id",
      body:
        "In the station departure and arrival boards this field used to be " +
        "called stop_id, although it identifies a single stop of one specific " +
        "train run, not a station. The name collided with the stop id of the " +
        "live departures under /live/{slug}/transit/departures, which expects a " +
        "DELFI id in the form de:AGS:id. Passing the value from one endpoint to " +
        "the other reliably produced a 400. The field is therefore now called " +
        "trip_stop_id; stop_id keeps carrying the same value and is deprecated. " +
        "The live endpoint's error message now names the mix-up explicitly and " +
        "points to where valid stop ids come from.",
    },
  },
  {
    date: "2026-07-25",
    kind: "added",
    de: {
      title: "Einheitliche Feldnamen über alle Datenarten",
      body:
        "Gleiche Konzepte heißen jetzt überall gleich, in snake_case und " +
        "englisch: post_code, street, house_number, place, name, start, end, " +
        "distance_km, power_kw, lat und lon. Betroffen sind unter anderem " +
        "Ladesäulen (bisher plz und ort), Energie-Anlagen (plz, leistung_kw, " +
        "einheit_typ), Bahnhöfe (zip), Krankenhäuser (zip, city), " +
        "Köln-Veranstaltungen (strasse, hausnummer, plz) und innerstädtische " +
        "Baustellen (bezeichnung, beginn, ende, art). Die Verkehrsmeldungen " +
        "der Autobahn-API tragen zusätzlich is_blocked als echtes Boolean, " +
        "start_timestamp, delay_minutes, average_speed_kmh, " +
        "abnormal_traffic_type, name, description_text sowie bbox mit lat und " +
        "lon aus dem bisherigen Komma-String extent. Innerstädtische " +
        "Baustellen in Köln bekommen mit event_type_label den Klartext zum " +
        "bisherigen Zahlencode, direkt aus der Werteliste des Dienstes. " +
        "Der Bahnhofs-Katalog nennt die DB-Bahnhofskategorie jetzt " +
        "station_category, weil category in anderen Datenarten ein Textlabel " +
        "trägt und nicht eine Zahl. " +
        "Alle Änderungen sind additiv, die bisherigen Felder bleiben vorerst " +
        "mit identischem Wert erhalten.",
    },
    en: {
      title: "Consistent field names across all data types",
      body:
        "The same concepts now use the same name everywhere, in snake_case " +
        "and English: post_code, street, house_number, place, name, start, " +
        "end, distance_km, power_kw, lat and lon. This affects charging " +
        "stations (previously plz and ort), energy installations (plz, " +
        "leistung_kw, einheit_typ), railway stations (zip), hospitals (zip, " +
        "city), Cologne events (strasse, hausnummer, plz) and inner-city " +
        "roadworks (bezeichnung, beginn, ende, art). Traffic messages from the " +
        "Autobahn API additionally carry is_blocked as a real boolean, " +
        "start_timestamp, delay_minutes, average_speed_kmh, " +
        "abnormal_traffic_type, name, description_text plus bbox with lat and " +
        "lon derived from the former comma string extent. Cologne roadworks " +
        "gain event_type_label, the plain-text meaning of the former numeric " +
        "code, taken straight from the service's own code list. The station " +
        "catalog now calls the DB station category station_category, because " +
        "category carries a text label in other data types, not a number. " +
        "All changes " +
        "are additive; the previous fields remain with identical values for now.",
    },
  },
  {
    date: "2026-07-25",
    kind: "deprecated",
    de: {
      title: "Abkündigung: alte Feldnamen und camelCase-Rohfelder",
      body:
        "Die bisherigen Namen plz, zip, strasse, hausnummer, ort, city, " +
        "bezeichnung, beginn, ende, art, dist_km, leistung_kw, einheit_typ und " +
        "das stop_id der Bahnhofs-Tafeln (jetzt trip_stop_id), das category " +
        "im Bahnhofs-Katalog (jetzt station_category) " +
        "sowie die camelCase-Rohfelder der Autobahn-Verkehrsmeldungen " +
        "(isBlocked, startTimestamp, delayTimeValue, averageSpeed, " +
        "abnormalTrafficType, extent) sind abgekündigt. Sie tragen weiter " +
        "denselben Wert wie ihre kanonischen Entsprechungen und werden " +
        "frühestens 30 Tage nach diesem Eintrag entfernt. Wer sie nutzt, " +
        "stellt bis dahin auf die neuen Namen um.",
    },
    en: {
      title: "Deprecated: legacy field names and camelCase raw fields",
      body:
        "The former names plz, zip, strasse, hausnummer, ort, city, " +
        "bezeichnung, beginn, ende, art, dist_km, leistung_kw, einheit_typ and " +
        "the stop_id of the station boards (now trip_stop_id), the category " +
        "in the station catalog (now station_category), " +
        "as well as the camelCase raw fields of the Autobahn traffic messages " +
        "(isBlocked, startTimestamp, delayTimeValue, averageSpeed, " +
        "abnormalTrafficType, extent), are deprecated. They keep carrying the " +
        "same value as their canonical counterparts and will be removed no " +
        "earlier than 30 days after this entry. If you rely on them, switch to " +
        "the new names before then.",
    },
  },
  {
    date: "2026-07-25",
    kind: "fixed",
    endpoint: "getStationDepartures",
    de: {
      title: "Abfahrtszeiten tragen jetzt eine Zeitzone",
      body:
        "planned_time in den Abfahrts- und Ankunftstafeln kam bisher ohne " +
        "Zeitzone (2026-07-25T10:01:00) und war damit mehrdeutig. Der Wert ist " +
        "Bahnhofszeit und trägt jetzt die passende Zone " +
        "(2026-07-25T10:01:00+02:00). Ebenfalls behoben: leere Adressangaben " +
        "in den Köln-Veranstaltungen kamen als Leerstring statt als null, und " +
        "Postleitzahlen mit führender Null konnten ihre Null verlieren.",
    },
    en: {
      title: "Departure times now carry a time zone",
      body:
        "planned_time in the departure and arrival boards used to come without " +
        "a time zone (2026-07-25T10:01:00), which made it ambiguous. The value " +
        "is station local time and now carries the matching offset " +
        "(2026-07-25T10:01:00+02:00). Also fixed: empty address fields in the " +
        "Cologne events came back as an empty string instead of null, and " +
        "postal codes with a leading zero could lose that zero.",
    },
  },
  {
    date: "2026-07-25",
    kind: "added",
    endpoint: "getCityFuelPrices",
    de: {
      title: "Spritpreise: Adresse je Tankstelle",
      body:
        "Die Einzel-Tankstellen im Spritpreis-Payload tragen jetzt zusätzlich " +
        "street, house_number, post_code und place, also die an die MTS-K " +
        "gemeldete Adresse. Damit ist eine Tankstelle auch ohne Karte " +
        "benennbar. post_code ist immer ein fünfstelliger String, führende " +
        "Nullen bleiben erhalten (01067). Meldet die Quelle keine eigene " +
        "Hausnummer, steht sie oft im Straßennamen (\"Rödingsmarkt 14\"); sie " +
        "wird dann abgetrennt, sodass street und house_number getrennt " +
        "ankommen. Tankstellen ohne jede Hausnummer behalten house_number " +
        "null. Rein additiv, bestehende Felder bleiben unverändert.",
    },
    en: {
      title: "Fuel prices: address per station",
      body:
        "Individual stations in the fuel price payload now also carry street, " +
        "house_number, post_code and place, the address reported to the German " +
        "fuel price transparency unit (MTS-K). This makes a station " +
        "identifiable without a map. post_code is always a five-character " +
        "string, so leading zeros are preserved (01067). When the source " +
        "reports no separate house number, it is often part of the street name " +
        "(\"Rödingsmarkt 14\") and is split off, so street and house_number " +
        "arrive separately. Stations without any house number keep " +
        "house_number null. Purely additive, existing fields are unchanged.",
    },
  },
  {
    date: "2026-07-25",
    kind: "added",
    endpoint: "getCityFuelPrices",
    de: {
      title: "Spritpreise: Koordinaten je Tankstelle (Kartendarstellung)",
      body:
        "Die Einzel-Tankstellen im Spritpreis-Payload tragen jetzt zusätzlich " +
        "lat und lon, also die Koordinate der Tankstelle selbst. Damit lassen " +
        "sich die Tankstellen direkt auf einer Karte darstellen, ohne " +
        "Zusatz-Lookup. Rein additiv, bestehende Felder bleiben unverändert; " +
        "liefert die Quelle keine Koordinate, sind lat und lon null.",
    },
    en: {
      title: "Fuel prices: coordinates per station (map display)",
      body:
        "Individual stations in the fuel price payload now also carry lat and " +
        "lon, the coordinate of the station itself. This makes the stations " +
        "directly mappable without an extra lookup. Purely additive, existing " +
        "fields are unchanged; when the source has no coordinate, lat and lon " +
        "are null.",
    },
  },
  {
    date: "2026-07-23",
    kind: "changed",
    endpoint: "getCityParking",
    de: {
      title: "Köln: Parkdaten jetzt direkt von der Stadt Köln (Mobilithek)",
      body:
        "Köln kam bisher über den ParkenDD-Aggregator, dessen Köln-Feed seit " +
        "2021 eingefroren ist und daher keine Daten mehr lieferte. Die " +
        "Parkdaten kommen jetzt direkt von der Stadt Köln über die Mobilithek " +
        "(DATEX II, Belegung und Stammdaten gejoint, DL-DE/Zero 2.0, Tier A): " +
        "41 Parkhäuser mit Live-Belegung, Kapazität, Name und Koordinaten.",
    },
    en: {
      title: "Cologne: parking data now directly from the City of Cologne (Mobilithek)",
      body:
        "Cologne was previously served via the ParkenDD aggregator, whose " +
        "Cologne feed has been frozen since 2021 and no longer delivered any " +
        "data. Parking data now comes directly from the City of Cologne via " +
        "Mobilithek (DATEX II, occupancy joined with facility master data, " +
        "DL-DE/Zero 2.0, Tier A): 41 parking facilities with live occupancy, " +
        "capacity, name and coordinates.",
    },
  },
  {
    date: "2026-07-20",
    kind: "added",
    endpoint: "getCityParking",
    de: {
      title: "Parken in 14 weiteren Städten (DB BahnPark, bundesweit)",
      body:
        "Der /parking-Endpunkt deckt jetzt 14 zusätzliche Städte ab: Berlin, " +
        "Bochum, Bonn, Bremen, Düsseldorf, Duisburg, Erfurt, Essen, Hannover, " +
        "Mainz, Saarbrücken, Schwerin, Stuttgart und Wiesbaden. Quelle sind die " +
        "bahnhofsnahen Parkeinrichtungen der DB BahnPark (DB API Marketplace, " +
        "DL-DE/BY 2.0, Tier A). Es handelt sich um einen statischen Katalog " +
        "(Standort, Name, Gesamtkapazität, lot_type=\"station\"): eine numerische " +
        "Live-Belegung (free) liefert die Quelle nicht, das Feld bleibt daher null. " +
        "Städte mit eigener Live-Parkquelle (z.B. Köln, Frankfurt, Hamburg) sind " +
        "unverändert.",
    },
    en: {
      title: "Parking in 14 more cities (DB BahnPark, nationwide)",
      body:
        "The /parking endpoint now covers 14 additional cities: Berlin, Bochum, " +
        "Bonn, Bremen, Düsseldorf, Duisburg, Erfurt, Essen, Hannover, Mainz, " +
        "Saarbrücken, Schwerin, Stuttgart and Wiesbaden. The source is DB " +
        "BahnPark's station-adjacent parking facilities (DB API Marketplace, " +
        "DL-DE/BY 2.0, Tier A). This is a static catalogue (location, name, total " +
        "capacity, lot_type=\"station\"): the source provides no numeric live " +
        "occupancy (free), so that field stays null. Cities with their own live " +
        "parking source (e.g. Cologne, Frankfurt, Hamburg) are unchanged.",
    },
  },
  {
    date: "2026-07-19",
    kind: "changed",
    endpoint: "getCityPois",
    de: {
      title: "OSM-POIs jetzt aus wöchentlichem Precompute (stabiler)",
      body:
        "Die POI- und OSM-Infrastruktur-Datenarten (pois, playgrounds, " +
        "drinking-water, public-toilets, markets, parcel-lockers, post-offices, " +
        "post-boxes, public-wifi, recycling-centres, government-offices, " +
        "education) werden ab sofort aus einem periodischen Precompute des OSM-" +
        "Deutschland-Extrakts (wöchentlich) bedient statt live abgefragt. Envelope, " +
        "Felder und Lizenz (ODbL, Tier B) bleiben unverändert; total_available " +
        "nennt weiterhin den echten Gesamtbestand. Vorteil: keine Abhängigkeit von " +
        "einer öffentlichen Live-Instanz mehr, dadurch deutlich stabiler. Ist der " +
        "Bestand einer Stadt noch nicht berechnet, antwortet die Route mit 200 " +
        "source_status=\"no_data\" statt eines Fehlers.",
    },
    en: {
      title: "OSM POIs now from a weekly precompute (more stable)",
      body:
        "The POI and OSM infrastructure data types (pois, playgrounds, " +
        "drinking-water, public-toilets, markets, parcel-lockers, post-offices, " +
        "post-boxes, public-wifi, recycling-centres, government-offices, " +
        "education) are now served from a periodic precompute of the OSM Germany " +
        "extract (weekly) instead of being queried live. Envelope, fields and " +
        "license (ODbL, Tier B) are unchanged; total_available still reports the " +
        "real total. Benefit: no more dependency on a public live instance, hence " +
        "noticeably more stable. If a city's data has not been computed yet, the " +
        "route responds with 200 source_status=\"no_data\" instead of an error.",
    },
  },
  {
    date: "2026-07-17",
    kind: "added",
    endpoint: "getCityRoadEvents",
    de: {
      title: "Innerstädtische Baustellen für Rostock",
      body:
        "Die Datenart Baustellen/Verkehrsereignisse deckt jetzt auch Rostock " +
        "ab (OpenData.HRO, CC0). Je Baustelle werden Maßnahme, Sparte, Straße, " +
        "Abschnitt, Zeitraum und Verkehrsbeeinträchtigung geliefert.",
    },
    en: {
      title: "Inner-city roadworks for Rostock",
      body:
        "The roadworks / traffic events data type now also covers Rostock " +
        "(OpenData.HRO, CC0). Each roadwork comes with measure, utility, " +
        "street, section, period and traffic impact.",
    },
  },
  {
    date: "2026-07-17",
    kind: "added",
    endpoint: "get_city_resource",
    de: {
      title: "Ratsdokumente jetzt auch für Magdeburg und Osnabrück",
      body:
        "Die Datenart council-papers deckt neben Köln, Leipzig, Münster, " +
        "Dresden und Düsseldorf jetzt auch Magdeburg (DL-DE/Zero-2.0) und " +
        "Osnabrück (CC-BY-4.0) ab, beide über die standardisierte " +
        "OParl-Schnittstelle. Abrufbar unter " +
        "/api/v1/cities/{stadt}/council-papers sowie per MCP über " +
        "get_city_resource.",
    },
    en: {
      title: "Council papers now also for Magdeburg and Osnabrück",
      body:
        "The council-papers data type now covers Magdeburg (DL-DE/Zero-2.0) " +
        "and Osnabrück (CC-BY-4.0) in addition to Cologne, Leipzig, Münster, " +
        "Dresden and Düsseldorf, both via the standardized OParl interface. " +
        "Available at /api/v1/cities/{city}/council-papers and via MCP through " +
        "get_city_resource.",
    },
  },
  {
    date: "2026-07-17",
    kind: "added",
    endpoint: "getCitySharing",
    de: {
      title: "Bike-Sharing für Kiel (SprottenFlotte)",
      body:
        "Kiel ist beim Bike- und Scooter-Sharing ergänzt: die SprottenFlotte " +
        "läuft über Donkey Republic (GBFS 3.0) und liefert jetzt Stationen " +
        "und Verfügbarkeiten wie bei den übrigen Sharing-Städten. Die Daten " +
        "stehen unter CC0. Damit unterstützt der GBFS-Adapter erstmals auch " +
        "die GBFS-Version 3.0 (mehrsprachige Namensfelder, num_vehicles_available).",
    },
    en: {
      title: "Bike sharing for Kiel (SprottenFlotte)",
      body:
        "Kiel now has bike and scooter sharing: the SprottenFlotte runs on " +
        "Donkey Republic (GBFS 3.0) and reports stations and availability " +
        "just like the other sharing cities. The data is licensed CC0. This " +
        "also brings first-time support for GBFS version 3.0 (localized name " +
        "fields, num_vehicles_available).",
    },
  },
  {
    date: "2026-07-17",
    kind: "added",
    endpoint: "getCityTreeCadastre",
    de: {
      title: "Baumkataster für Hamburg und Kiel",
      body:
        "Das Baumkataster deckt jetzt neben Berlin auch Hamburg und Kiel ab. " +
        "Hamburg liefert das Straßenbaumkataster (Landesbetrieb Geoinformation " +
        "und Vermessung, DL-DE/BY-2.0), Kiel die Bäume auf städtischem Grund " +
        "(CC-BY-4.0). Je Baum werden Standort, Art und Kronendurchmesser " +
        "ausgeliefert.",
    },
    en: {
      title: "Tree cadastre for Hamburg and Kiel",
      body:
        "The tree cadastre now covers Hamburg and Kiel in addition to Berlin. " +
        "Hamburg provides its street tree register (Landesbetrieb Geoinformation " +
        "und Vermessung, DL-DE/BY-2.0), Kiel the trees on public ground " +
        "(CC-BY-4.0). Each tree comes with location, species and crown diameter.",
    },
  },
  {
    date: "2026-07-17",
    kind: "added",
    endpoint: "getCityFlood",
    de: {
      title: "Hochwasserwarnungen für Hannover, Kiel und Magdeburg",
      body:
        "Die Hochwasserwarnungen decken jetzt auch Hannover (Pegel " +
        "Herrenhausen, Leine), Kiel (Kiel-Holtenau, Ostsee, sturmflutrelevant) " +
        "und Magdeburg (Niegripp, Elbe) ab. Je Pegel werden Warnstufe, " +
        "Wasserstand und Zeitstempel geliefert. Quelle sind die " +
        "Länderübergreifenden Hochwasserportale (LHP).",
    },
    en: {
      title: "Flood warnings for Hanover, Kiel and Magdeburg",
      body:
        "Flood warnings now also cover Hanover (Herrenhausen gauge, Leine), " +
        "Kiel (Kiel-Holtenau, Baltic Sea, relevant for storm surges) and " +
        "Magdeburg (Niegripp, Elbe). Each gauge reports warning level, water " +
        "level and timestamp. Source is the joint German flood portals (LHP).",
    },
  },
  {
    date: "2026-07-16",
    kind: "fixed",
    endpoint: "getCityWeatherWarnings",
    de: {
      title: "Amtliche Wetterwarnungen wieder verfügbar (neue Bezugsquelle)",
      body:
        "Der DWD hat die alte WarnApp-Schnittstelle abgeschaltet, der " +
        "Endpunkt für amtliche Wetterwarnungen lieferte deshalb kurzzeitig " +
        "503. Die Warnungen kommen jetzt über die Bright-Sky-Alerts-API und " +
        "damit weiterhin dieselben amtlichen DWD-Daten. Die Warnstufen 1 " +
        "bis 4 werden aus der CAP-severity abgeleitet; Hitze- und " +
        "UV-Warnungen stehen wie bisher separat in special_warnings und " +
        "zählen nicht in max_level. Beachte: start und end der " +
        "Einzelwarnungen sind jetzt ISO-8601-Zeitstempel statt " +
        "Epoch-Millisekunden.",
    },
    en: {
      title: "Official weather warnings available again (new upstream)",
      body:
        "DWD shut down its old WarnApp interface, so the endpoint for " +
        "official weather warnings briefly returned 503. Warnings are now " +
        "fetched via the Bright Sky alerts API and thus remain the same " +
        "official DWD data. Warning levels 1 to 4 are derived from the CAP " +
        "severity; heat and UV warnings are still listed separately in " +
        "special_warnings and do not count towards max_level. Note: start " +
        "and end of individual warnings are now ISO 8601 timestamps " +
        "instead of epoch milliseconds.",
    },
  },
  {
    date: "2026-07-16",
    kind: "fixed",
    endpoint: "getLiveTransitDepartures",
    de: {
      title: "Live-ÖPNV-Abfahrten: Delay-only-Updates und Steig-IDs funktionieren jetzt",
      body:
        "Der Endpunkt für Live-Abfahrten je Halt lieferte fast überall no_data: " +
        "der bundesweite GTFS-RT-Feed trägt meist nur Verspätungen ohne " +
        "absolute Abfahrtszeit, und genau solche Einträge wurden verworfen. " +
        "Jetzt werden sie ehrlich ausgeliefert (delay_s/delay_min gesetzt, " +
        "departure_time und minutes_until = null) und folgen nach den " +
        "zeitbehafteten Abfahrten, die es z.B. in Berlin über den VBB-Feed " +
        "gibt. Außerdem darf stop_id jetzt Parent- oder Steig-Ebene sein " +
        "(de:AGS:nr oder de:AGS:nr:bereich:steig), beide werden aufgelöst.",
    },
    en: {
      title: "Live transit departures: delay-only updates and platform IDs now work",
      body:
        "The per-stop live departures endpoint returned no_data almost " +
        "everywhere: the nationwide GTFS-RT feed mostly carries delays " +
        "without absolute departure times, and exactly those entries were " +
        "dropped. They are now served honestly (delay_s/delay_min set, " +
        "departure_time and minutes_until = null) after the timed departures " +
        "available e.g. in Berlin via the VBB feed. stop_id may now also be " +
        "parent or platform level (de:AGS:nr or de:AGS:nr:area:platform); " +
        "both resolve.",
    },
  },
  {
    date: "2026-07-16",
    kind: "added",
    endpoint: "get_city_resource",
    de: {
      title: "Ratsdokumente: kompletter Datenbestand für 5 Städte (112.000+ Dokumente)",
      body:
        "Die neue Datenart council-papers liefert Ratsinformationen (Vorlagen, " +
        "Anträge, Beschlüsse) über die standardisierte OParl-Schnittstelle für " +
        "Köln, Leipzig, Münster, Dresden und Düsseldorf. Der historische " +
        "Rückbezug ist jetzt komplett: über 112.000 Dokumente ab 2020, davon " +
        "allein 48.000+ aus Leipzig. Neue Dokumente werden laufend ergänzt. " +
        "Abrufbar unter /api/v1/cities/{stadt}/council-papers sowie per MCP " +
        "über get_city_resource.",
    },
    en: {
      title: "Council papers: complete data set for 5 cities (112,000+ documents)",
      body:
        "The new council-papers data type serves municipal council documents " +
        "(motions, resolutions, drafts) via the standardized OParl interface " +
        "for Cologne, Leipzig, Münster, Dresden and Düsseldorf. The historical " +
        "backfill is now complete: more than 112,000 documents since 2020, " +
        "including 48,000+ from Leipzig alone. New documents are added " +
        "continuously. Available at /api/v1/cities/{city}/council-papers and " +
        "via MCP through get_city_resource.",
    },
  },
  {
    date: "2026-07-11",
    kind: "changed",
    de: {
      title: "Doku: neue Navigation mit Aufgaben-Gruppen und mobilem Drawer",
      body:
        "Das Doku-Menü ist neu gegliedert in Loslegen, Grundlagen, API-Referenz, " +
        "KI & Integrationen und Projekt. Die API-Referenz zeigt jetzt sprechende " +
        "Namen statt operationIds (die operationId erscheint beim Überfahren), " +
        "Live-Endpunkte stehen in ihrer Themenkategorie mit LIVE-Badge statt in " +
        "einer eigenen Sektion. Das Badge markiert Echtzeitdaten unabhängig vom " +
        "Pfad, also auch Spritpreise, Parkhaus-Belegung, Bahn-Abfahrten oder " +
        "Ladesäulen-Status. Auf Mobilgeräten öffnet ein Menü-Button in der " +
        "Kopfleiste einen Drawer, in dem nur die aktive Gruppe aufgeklappt ist. " +
        "Alle Seiten und URLs bleiben unverändert.",
    },
    en: {
      title: "Docs: new navigation with task-based groups and a mobile drawer",
      body:
        "The docs menu is regrouped into Get started, Basics, API reference, " +
        "AI & integrations and Project. The API reference now shows readable " +
        "names instead of operationIds (the operationId appears on hover), and " +
        "live endpoints sit inside their topic category with a LIVE badge " +
        "instead of a separate section. The badge marks real-time data " +
        "regardless of path, including fuel prices, parking occupancy, train " +
        "departures and charging status. On mobile, a menu button in the top " +
        "bar opens a drawer with only the active group expanded. All pages and " +
        "URLs are unchanged.",
    },
  },
  {
    date: "2026-07-07",
    kind: "changed",
    endpoint: "get_city_parking",
    de: {
      title: "Parken: Frische-Schutz gegen eingefrorene Upstreams",
      body:
        "Für die ParkenDD-Städte gilt jetzt ein Frische-Wächter: Liefert ein " +
        "Upstream seit mehr als 48 Stunden keine neuen Belegungszeiten, gibt der " +
        "Endpunkt no_data zurück statt veralteter Werte. Das verhindert, dass " +
        "monatealte Parkstände wie aktuelle aussehen. Ein fehlender oder " +
        "unlesbarer Zeitstempel zählt defensiv nicht als eingefroren.",
    },
    en: {
      title: "Parking: staleness guard for frozen upstreams",
      body:
        "The ParkenDD cities now have a freshness guard: if an upstream has not " +
        "delivered new occupancy timestamps for more than 48 hours, the endpoint " +
        "returns no_data instead of stale values. This prevents months-old parking " +
        "counts from looking current. A missing or unreadable timestamp defensively " +
        "does not count as frozen.",
    },
  },
  {
    date: "2026-07-04",
    kind: "added",
    endpoint: "get_city_bike_counts",
    de: {
      title: "Radzählstellen: Düsseldorf ergänzt (8 Städte)",
      body:
        "bike-counts liefert jetzt auch die Radzählstellen der Landeshauptstadt " +
        "Düsseldorf. Damit deckt die Datenart acht Städte ab. Lizenz DL-DE/BY 2.0.",
    },
    en: {
      title: "Bike counters: Düsseldorf added (8 cities)",
      body:
        "bike-counts now also serves the bicycle counting stations of Düsseldorf, " +
        "bringing the data type to eight cities. Licence DL-DE/BY 2.0.",
    },
  },
  {
    date: "2026-07-04",
    kind: "changed",
    endpoint: "compare_cities",
    de: {
      title: "Städtevergleich: sechs weitere Datenarten",
      body:
        "Der Vergleich mehrerer Städte in einem Aufruf umfasst jetzt zusätzlich " +
        "Kennzahlen (indicators), Demografie, Arbeitslosenquote, Tourismus, " +
        "Ladebelegung und Wetterwarnungen, ergänzend zu Wetter und Luftqualität.",
    },
    en: {
      title: "City comparison: six more data types",
      body:
        "Comparing multiple cities in one call now additionally covers indicators, " +
        "demographics, unemployment, tourism, charging status and weather warnings, " +
        "on top of weather and air quality.",
    },
  },
  {
    date: "2026-07-04",
    kind: "added",
    endpoint: "get_city_road_events",
    de: {
      title: "Baustellen und Sperrungen: Dresden und Leipzig",
      body:
        "road-events liefert jetzt Baustellen und Sperrungen für Dresden und " +
        "Leipzig aus dem sächsischen SPERRINFOSYS. Lizenz DL-DE/BY 2.0.",
    },
    en: {
      title: "Roadworks and closures: Dresden and Leipzig",
      body:
        "road-events now serves roadworks and closures for Dresden and Leipzig " +
        "from Saxony's SPERRINFOSYS. Licence DL-DE/BY 2.0.",
    },
  },
  {
    date: "2026-07-04",
    kind: "added",
    de: {
      title: "InfraNode als ChatGPT-GPT und GPT-Action",
      body:
        "InfraNode ist jetzt als Custom-GPT im GPT Store verfügbar und lässt sich " +
        "über eine kuratierte Actions-OpenAPI als GPT-Action einbinden, keylos und " +
        "per URL-Import. Details unter /chatgpt/.",
    },
    en: {
      title: "InfraNode as a ChatGPT GPT and GPT action",
      body:
        "InfraNode is now available as a Custom GPT in the GPT Store and can be " +
        "wired in as a GPT action via a curated actions OpenAPI, key-free and via " +
        "URL import. See /en/chatgpt/.",
    },
  },
  {
    date: "2026-07-03",
    kind: "added",
    endpoint: "get_city_charging_status",
    de: {
      title: "Live-Ladebelegung für alle 84 Städte",
      body:
        "Neue Datenart charging-status: die Echtzeit-Belegung öffentlicher " +
        "Ladepunkte je Stadt (frei, belegt, lädt, außer Betrieb), aufbereitet aus " +
        "dem eRound-Feed (CC0). Ergänzt die statischen Ladesäulen-Standorte.",
    },
    en: {
      title: "Live charging occupancy for all 84 cities",
      body:
        "New data type charging-status: the real-time occupancy of public charging " +
        "points per city (available, occupied, charging, out of service), derived " +
        "from the eRound feed (CC0). Complements the static charging point locations.",
    },
  },
  {
    date: "2026-07-02",
    kind: "changed",
    de: {
      title: "MCP-Server auf 12 schlanke Tools konsolidiert",
      body:
        "Der gehostete MCP-Server bündelt die 67 Datenarten jetzt in 12 Tools; " +
        "die Long-Tail-Datenarten laufen über get_city_resource(slug, resource). " +
        "Bestehende Aufrufe bleiben abgedeckt, die Tool-Liste ist deutlich kürzer.",
    },
    en: {
      title: "MCP server consolidated to 12 lean tools",
      body:
        "The hosted MCP server now bundles the 67 data types into 12 tools; the " +
        "long-tail data types run through get_city_resource(slug, resource). " +
        "Existing calls stay covered and the tool list is much shorter.",
    },
  },
];
