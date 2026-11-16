import type { Band, DayTypeCode } from "./types";

export type Lang = "fr" | "en";
export const LANGS: Lang[] = ["fr", "en"];

const fr = {
  appName: "Quai libre",
  tagline: "Quand prendre le métro ou le RER pour éviter la foule.",
  navStations: "Gares",
  navAbout: "Méthode et données",
  searchLabel: "Rechercher une station de métro ou de RER",
  searchPlaceholder: "Station, ville ou ligne (ex. Châtelet, Nanterre, ligne 13)",
  noResult: "Aucune station trouvée.",
  busiest: "Grandes gares",
  stationsCount: (n: number) => `${n} stations de métro et RER`,
  dayTypes: {
    JOHV: "Semaine (période scolaire)",
    JOVS: "Semaine (vacances scolaires)",
    SAHV: "Samedi (période scolaire)",
    SAVS: "Samedi (vacances scolaires)",
    DIJFP: "Dimanche et jours fériés",
  } satisfies Record<DayTypeCode, string>,
  dayTypesShort: {
    JOHV: "Semaine",
    JOVS: "Semaine vac.",
    SAHV: "Samedi",
    SAVS: "Samedi vac.",
    DIJFP: "Dim. & fériés",
  } satisfies Record<DayTypeCode, string>,
  bands: {
    quiet: "Calme",
    moderate: "Modéré",
    busy: "Chargé",
    very_busy: "Très chargé",
  } satisfies Record<Band, string>,
  typicalWeek: "Semaine type",
  typicalWeekHelp:
    "Score d’affluence par heure (100 = niveau de référence de la station). Cliquez sur une ligne pour le détail.",
  hourly: "Heure par heure",
  score: "Score",
  hour: "Heure",
  band: "Niveau",
  entries: "Entrées",
  expectedEntries: (n: string) => `≈ ${n} entrées / h`,
  entriesNote: "validations brutes, entrées depuis la rue",
  dailyEntries: (n: string) => `≈ ${n} entrées par jour`,
  peakHint: (peak: string, alt: string, pct: number) =>
    `Pointe à ${peak} : à ${alt}, ${pct} % de monde en moins.`,
  quietest: (hours: string) => `Créneaux les plus calmes (6 h – 22 h) : ${hours}.`,
  referenceLine: "Niveau de référence (100)",
  quietLegend: "Créneau calme conseillé",
  lowConfidence: "Peu de jours observés pour ce type de jour : à prendre avec prudence.",
  basedOn: (n: number, start: string, end: string) =>
    `Moyenne de ${n} jours entre le ${start} et le ${end}.`,
  showTable: "Voir les valeurs",
  notTrainLoad:
    "Ce score décrit les entrées dans la station, pas le remplissage des trains ni les correspondances.",
  lines: "Lignes",
  back: "← Toutes les stations",
  footerData: "Données : Île-de-France Mobilités (ODbL)",
  footerDerived: "Données dérivées sous ODbL · Code sous licence MIT",
  footerIndependent: "Projet indépendant, sans lien avec IDFM, la RATP ou la SNCF.",
  dataPeriod: (s: string, e: string) => `Données du ${s} au ${e}`,
  language: "Langue",
  notFound: "Station introuvable.",
};

type Strings = typeof fr;

const en: Strings = {
  appName: "Quai libre",
  tagline: "When to take the metro or RER to avoid the crowds.",
  navStations: "Stations",
  navAbout: "Method & data",
  searchLabel: "Search a metro or RER station",
  searchPlaceholder: "Station, town or line (e.g. Châtelet, Nanterre, line 13)",
  noResult: "No station found.",
  busiest: "Major stations",
  stationsCount: (n: number) => `${n} metro and RER stations`,
  dayTypes: {
    JOHV: "Weekday (school term)",
    JOVS: "Weekday (school holidays)",
    SAHV: "Saturday (term)",
    SAVS: "Saturday (holidays)",
    DIJFP: "Sunday & public holidays",
  },
  dayTypesShort: {
    JOHV: "Weekday",
    JOVS: "Wkday hol.",
    SAHV: "Saturday",
    SAVS: "Sat. hol.",
    DIJFP: "Sun. & hol.",
  },
  bands: { quiet: "Quiet", moderate: "Moderate", busy: "Busy", very_busy: "Very busy" },
  typicalWeek: "Typical week",
  typicalWeekHelp:
    "Crowding score by hour (100 = the station's reference level). Click a row for details.",
  hourly: "Hour by hour",
  score: "Score",
  hour: "Hour",
  band: "Level",
  entries: "Entries",
  expectedEntries: (n: string) => `≈ ${n} entries / h`,
  entriesNote: "raw validations, entries from the street",
  dailyEntries: (n: string) => `≈ ${n} entries per day`,
  peakHint: (peak: string, alt: string, pct: number) =>
    `Peak at ${peak}: at ${alt}, ${pct}% fewer people.`,
  quietest: (hours: string) => `Quietest slots (6 am – 10 pm): ${hours}.`,
  referenceLine: "Reference level (100)",
  quietLegend: "Suggested quiet slot",
  lowConfidence: "Few days observed for this day type: treat with caution.",
  basedOn: (n: number, start: string, end: string) =>
    `Average of ${n} days between ${start} and ${end}.`,
  showTable: "Show values",
  notTrainLoad:
    "This score describes entries into the station, not how full trains are, nor transfers.",
  lines: "Lines",
  back: "← All stations",
  footerData: "Data: Île-de-France Mobilités (ODbL)",
  footerDerived: "Derived data under ODbL · Code under the MIT licence",
  footerIndependent: "Independent project, not affiliated with IDFM, RATP or SNCF.",
  dataPeriod: (s: string, e: string) => `Data from ${s} to ${e}`,
  language: "Language",
  notFound: "Station not found.",
};

export const STRINGS: Record<Lang, Strings> = { fr, en };
export type { Strings };

export function formatDate(iso: string, lang: Lang): string {
  return new Intl.DateTimeFormat(lang === "fr" ? "fr-FR" : "en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${iso}T00:00:00Z`));
}
