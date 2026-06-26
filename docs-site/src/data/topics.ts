// Single Source fuer die per-Datentyp-Landingpages (SEO-Massnahme 1).
// Jede Datenachse (Wetter, Luftqualitaet, Strompreis, Bodenrichtwerte,
// OePNV-Echtzeit) bekommt eine keyword-optimierte Seite in DE und EN, gespeist
// aus diesem Array. Die dynamischen Routen src/pages/daten/[topic].astro und
// src/pages/en/data/[topic].astro generieren daraus die Seiten.
//
// coverageKey: Schluessel in src/data/coverage.json#partial fuer die Stadt-Zahl.
// "all" = alle Staedte (nationale/flaechendeckende Quelle). endpointId verlinkt
// in die API-Referenz (/api/{endpointId}/ bzw. /en/api/{endpointId}/).

export interface TopicFaq {
  q: string;
  a: string;
}

export interface TopicLang {
  slug: string;
  metaTitle: string;
  h1: string;
  lead: string;
  dataDesc: string;
  sourceName: string;
  sourceUrl: string;
  license: string;
  licenseUrl: string;
  vars: string[];
  keywords: string[];
  coverageNote: string;
  faq: TopicFaq[];
  datasetName: string;
  datasetDesc: string;
}

export interface Topic {
  id: string;
  endpointId: string;
  examplePath: string; // Pfad nach /api/v1 ... mit Beispiel-Slug
  coverageKey: string; // "all" oder Key aus coverage.json#partial
  de: TopicLang;
  en: TopicLang;
}

