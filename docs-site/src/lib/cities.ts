// Helfer fuer die per-City-Landingpages (SEO-Massnahme 2). Bundesland-Namen
// und die je Stadt verfuegbaren Datenarten (aus topics + coverage.json).
import { topics, type Topic } from "../data/topics";

// Bundesland-Kuerzel -> ausgeschriebener Name (echte Umlaute). Eigennamen,
// daher in DE und EN identisch.
export const STATES: Record<string, string> = {
  BW: "Baden-Württemberg",
  BY: "Bayern",
  BE: "Berlin",
  BB: "Brandenburg",
  HB: "Bremen",
  HH: "Hamburg",
  HE: "Hessen",
  MV: "Mecklenburg-Vorpommern",
  NI: "Niedersachsen",
  NW: "Nordrhein-Westfalen",
  RP: "Rheinland-Pfalz",
  SL: "Saarland",
  SN: "Sachsen",
  ST: "Sachsen-Anhalt",
  SH: "Schleswig-Holstein",
  TH: "Thüringen",
};

export interface Coverage {
  total_cities: number;
  partial: Record<string, string[]>;
}

// Liefert die Topics, die fuer eine konkrete Stadt verfuegbar sind: "all"-Topics
// immer, partielle nur, wenn der Slug in der coverage-Liste steht.
export function topicsForCity(slug: string, coverage: Coverage): Topic[] {
  return topics.filter((topic) => {
    if (topic.coverageKey === "all") return true;
    return coverage.partial[topic.coverageKey]?.includes(slug) ?? false;
  });
}
