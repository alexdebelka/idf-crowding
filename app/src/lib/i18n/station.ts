// Strings of the station screens. French is the reference; `en` must keep the same shape.
// Shared wording (headlines, summaries, legend, notes) lives in common.ts.
const fr = {
  /** Date line of the computer layout: "Jeudi 24 décembre, veille de Noël, heure par heure". */
  byHour: (day: string) => `${day}, heure par heure`,
  /** Date line with the day's reason: "Jeudi 24 décembre, veille de Noël". */
  dayWithReason: (day: string, reason: string) => `${day}, ${reason}`,
  /** Accessible name of the date pill: "Choisir une date. Date affichée : aujourd’hui." */
  pickerLabel: (shown: string) => `Choisir une date. Date affichée : ${shown}.`,
  backToToday: "Aujourd’hui",
  backToTodayLabel: "Revenir à aujourd’hui",
  /** Station name before the headline, for screen readers ("Châtelet – Les Halles : Calme."). */
  stationPrefix: (name: string) => `${name} : `,
  /** Headline of the chosen date, read with the date ("Jeudi 24 décembre : Plus chargé…"). */
  datePrefix: (day: string) => `${day} : `,
  /** Next departures in real time (the block under the chart). */
  departuresTitle: "Prochains départs, en temps réel",
  minutes: (m: number) => `${m}\u00a0min`,
  approaching: "à l’approche",
  atPlatform: "à quai",
  departuresAll: (n: number) => `Voir les ${n} directions`,
  departuresLess: "Voir moins",
  /** Favourite star in the header. */
  favAdd: "Ajouter à vos gares",
  favRemove: "Retirer de vos gares",
  favAdded: "Ajoutée à vos gares.",
  favRemoved: "Retirée de vos gares.",
  favFull: (n: number) => `Vos gares sont complètes (${n}). Retirez-en une pour en ajouter.`,
  favError: "Cet appareil n’a pas pu enregistrer la gare.",
};

export type StationStrings = typeof fr;

// English reviewed (British spelling, 24-hour clock, entries described, never advice).
const en: StationStrings = {
  byHour: (day: string) => `${day}, hour by hour`,
  dayWithReason: (day: string, reason: string) => `${day}, ${reason}`,
  pickerLabel: (shown: string) => `Choose a date. Date shown: ${shown}.`,
  backToToday: "Today",
  backToTodayLabel: "Back to today",
  stationPrefix: (name: string) => `${name}: `,
  datePrefix: (day: string) => `${day}: `,
  departuresTitle: "Next departures, live",
  minutes: (m: number) => `${m}\u00a0min`,
  approaching: "approaching",
  atPlatform: "at platform",
  departuresAll: (n: number) => `Show all ${n} directions`,
  departuresLess: "Show fewer",
  favAdd: "Add to your stations",
  favRemove: "Remove from your stations",
  favAdded: "Added to your stations.",
  favRemoved: "Removed from your stations.",
  favFull: (n: number) => `Your stations are full (${n}). Remove one to add another.`,
  favError: "This device could not save the station.",
};

export const station = { fr, en };