export const topics: Topic[] = [
  {
    id: "weather",
    endpointId: "getCityWeather",
    examplePath: "/api/v1/cities/berlin/weather",
    coverageKey: "all",
    de: {
      slug: "wetter-api",
      metaTitle: "Wetter-API Deutschland (DWD): kostenlos und keylos je Stadt",
      h1: "Wetter-API für deutsche Städte (DWD)",
      lead: "Aktuelle Wetterdaten für 84 deutsche Großstädte über eine kostenlose, keylose REST-API. Quelle ist der Deutsche Wetterdienst (DWD), ausgeliefert in einem einheitlichen JSON-Envelope mit Quelle, Lizenz und Zeitstempel je Antwort.",
      dataDesc:
        "Pro Stadt liefert der Endpunkt die nächstgelegene DWD-Messung: Lufttemperatur, Luftfeuchte, Windgeschwindigkeit und Wetterlage, dazu Beobachtungszeitpunkt und Stations-ID. Über einen separaten Endpunkt gibt es amtliche DWD-Wetterwarnungen.",
      sourceName: "Deutscher Wetterdienst (DWD)",
      sourceUrl: "https://www.dwd.de/",
      license: "DL-DE BY 2.0",
      licenseUrl: "https://www.govdata.de/dl-de/by-2-0",
      vars: ["Lufttemperatur (Grad Celsius)", "Relative Luftfeuchte", "Windgeschwindigkeit", "Wetterlage", "Beobachtungszeitpunkt", "Stations-ID"],
      keywords: ["Wetter API Deutschland", "DWD API", "keylose Wetter API", "Wetterdaten API kostenlos", "Wetter API JSON", "Wetterstation API"],
      coverageNote: "Wetterdaten sind für alle 84 abgedeckten Großstädte verfügbar (nächstgelegene DWD-Station).",
      faq: [
        { q: "Brauche ich einen API-Schlüssel für die Wetter-API?", a: "Nein. Die InfraNode-Wetter-API ist keylos und kostenlos. Ein einfacher GET-Request ohne Anmeldung genügt, das Rate-Limit liegt bei 300 Anfragen pro Minute und IP." },
        { q: "Woher kommen die Wetterdaten?", a: "Die Daten stammen vom Deutschen Wetterdienst (DWD) und werden unverändert unter der Lizenz DL-DE BY 2.0 durchgereicht. Jede API-Antwort enthält Quelle, Lizenz-URL und Beobachtungszeitpunkt." },
        { q: "Wie aktuell sind die Werte?", a: "Die API liefert die jeweils jüngste verfügbare DWD-Beobachtung. Der Zeitpunkt steht als observed_at in jeder Antwort, dazu ein Cache-Status im meta-Block." },
      ],
      datasetName: "InfraNode Wetterdaten deutscher Großstädte (DWD)",
      datasetDesc: "Aktuelle Wetterbeobachtungen (Temperatur, Luftfeuchte, Wind, Wetterlage) für 84 deutsche Großstädte aus DWD-Stationsdaten, kostenlos und keylos über eine REST-API als JSON.",
    },
    en: {
      slug: "weather-api",
      metaTitle: "Germany Weather API (DWD): free and keyless, per city",
      h1: "Weather API for German cities (DWD)",
      lead: "Current weather data for 84 major German cities through a free, keyless REST API. The source is the German Weather Service (DWD), delivered in one consistent JSON envelope with source, license and timestamp on every response.",
      dataDesc:
        "For each city the endpoint returns the nearest DWD observation: air temperature, humidity, wind speed and weather condition, plus the observation time and station id. A separate endpoint serves official DWD weather warnings.",
      sourceName: "German Weather Service (DWD)",
      sourceUrl: "https://www.dwd.de/",
      license: "DL-DE BY 2.0",
      licenseUrl: "https://www.govdata.de/dl-de/by-2-0",
      vars: ["Air temperature (degrees Celsius)", "Relative humidity", "Wind speed", "Weather condition", "Observation time", "Station id"],
      keywords: ["weather API Germany", "DWD API", "keyless weather API", "free weather data API", "weather API JSON", "German weather API"],
      coverageNote: "Weather data is available for all 84 covered cities (nearest DWD station).",
      faq: [
        { q: "Do I need an API key for the weather API?", a: "No. The InfraNode weather API is keyless and free. A simple GET request without sign-up is enough; the rate limit is 300 requests per minute per IP." },
        { q: "Where does the weather data come from?", a: "Data comes from the German Weather Service (DWD) and is passed through unchanged under the DL-DE BY 2.0 license. Every API response carries the source, license URL and observation time." },
        { q: "How current are the values?", a: "The API returns the most recent available DWD observation. The time is exposed as observed_at on every response, with a cache status in the meta block." },
      ],
      datasetName: "InfraNode weather data for German cities (DWD)",
      datasetDesc: "Current weather observations (temperature, humidity, wind, condition) for 84 major German cities from DWD station data, free and keyless via a JSON REST API.",
    },
  },
  {
    id: "air-quality",
    endpointId: "getCityAirUba",
    examplePath: "/api/v1/cities/berlin/air-uba",
    coverageKey: "all",
    de: {
      slug: "luftqualitaet-api",
      metaTitle: "Luftqualitäts-API Deutschland (Umweltbundesamt), keylos",
      h1: "Luftqualitäts-API für deutsche Städte (UBA)",
      lead: "Aktuelle Luftqualitätsdaten für deutsche Großstädte über eine kostenlose, keylose REST-API. Quelle ist das Umweltbundesamt (UBA) mit seinem amtlichen Messnetz, einheitlich als JSON mit Quelle und Lizenz je Antwort.",
      dataDesc:
        "Pro Stadt liefert der Endpunkt die Messwerte der nächstgelegenen UBA-Station: Feinstaub PM10 und PM2.5, Stickstoffdioxid NO2, Ozon O3 und Schwefeldioxid SO2, jeweils mit Messzeitpunkt und Stationsbezug.",
      sourceName: "Umweltbundesamt (UBA)",
      sourceUrl: "https://www.umweltbundesamt.de/",
      license: "DL-DE BY 2.0",
      licenseUrl: "https://www.govdata.de/dl-de/by-2-0",
      vars: ["Feinstaub PM10", "Feinstaub PM2.5", "Stickstoffdioxid (NO2)", "Ozon (O3)", "Schwefeldioxid (SO2)", "Messzeitpunkt", "Messstation"],
      keywords: ["Luftqualität API Deutschland", "Feinstaub API", "UBA API", "Luftqualitäts API kostenlos", "NO2 PM10 API", "Air Quality API Germany"],
      coverageNote: "Luftqualitätsdaten richten sich nach dem UBA-Messnetz; abgefragt wird die jeweils nächstgelegene Station.",
      faq: [
        { q: "Ist die Luftqualitäts-API kostenlos und ohne Schlüssel nutzbar?", a: "Ja. Die API ist keylos und kostenlos, ein GET-Request ohne Anmeldung genügt. Das Rate-Limit beträgt 300 Anfragen pro Minute und IP." },
        { q: "Welche Schadstoffe sind enthalten?", a: "Feinstaub PM10 und PM2.5, Stickstoffdioxid NO2, Ozon O3 und Schwefeldioxid SO2 aus dem Messnetz des Umweltbundesamts, mit Messzeitpunkt und Stationsbezug je Wert." },
        { q: "Welche Lizenz gilt für die Luftdaten?", a: "Die UBA-Daten werden unter DL-DE BY 2.0 durchgereicht. Die Lizenz-URL und der Attributionstext stehen in jeder API-Antwort im attribution-Block." },
      ],
      datasetName: "InfraNode Luftqualitätsdaten deutscher Großstädte (UBA)",
      datasetDesc: "Aktuelle Luftqualitätswerte (PM10, PM2.5, NO2, O3, SO2) für deutsche Großstädte aus dem Messnetz des Umweltbundesamts, kostenlos und keylos über eine REST-API als JSON.",
    },
    en: {
      slug: "air-quality-api",
      metaTitle: "Germany Air Quality API (UBA): free and keyless",
      h1: "Air quality API for German cities (UBA)",
      lead: "Current air quality data for major German cities through a free, keyless REST API. The source is the German Environment Agency (UBA) with its official monitoring network, delivered as consistent JSON with source and license on every response.",
      dataDesc:
        "For each city the endpoint returns readings from the nearest UBA station: particulate matter PM10 and PM2.5, nitrogen dioxide NO2, ozone O3 and sulphur dioxide SO2, each with measurement time and station reference.",
      sourceName: "German Environment Agency (UBA)",
      sourceUrl: "https://www.umweltbundesamt.de/en",
      license: "DL-DE BY 2.0",
      licenseUrl: "https://www.govdata.de/dl-de/by-2-0",
      vars: ["Particulate matter PM10", "Particulate matter PM2.5", "Nitrogen dioxide (NO2)", "Ozone (O3)", "Sulphur dioxide (SO2)", "Measurement time", "Monitoring station"],
      keywords: ["air quality API Germany", "particulate matter API", "UBA API", "free air quality API", "NO2 PM10 API", "German air quality data API"],
      coverageNote: "Air quality data follows the UBA monitoring network; the nearest station is queried per city.",
      faq: [
        { q: "Is the air quality API free and usable without a key?", a: "Yes. The API is keyless and free; a GET request without sign-up is enough. The rate limit is 300 requests per minute per IP." },
        { q: "Which pollutants are included?", a: "Particulate matter PM10 and PM2.5, nitrogen dioxide NO2, ozone O3 and sulphur dioxide SO2 from the German Environment Agency network, with measurement time and station reference per value." },
        { q: "Which license applies to the air data?", a: "UBA data is passed through under DL-DE BY 2.0. The license URL and attribution text are included in every API response in the attribution block." },
      ],
      datasetName: "InfraNode air quality data for German cities (UBA)",
      datasetDesc: "Current air quality values (PM10, PM2.5, NO2, O3, SO2) for major German cities from the German Environment Agency network, free and keyless via a JSON REST API.",
    },
  },
  {
    id: "electricity-price",
    endpointId: "getCityPowerPrice",
    examplePath: "/api/v1/cities/berlin/power-price",
    coverageKey: "all",
    de: {
      slug: "strompreis-api",
      metaTitle: "Strompreis-API Deutschland (SMARD): Day-Ahead, keylos",
      h1: "Strompreis-API für Deutschland (SMARD)",
      lead: "Der bundesweite Day-Ahead-Börsenstrompreis über eine kostenlose, keylose REST-API. Quelle ist SMARD der Bundesnetzagentur, einheitlich als JSON mit Quelle, Lizenz und Zeitstempel je Antwort.",
      dataDesc:
        "Der Endpunkt liefert den deutschlandweiten Day-Ahead-Börsenstrompreis (EUR pro MWh) als Tageswert. Da es ein bundesweiter Preis ist, ist der Wert für jede Stadt identisch, abrufbar bequem über den jeweiligen Stadt-Slug. Ein zweiter Endpunkt liefert die Netzlast (Stromverbrauch) der Regelzone je Stadt.",
      sourceName: "SMARD, Bundesnetzagentur",
      sourceUrl: "https://www.smard.de/",
      license: "DL-DE BY 2.0",
      licenseUrl: "https://www.govdata.de/dl-de/by-2-0",
      vars: ["Day-Ahead-Börsenstrompreis (EUR/MWh)", "Bezugszeitpunkt", "Netzlast der Regelzone (über power-load)"],
      keywords: ["Strompreis API", "SMARD API", "Börsenstrompreis API", "Day Ahead Strompreis API", "Strompreis API kostenlos", "Energiedaten API Deutschland"],
      coverageNote: "Der Day-Ahead-Preis ist bundesweit, also für alle 84 Städte über denselben Wert abrufbar. Die Netzlast (power-load) bezieht sich auf die jeweilige Regelzone.",
      faq: [
        { q: "Ist die Strompreis-API kostenlos und keylos?", a: "Ja. Kein Schlüssel, keine Anmeldung, kostenlos, ein GET-Request genügt. Das Rate-Limit beträgt 300 Anfragen pro Minute und IP." },
        { q: "Ist der Strompreis pro Stadt unterschiedlich?", a: "Nein. Der Day-Ahead-Börsenstrompreis gilt für ganz Deutschland einheitlich. Der Abruf über einen Stadt-Slug ist nur bequemer Zugang zu demselben bundesweiten Wert." },
        { q: "Eignet sich die API für Smart Home oder dynamische Tarife?", a: "Ja. Der Tageswert lässt sich keylos abrufen und etwa in Home Assistant oder ioBroker einbinden, um Verbraucher in günstige Stunden zu legen." },
      ],
      datasetName: "InfraNode Strompreisdaten Deutschland (SMARD)",
      datasetDesc: "Bundesweiter Day-Ahead-Börsenstrompreis und Netzlast aus SMARD-Daten der Bundesnetzagentur, kostenlos und keylos über eine REST-API als JSON.",
    },
    en: {
      slug: "electricity-price-api",
      metaTitle: "Germany Electricity Price API (SMARD): day-ahead, keyless",
      h1: "Electricity price API for Germany (SMARD)",
      lead: "The nationwide day-ahead spot electricity price through a free, keyless REST API. The source is SMARD by the Federal Network Agency, delivered as consistent JSON with source, license and timestamp on every response.",
      dataDesc:
        "The endpoint returns the Germany-wide day-ahead spot electricity price (EUR per MWh) as a daily value. Because it is a national price, the value is identical for every city, conveniently retrievable via each city slug. A second endpoint returns the grid load (electricity consumption) of the control zone per city.",
      sourceName: "SMARD, Federal Network Agency",
      sourceUrl: "https://www.smard.de/en",
      license: "DL-DE BY 2.0",
      licenseUrl: "https://www.govdata.de/dl-de/by-2-0",
      vars: ["Day-ahead spot electricity price (EUR/MWh)", "Reference time", "Grid load of the control zone (via power-load)"],
      keywords: ["electricity price API", "SMARD API", "spot electricity price API", "day ahead electricity price API", "free electricity price API", "Germany energy data API"],
      coverageNote: "The day-ahead price is nationwide, so the same value is retrievable for all 84 cities. Grid load (power-load) refers to the respective control zone.",
      faq: [
        { q: "Is the electricity price API free and keyless?", a: "Yes. No key, no sign-up, free, a single GET request is enough. The rate limit is 300 requests per minute per IP." },
        { q: "Does the electricity price differ per city?", a: "No. The day-ahead spot price is uniform across Germany. Retrieving it via a city slug is just convenient access to the same national value." },
        { q: "Is the API suitable for smart home or dynamic tariffs?", a: "Yes. The daily value can be fetched keyless and integrated into Home Assistant or ioBroker, for example to shift loads into cheaper hours." },
      ],
      datasetName: "InfraNode electricity price data Germany (SMARD)",
      datasetDesc: "Nationwide day-ahead spot electricity price and grid load from SMARD data of the Federal Network Agency, free and keyless via a JSON REST API.",
    },
  },
  {
    id: "land-values",
    endpointId: "getCityLandValues",
    examplePath: "/api/v1/cities/berlin/land-values",
    coverageKey: "land-values",
    de: {
      slug: "bodenrichtwerte-api",
      metaTitle: "Bodenrichtwerte-API Deutschland (BORIS), keylos und frei",
      h1: "Bodenrichtwerte-API für deutsche Städte (BORIS)",
      lead: "Amtliche Bodenrichtwerte je Stadt über eine kostenlose, keylose REST-API. Quelle sind die BORIS-Geodatendienste der Länder, aggregiert zu einer Bauland-Kennzahl je Stadt und einheitlich als JSON ausgeliefert.",
      dataDesc:
        "Pro abgedeckter Stadt liefert der Endpunkt eine Bauland-Kennzahl: Median, Minimum und Maximum der Bodenrichtwerte in EUR pro Quadratmeter, Anzahl der Zonen und den Stichtag. Gefiltert auf Bauland (Wohnen, Misch, Gewerbe), damit Wald- und Wasserzonen den Wert nicht verzerren.",
      sourceName: "BORIS (Bodenrichtwertinformationssysteme der Länder)",
      sourceUrl: "https://www.bodenrichtwerte-boris.de/",
      license: "DL-DE Zero 2.0 bzw. DL-DE BY 2.0 (je Land)",
      licenseUrl: "https://www.govdata.de/dl-de/zero-2-0",
      vars: ["Median-Bodenrichtwert (EUR/m²)", "Minimum-Bodenrichtwert", "Maximum-Bodenrichtwert", "Anzahl Bodenrichtwertzonen", "Stichtag"],
      keywords: ["Bodenrichtwerte API", "BORIS API", "Bodenrichtwert Deutschland API", "Grundstückspreise API", "Bauland API", "Immobiliendaten API"],
      coverageNote: "Bodenrichtwerte sind dort verfügbar, wo das jeweilige Land einen offenen BORIS-Dienst bereitstellt.",
      faq: [
        { q: "Ist die Bodenrichtwerte-API kostenlos und keylos?", a: "Ja. Kein Schlüssel, keine Anmeldung, kostenlos, ein GET-Request genügt. Das Rate-Limit beträgt 300 Anfragen pro Minute und IP." },
        { q: "Was bedeutet die Bauland-Kennzahl?", a: "Es ist der Median der Bodenrichtwerte einer Stadt, gefiltert auf Bauland (Wohnen, Misch, Gewerbe), plus Minimum, Maximum, Zonenzahl und Stichtag. So bleibt der Wert aussagekräftig und nicht durch Wald- oder Wasserflächen verzerrt." },
        { q: "Warum ist nicht jede Stadt abgedeckt?", a: "Bodenrichtwerte werden je Bundesland bereitgestellt. Wo ein Land keinen offenen BORIS-Dienst anbietet (etwa lizenzbeschränkt), antwortet die API ehrlich mit not_covered statt zu raten." },
      ],
      datasetName: "InfraNode Bodenrichtwerte deutscher Städte (BORIS)",
      datasetDesc: "Amtliche Bodenrichtwerte als Bauland-Kennzahl (Median, Minimum, Maximum, Zonen, Stichtag) je Stadt aus BORIS-Diensten der Länder, kostenlos und keylos über eine REST-API als JSON.",
    },
    en: {
      slug: "land-values-api",
      metaTitle: "Germany Land Values API (BORIS): keyless and free",
      h1: "Land values API for German cities (BORIS)",
      lead: "Official standard land values per city through a free, keyless REST API. The source is the BORIS geodata services of the federal states, aggregated to a building-land metric per city and delivered as consistent JSON.",
      dataDesc:
        "For each covered city the endpoint returns a building-land metric: median, minimum and maximum of standard land values in EUR per square meter, the number of zones and the reference date. Filtered to building land (residential, mixed, commercial) so forest and water zones do not distort the value.",
      sourceName: "BORIS (standard land value systems of the federal states)",
      sourceUrl: "https://www.bodenrichtwerte-boris.de/",
      license: "DL-DE Zero 2.0 or DL-DE BY 2.0 (per state)",
      licenseUrl: "https://www.govdata.de/dl-de/zero-2-0",
      vars: ["Median standard land value (EUR/m²)", "Minimum land value", "Maximum land value", "Number of land value zones", "Reference date"],
      keywords: ["land values API", "BORIS API", "standard land value Germany API", "property prices API", "building land API", "real estate data API Germany"],
      coverageNote: "Land values are available where the respective state provides an open BORIS service.",
      faq: [
        { q: "Is the land values API free and keyless?", a: "Yes. No key, no sign-up, free, a single GET request is enough. The rate limit is 300 requests per minute per IP." },
        { q: "What does the building-land metric mean?", a: "It is the median of a city's standard land values, filtered to building land (residential, mixed, commercial), plus minimum, maximum, zone count and reference date. This keeps the value meaningful and not distorted by forest or water areas." },
        { q: "Why is not every city covered?", a: "Standard land values are provided per federal state. Where a state offers no open BORIS service (for example license-restricted), the API answers honestly with not_covered instead of guessing." },
      ],
      datasetName: "InfraNode land values for German cities (BORIS)",
      datasetDesc: "Official standard land values as a building-land metric (median, minimum, maximum, zones, reference date) per city from state BORIS services, free and keyless via a JSON REST API.",
    },
  },
  {
    id: "solar",
    endpointId: "getCitySolar",
    examplePath: "/api/v1/cities/berlin/solar",
    coverageKey: "all",
    de: {
      slug: "solar-api",
      metaTitle: "Solar-API Deutschland (PVGIS): PV-Ertrag und Einstrahlung, keylos",
      h1: "Solar-API für deutsche Städte (PVGIS)",
      lead: "Solar-Potenzial je Stadt über eine kostenlose, keylose REST-API. Quelle ist PVGIS der Europäischen Kommission (JRC), aggregiert zu einer vergleichbaren Kennzahl je Stadt und einheitlich als JSON mit Quelle, Lizenz und Bezugszeitraum je Antwort.",
      dataDesc:
        "Pro Stadt liefert der Endpunkt ein klimatologisches Mehrjahresmittel am Stadtzentrum, normiert auf eine 1-kWp-Anlage bei optimalem Neigungswinkel: Jahres-PV-Ertrag in kWh pro kWp, Globalstrahlung in kWh pro Quadratmeter, optimaler Neigungswinkel und Azimut sowie zwölf Monatswerte. Es ist kein Tageswert, sondern ein langjähriger Mittelwert; der Bezugszeitraum steht als Jahresspanne in der Antwort.",
      sourceName: "PVGIS, Europäische Kommission (JRC)",
      sourceUrl: "https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis_en",
      license: "EU-Wiederverwendungs-Policy (faktisch CC BY 4.0)",
      licenseUrl: "https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis_en",
      vars: ["Jahres-PV-Ertrag (kWh/kWp)", "Globalstrahlung (kWh/m²)", "Optimaler Neigungswinkel (Grad)", "Optimales Azimut (Grad, 0 = Süd)", "12 Monatswerte (Ertrag + Einstrahlung)", "Bezugszeitraum (Jahresspanne)"],
      keywords: ["Solar API Deutschland", "PVGIS API", "Solarpotenzial API", "Photovoltaik Ertrag API", "Globalstrahlung API", "PV Ertrag API kostenlos"],
      coverageNote: "Solar-Daten sind für alle 84 abgedeckten Städte verfügbar: PVGIS rechnet jede Koordinate in Europa, die Werte beziehen sich auf das Stadtzentrum.",
      faq: [
        { q: "Ist die Solar-API kostenlos und keylos?", a: "Ja. Kein Schlüssel, keine Anmeldung, kostenlos, ein GET-Request genügt. Das Rate-Limit beträgt 300 Anfragen pro Minute und IP." },
        { q: "Was bedeutet der Wert kWh pro kWp?", a: "Es ist der zu erwartende Jahresertrag einer Photovoltaikanlage je installiertem Kilowatt-Peak bei optimalem Neigungswinkel. So lassen sich Standorte direkt vergleichen und auf die geplante Anlagengröße hochrechnen." },
        { q: "Sind das aktuelle Messwerte?", a: "Nein. PVGIS liefert ein klimatologisches Mehrjahresmittel, also einen langjährigen Durchschnitt statt eines Tageswerts. Deshalb ist observed_at null; der Bezugszeitraum steht als Jahresspanne (period_start/period_end) in der Antwort." },
      ],
      datasetName: "InfraNode Solardaten deutscher Städte (PVGIS)",
      datasetDesc: "Solar-Einstrahlung und normierter PV-Ertrag (kWh/kWp, kWh/m², optimaler Winkel, Monatswerte) für 84 deutsche Städte aus PVGIS-Daten der Europäischen Kommission, kostenlos und keylos über eine REST-API als JSON.",
    },
    en: {
      slug: "solar-api",
      metaTitle: "Germany Solar API (PVGIS): PV yield and irradiation, keyless",
      h1: "Solar API for German cities (PVGIS)",
      lead: "Solar potential per city through a free, keyless REST API. The source is PVGIS by the European Commission (JRC), aggregated to a comparable metric per city and delivered as consistent JSON with source, license and reference period on every response.",
      dataDesc:
        "For each city the endpoint returns a multi-year climatological average at the city centre, normalized to a 1 kWp system at the optimal tilt: annual PV yield in kWh per kWp, global irradiation in kWh per square meter, the optimal tilt and azimuth, and twelve monthly values. It is not a daily value but a long-term average; the reference period is given as a year range in the response.",
      sourceName: "PVGIS, European Commission (JRC)",
      sourceUrl: "https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis_en",
      license: "EU reuse policy (effectively CC BY 4.0)",
      licenseUrl: "https://joint-research-centre.ec.europa.eu/photovoltaic-geographical-information-system-pvgis_en",
      vars: ["Annual PV yield (kWh/kWp)", "Global irradiation (kWh/m²)", "Optimal tilt (degrees)", "Optimal azimuth (degrees, 0 = south)", "12 monthly values (yield + irradiation)", "Reference period (year range)"],
      keywords: ["solar API Germany", "PVGIS API", "solar potential API", "photovoltaic yield API", "solar irradiation API", "free PV yield API"],
      coverageNote: "Solar data is available for all 84 covered cities: PVGIS computes any coordinate in Europe, the values refer to the city centre.",
      faq: [
        { q: "Is the solar API free and keyless?", a: "Yes. No key, no sign-up, free, a single GET request is enough. The rate limit is 300 requests per minute per IP." },
        { q: "What does kWh per kWp mean?", a: "It is the expected annual yield of a photovoltaic system per installed kilowatt-peak at the optimal tilt. This lets you compare locations directly and scale to your planned system size." },
        { q: "Are these live measurements?", a: "No. PVGIS provides a multi-year climatological average, a long-term mean rather than a daily value. That is why observed_at is null; the reference period is given as a year range (period_start/period_end) in the response." },
      ],
      datasetName: "InfraNode solar data for German cities (PVGIS)",
      datasetDesc: "Solar irradiation and normalized PV yield (kWh/kWp, kWh/m², optimal tilt, monthly values) for 84 German cities from European Commission PVGIS data, free and keyless via a JSON REST API.",
    },
  },
  {
    id: "solar-roofs",
    endpointId: "getCitySolarRoofs",
    examplePath: "/api/v1/cities/koeln/solar-roofs",
    coverageKey: "solar-roofs",
    de: {
      slug: "solarkataster-api",
      metaTitle: "Solarkataster-API (Dach-PV): Potenzial je Stadt, keylos (NRW, Bayern, Berlin, Hamburg)",
      h1: "Solarkataster-API für deutsche Städte (Dach-PV)",
      lead: "Das Dach-Photovoltaik-Potenzial je Stadt über eine kostenlose, keylose REST-API. Quelle sind die amtlichen Solarkataster der Länder (NRW: LANUK/Geobasis NRW/MaStR; Bayern: Bayerisches Landesamt für Umwelt; Berlin: Umweltatlas/SenMVKU; Hamburg: LGV), je Gemeinde aggregiert und einheitlich als JSON mit Quelle und Lizenz je Antwort.",
      dataDesc:
        "Pro abgedeckter Stadt liefert der Endpunkt das gesamte installierbare Dach-PV-Potenzial (Leistung in kWp und Jahresertrag in MWh), den bereits installierten Bestand und den Ausschöpfungsgrad in Prozent; für NRW zusätzlich die Aufschlüsselung des Potenzials nach Gebäudekategorie. Je nach Quelle variiert der Umfang: Berlin enthält Potenzial und installierten Bestand, Hamburg derzeit nur das Potenzial. Anders als die Solar-API (Einstrahlung und Ertrag je kWp aus PVGIS) liefert diese Schnittstelle die Mengen je Stadt.",
      sourceName: "Solarkataster der Länder (NRW: LANUK/Geobasis NRW; Bayern: LfU; Berlin: Umweltatlas; Hamburg: LGV)",
      sourceUrl: "https://www.opengeodata.nrw.de/produkte/umwelt_klima/energie/solarkataster/",
      license: "DL-DE Zero 2.0 (NRW, Berlin), CC BY 4.0 (Bayern), DL-DE BY 2.0 (Hamburg)",
      licenseUrl: "https://www.govdata.de/dl-de/zero-2-0",
      vars: ["Installierbares Potenzial (kWp)", "Potenzieller Jahresertrag (MWh)", "Installierter Bestand (kWp)", "Ausschöpfungsgrad (%)", "Potenzial je Gebäudekategorie (NRW)", "Stichtag"],
      keywords: ["Solarkataster API", "Dach-PV Potenzial API", "Solarpotenzial API Deutschland", "Photovoltaik Dachflächen API", "PV Potenzial Stadt API", "Solarkataster NRW Bayern Berlin Hamburg Daten"],
      coverageNote: "Das Dach-Solarkataster ist pro Bundesland föderiert. Aktuell abgedeckt sind die Städte in Nordrhein-Westfalen und Bayern sowie die Stadtstaaten Berlin und Hamburg; weitere Länder folgen, sobald ihr offenes Gemeinde-Aggregat vorliegt.",
      faq: [
        { q: "Ist die Solarkataster-API kostenlos und keylos?", a: "Ja. Kein Schlüssel, keine Anmeldung, kostenlos, ein GET-Request genügt. Das Rate-Limit beträgt 300 Anfragen pro Minute und IP." },
        { q: "Worin unterscheidet sich diese API von der Solar-API?", a: "Die Solar-API (PVGIS) liefert die Sonneneinstrahlung und den erwartbaren Ertrag je installiertem Kilowatt-Peak für jede Stadt. Diese Solarkataster-API liefert das tatsächliche Dachpotenzial je Stadt: wie viel PV installierbar ist und wie viel davon bereits installiert ist." },
        { q: "Welche Länder sind abgedeckt?", a: "Aktuell Nordrhein-Westfalen (Solarkataster NRW, DL-DE Zero 2.0), Bayern (Energie-Atlas Bayern, CC BY 4.0), Berlin (Umweltatlas, DL-DE Zero 2.0) und Hamburg (Solarpotenzialanalyse, DL-DE BY 2.0). Dach-Solarkataster werden je Bundesland erhoben; weitere Länder kommen hinzu, sobald ein offenes Gemeinde-Aggregat vorliegt. Für Städte ohne abgedecktes Land antwortet die API ehrlich mit not_covered statt zu raten." },
      ],
      datasetName: "InfraNode Dach-Solarkataster (Potenzial je Stadt: NRW, Bayern, Berlin, Hamburg)",
      datasetDesc: "Installierbares und installiertes Dach-PV-Potenzial (kWp, MWh, Ausschöpfungsgrad) je Stadt aus den amtlichen Solarkatastern NRW, Bayern, Berlin und Hamburg, kostenlos und keylos über eine REST-API als JSON.",
    },
    en: {
      slug: "solar-cadastre-api",
      metaTitle: "Solar Cadastre API (rooftop PV): potential per city, keyless (NRW, Bavaria, Berlin, Hamburg)",
      h1: "Solar cadastre API for German cities (rooftop PV)",
      lead: "Rooftop photovoltaic potential per city through a free, keyless REST API. The sources are the official state solar cadastres (NRW: LANUK/Geobasis NRW/MaStR; Bavaria: Bavarian Environment Agency; Berlin: Umweltatlas/SenMVKU; Hamburg: LGV), aggregated per municipality and delivered as consistent JSON with source and license on every response.",
      dataDesc:
        "For each covered city the endpoint returns the total installable rooftop PV potential (capacity in kWp and annual yield in MWh), the already installed stock and the exploitation ratio in percent; for NRW also the potential broken down per building category. Coverage varies by source: Berlin includes potential and installed stock, Hamburg currently only the potential. Unlike the solar API (irradiation and yield per kWp from PVGIS), this interface returns the per-city quantities.",
      sourceName: "State solar cadastres (NRW: LANUK/Geobasis NRW; Bavaria: LfU; Berlin: Umweltatlas; Hamburg: LGV)",
      sourceUrl: "https://www.opengeodata.nrw.de/produkte/umwelt_klima/energie/solarkataster/",
      license: "DL-DE Zero 2.0 (NRW, Berlin), CC BY 4.0 (Bavaria), DL-DE BY 2.0 (Hamburg)",
      licenseUrl: "https://www.govdata.de/dl-de/zero-2-0",
      vars: ["Installable potential (kWp)", "Potential annual yield (MWh)", "Installed stock (kWp)", "Exploitation ratio (%)", "Potential per building category (NRW)", "Reference date"],
      keywords: ["solar cadastre API", "rooftop PV potential API", "solar potential API Germany", "photovoltaic rooftop API", "PV potential city API", "Solarkataster NRW Bavaria Berlin Hamburg data"],
      coverageNote: "The rooftop solar cadastre is federated per federal state. Currently covered are the cities in North Rhine-Westphalia and Bavaria as well as the city states Berlin and Hamburg; more states follow once their open municipal aggregate is available.",
      faq: [
        { q: "Is the solar cadastre API free and keyless?", a: "Yes. No key, no sign-up, free, a single GET request is enough. The rate limit is 300 requests per minute per IP." },
        { q: "How does this differ from the solar API?", a: "The solar API (PVGIS) returns solar irradiation and the expected yield per installed kilowatt-peak for any city. This solar cadastre API returns the actual rooftop potential per city: how much PV is installable and how much is already installed." },
        { q: "Which states are covered?", a: "Currently North Rhine-Westphalia (Solarkataster NRW, DL-DE Zero 2.0), Bavaria (Energie-Atlas Bayern, CC BY 4.0), Berlin (Umweltatlas, DL-DE Zero 2.0) and Hamburg (solar potential analysis, DL-DE BY 2.0). Rooftop solar cadastres are compiled per federal state; more states are added once an open municipal aggregate is available. For cities without a covered state the API answers honestly with not_covered instead of guessing." },
      ],
      datasetName: "InfraNode rooftop solar cadastre (potential per city: NRW, Bavaria, Berlin, Hamburg)",
      datasetDesc: "Installable and installed rooftop PV potential (kWp, MWh, exploitation ratio) per city from the official NRW, Bavaria, Berlin and Hamburg solar cadastres, free and keyless via a JSON REST API.",
    },
  },
  {
    id: "public-transport",
    endpointId: "getCityStationDepartures",
    examplePath: "/api/v1/cities/berlin/station-departures",
    // ÖPNV-Echtzeit gibt es für alle Städte (DELFI/HVV GTFS), daher "all".
    // Vorher faelschlich "station-departures" (kein Key in coverage.json) ->
    // Topic erschien auf KEINER Stadt-Landingpage. Fix 2026-06-23.
    coverageKey: "all",
    de: {
      slug: "oepnv-echtzeit-api",
      metaTitle: "ÖPNV-Echtzeit-API Deutschland: Abfahrten je Stadt, keylos",
      h1: "ÖPNV-Echtzeit-API für deutsche Städte",
      lead: "Echtzeit-Abfahrten an Haltestellen deutscher Großstädte über eine kostenlose, keylose REST-API. Datengrundlage sind DELFI und GTFS sowie regionale Verkehrsverbünde, einheitlich als JSON mit Quelle und Zeitstempel je Antwort.",
      dataDesc:
        "Pro Stadt liefert der Endpunkt die nächsten Abfahrten an einer zentralen Haltestelle: Linie, Richtung, geplante und prognostizierte Abfahrtszeit sowie Verspätung. Ein paralleler Endpunkt liefert analog die Ankünfte.",
      sourceName: "DELFI, GTFS und regionale Verkehrsverbünde",
      sourceUrl: "https://www.delfi.de/",
      license: "CC BY 4.0 bzw. verbundspezifisch",
      licenseUrl: "https://creativecommons.org/licenses/by/4.0/",
      vars: ["Linie", "Richtung und Ziel", "Geplante Abfahrtszeit", "Prognostizierte Abfahrtszeit", "Verspätung", "Haltestelle"],
      keywords: ["ÖPNV API Deutschland", "Abfahrten API", "Echtzeit ÖPNV API", "GTFS Echtzeit API", "Fahrplan API kostenlos", "public transport API Germany"],
      coverageNote: "Echtzeit-Abfahrten sind für die Städte mit angebundenen Verbund- bzw. DELFI-Daten verfügbar.",
      faq: [
        { q: "Ist die ÖPNV-Echtzeit-API kostenlos und keylos?", a: "Ja. Kein Schlüssel, keine Anmeldung, kostenlos, ein GET-Request genügt. Das Rate-Limit beträgt 300 Anfragen pro Minute und IP." },
        { q: "Welche Daten enthält eine Abfahrt?", a: "Linie, Richtung und Ziel, die geplante und die prognostizierte Abfahrtszeit sowie die Verspätung, jeweils an einer zentralen Haltestelle der Stadt." },
        { q: "Welche Quellen stehen dahinter?", a: "DELFI und GTFS sowie regionale Verkehrsverbünde. Die jeweils gültige Lizenz und der Attributionshinweis stehen in jeder API-Antwort." },
      ],
      datasetName: "InfraNode ÖPNV-Echtzeit-Abfahrten deutscher Städte",
      datasetDesc: "Echtzeit-Abfahrten und -Ankünfte an Haltestellen deutscher Großstädte aus DELFI-, GTFS- und Verbunddaten, kostenlos und keylos über eine REST-API als JSON.",
    },
    en: {
      slug: "public-transport-api",
      metaTitle: "Germany Public Transport API: real-time departures, keyless",
      h1: "Real-time public transport API for German cities",
      lead: "Real-time departures at stops in major German cities through a free, keyless REST API. The data is based on DELFI and GTFS plus regional transit associations, delivered as consistent JSON with source and timestamp on every response.",
      dataDesc:
        "For each city the endpoint returns the next departures at a central stop: line, direction, planned and predicted departure time and delay. A parallel endpoint returns arrivals in the same shape.",
      sourceName: "DELFI, GTFS and regional transit associations",
      sourceUrl: "https://www.delfi.de/",
      license: "CC BY 4.0 or association-specific",
      licenseUrl: "https://creativecommons.org/licenses/by/4.0/",
      vars: ["Line", "Direction and destination", "Planned departure time", "Predicted departure time", "Delay", "Stop"],
      keywords: ["public transport API Germany", "departures API", "real-time transit API", "GTFS realtime API", "free timetable API", "German transit API"],
      coverageNote: "Real-time departures are available for cities with connected association or DELFI data.",
      faq: [
        { q: "Is the public transport API free and keyless?", a: "Yes. No key, no sign-up, free, a single GET request is enough. The rate limit is 300 requests per minute per IP." },
        { q: "What data does a departure contain?", a: "Line, direction and destination, the planned and predicted departure time and the delay, at a central stop in the city." },
        { q: "Which sources are behind it?", a: "DELFI and GTFS plus regional transit associations. The applicable license and attribution note are included in every API response." },
      ],
      datasetName: "InfraNode real-time public transport departures for German cities",
      datasetDesc: "Real-time departures and arrivals at stops in major German cities from DELFI, GTFS and transit association data, free and keyless via a JSON REST API.",
    },
  },
  {
    id: "public-tenders",
    endpointId: "getCityPublicTenders",
    examplePath: "/api/v1/cities/koeln/public-tenders",
    // Bundesweite OCDS-Quelle (Datenservice Oeffentlicher Einkauf), daher "all".
    coverageKey: "all",
    de: {
      slug: "vergabe-api",
      metaTitle: "Vergabe-API Deutschland: oeffentliche Auftraege je Stadt, keylos",
      h1: "API fuer oeffentliche Auftragsvergabe deutscher Staedte",
      lead: "Laufende Ausschreibungen und vergebene Auftraege deutscher Staedte ueber eine kostenlose, keylose REST-API. Quelle ist der Datenservice Oeffentlicher Einkauf (oeffentlichevergabe.de) im OCDS-Standard, einheitlich als JSON mit Quelle, Lizenz und Zeitstempel je Antwort.",
      dataDesc:
        "Pro Stadt liefert der Endpunkt die oeffentlichen Vergabebekanntmachungen: Bekanntmachungstyp (Ausschreibung oder Zuschlag), Status, Auftraggeber-Ort, Region (NUTS), Leistungsgegenstand (CPV) und, soweit veroeffentlicht, der Auftragswert. Filtern laesst sich nach Status (active fuer laufende, complete fuer vergebene Auftraege).",
      sourceName: "Datenservice Oeffentlicher Einkauf",
      sourceUrl: "https://www.oeffentlichevergabe.de/",
      license: "CC0",
      licenseUrl: "https://creativecommons.org/publicdomain/zero/1.0/",
      vars: ["Bekanntmachungstyp (Ausschreibung/Zuschlag)", "Status", "Auftraggeber-Ort", "Region (NUTS)", "Leistungsgegenstand (CPV)", "Auftragswert"],
      keywords: ["Vergabe API Deutschland", "oeffentliche Auftraege API", "Ausschreibungen API", "OCDS API Deutschland", "Auftragsvergabe Daten API", "public procurement API Germany"],
      coverageNote: "Die Abdeckung waechst: Oberschwellige Bekanntmachungen sind vollstaendig, unterschwellige werden ab 2024 schrittweise ergaenzt.",
      faq: [
        { q: "Ist die Vergabe-API kostenlos und ohne Schluessel nutzbar?", a: "Ja. Die API ist keylos und kostenlos, ein GET-Request ohne Anmeldung genuegt. Das Rate-Limit betraegt 300 Anfragen pro Minute und IP." },
        { q: "Welche Vergabedaten sind enthalten?", a: "Laufende Ausschreibungen und bereits vergebene Auftraege je Stadt mit Bekanntmachungstyp, Status, Auftraggeber-Ort, Region (NUTS), Leistungsgegenstand (CPV) und, soweit veroeffentlicht, dem Auftragswert." },
        { q: "Welche Lizenz gilt fuer die Vergabedaten?", a: "Die Daten stammen aus dem Datenservice Oeffentlicher Einkauf und werden unter CC0 durchgereicht. Lizenz-URL und Attribution stehen in jeder API-Antwort im attribution-Block." },
      ],
      datasetName: "InfraNode Vergabedaten deutscher Staedte (Datenservice Oeffentlicher Einkauf)",
      datasetDesc: "Laufende Ausschreibungen und vergebene Auftraege deutscher Staedte aus dem Datenservice Oeffentlicher Einkauf (OCDS, CC0), kostenlos und keylos ueber eine REST-API als JSON.",
    },
    en: {
      slug: "public-procurement-api",
      metaTitle: "Germany Public Procurement API: tenders per city, keyless",
      h1: "Public procurement API for German cities",
      lead: "Running tenders and awarded contracts for German cities through a free, keyless REST API. The source is the German public procurement data service (oeffentlichevergabe.de) in the OCDS standard, delivered as consistent JSON with source, license and timestamp on every response.",
      dataDesc:
        "For each city the endpoint returns public procurement notices: notice type (tender or award), status, buyer city, region (NUTS), subject of the contract (CPV) and, where published, the contract value. Results can be filtered by status (active for running tenders, complete for awarded contracts).",
      sourceName: "German public procurement data service",
      sourceUrl: "https://www.oeffentlichevergabe.de/",
      license: "CC0",
      licenseUrl: "https://creativecommons.org/publicdomain/zero/1.0/",
      vars: ["Notice type (tender/award)", "Status", "Buyer city", "Region (NUTS)", "Contract subject (CPV)", "Contract value"],
      keywords: ["public procurement API Germany", "public tenders API", "tenders API Germany", "OCDS API Germany", "procurement data API", "government contracts API Germany"],
      coverageNote: "Coverage is growing: above-threshold notices are complete, below-threshold notices are added gradually from 2024 onward.",
      faq: [
        { q: "Is the public procurement API free and usable without a key?", a: "Yes. The API is keyless and free; a GET request without sign-up is enough. The rate limit is 300 requests per minute per IP." },
        { q: "Which procurement data is included?", a: "Running tenders and already awarded contracts per city with notice type, status, buyer city, region (NUTS), contract subject (CPV) and, where published, the contract value." },
        { q: "Which license applies to the procurement data?", a: "Data comes from the German public procurement data service and is passed through under CC0. The license URL and attribution are included in every API response in the attribution block." },
      ],
      datasetName: "InfraNode public procurement data for German cities (German procurement data service)",
      datasetDesc: "Running tenders and awarded contracts for German cities from the German public procurement data service (OCDS, CC0), free and keyless via a JSON REST API.",
    },
  },
];

export function topicCityCount(
  topic: Topic,
  coverage: { total_cities: number; partial: Record<string, string[]> },
): number {
  if (topic.coverageKey === "all") return coverage.total_cities;
  return coverage.partial[topic.coverageKey]?.length ?? 0;
}
