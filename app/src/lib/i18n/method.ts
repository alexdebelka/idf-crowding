// Strings of the method page (/a-propos/). French is the reference; `en` must keep the same
// shape. Every number comes from the data files (index.json, accuracy.json, a Place file's
// forecast block); sentences only describe the method (docs/data-quality.md), never advise.

const fr = {
  pageTitle: "Comment c’est calculé",
  headline: "Comment c’est calculé.",
  lead: "Une prévision du nombre d’entrées dans chaque gare, jour par jour et heure par heure, à partir de données ouvertes.",

  countedTitle: "Ce qui est compté",
  // IDFM validation documentation (DATA_SOURCES.md #3): p. 12 (validation tied to the station,
  // not the line; no new validation when changing line), p. 26 (exits and transfers excluded,
  // only entries from the street), p. 8 (people who enter without validating are not counted).
  counted:
    "Les validations à l’entrée des gares desservies par le métro ou le RER, publiées par Île-de-France Mobilités. Chaque validation est rattachée à la gare, pas à la ligne prise ensuite.",
  notCounted:
    "Ce n’est pas un comptage des personnes sur le quai : les sorties et les changements de ligne à l’intérieur du réseau ne sont pas comptés, ni les personnes qui entrent sans valider (accès sans portique, portiques hors service, fraude).",

  levelsTitle: "Les quatre niveaux",
  levels: (start: string, end: string) =>
    `Chaque heure est comparée à un repère propre à la gare (100), fixé près de ses heures les plus chargées entre le ${start} et le ${end}. Les heures de pointe de semaine le dépassent.`,
  below: (n: string) => `moins de ${n}`,
  between: (a: string, b: string) => `de ${a} à ${b}`,
  andAbove: (n: string) => `${n} et plus`,

  forecastTitle: "La prévision",
  forecastModels:
    "Deux modèles d’apprentissage automatique apprennent sur les entrées observées des dernières années : jour de la semaine, vacances scolaires, jours fériés et ponts, saison. La prévision retenue est leur moyenne.",
  forecastHours: "Les heures viennent du profil habituel de la gare pour ce type de jour.",

  accuracyTitle: "Sa précision",
  accuracyHow: (start: string, end: string, minMonths: string, maxMonths: string) =>
    `Mesurée sur les journées du ${start} au ${end}, prévues sans les ${minMonths} à ${maxMonths} derniers mois de données, pour reproduire le retard de publication.`,
  accuracyHowShort: (start: string, end: string) =>
    `Mesurée sur les journées du ${start} au ${end}, prévues en reproduisant le retard de publication.`,
  accuracyCaveats:
    "Ces chiffres portent sur le total de la journée : la répartition heure par heure n’a pas été mesurée. Les petites gares sont moins bien prévues que les grandes.",
  about: (v: string) => `≈\u00a0${v}\u00a0%`,
  tileStation: "d’écart moyen par gare, sur le total d’une journée",
  tileNetwork: "d’écart sur le total de tout le réseau",
  tileBandValue: (k: number) => `${k}\u00a0sur\u00a010`,
  tileBand: "journées dans la fourchette de prévision",
  tileSpecial: (season: number) =>
    `d’écart les 24, 25, 31 décembre et 1er janvier (fêtes ${season}-${season + 1})`,
  spread: (median: string, p90: string) =>
    `D’une gare à l’autre : la moitié des gares ont un écart moyen sous ${median}\u00a0%, 9 gares sur 10 sous ${p90}\u00a0%.`,
  spreadBase: (n: number, total: number, minDays: number) =>
    `${n} gares sur ${total} ont au moins ${minDays} journées mesurées ; les autres n’ont pas de chiffre.`,

  delayTitle: "Un décalage de plusieurs mois",
  delay: (dataEnd: string, issue: string, minMonths: string, maxMonths: string) =>
    `Les validations sont publiées avec retard. La prévision actuelle s’appuie sur les données publiées jusqu’au ${dataEnd} ; calculée le ${issue}, elle porte sur des jours situés ${minMonths} à ${maxMonths} mois après ce dernier jour connu.`,
  delayNoForecast: (dataEnd: string) =>
    `Les validations sont publiées avec retard : les données disponibles s’arrêtent au ${dataEnd}.`,

  limitsTitle: "Ses limites",
  limitsEvents: "Travaux, grèves et incidents ne sont pas pris en compte.",
  limitsSpecial: (season: number) =>
    `Les 24, 25, 31 décembre et 1er janvier sont corrigés d’après les mêmes jours des années précédentes ; la correction n’a été vérifiée que sur les fêtes ${season}-${season + 1}. Leurs heures sont moins sûres.`,
  limitsSpecialShort:
    "Les 24, 25, 31 décembre et 1er janvier sont corrigés d’après les mêmes jours des années précédentes ; leurs heures sont moins sûres.",
  limitsTrend:
    "La croissance de la fréquentation sur un an est prolongée : si elle ralentit, la prévision peut être trop haute.",

  traffic: "Aucun cookie, aucun script de mesure d’audience.",
};

export type MethodStrings = typeof fr;

// English reviewed (British spelling, 24-hour clock, entries described, never advice).
const en: MethodStrings = {
  pageTitle: "How it is calculated",
  headline: "How it is calculated.",
  lead: "A forecast of the number of entries at each station, day by day and hour by hour, from open data.",
  countedTitle: "What is counted",
  counted:
    "Validations at the entrances of stations served by the metro or RER, published by Île-de-France Mobilités. Each validation belongs to the station, not to the line taken next.",
  notCounted:
    "It is not a count of people on the platform: exits and line changes inside the network are not counted, nor are people who enter without validating (stations without gates, gates out of service, fare evasion).",
  levelsTitle: "The four levels",
  levels: (start: string, end: string) =>
    `Each hour is compared with the station’s own reference level (100), set near its busiest hours between ${start} and ${end}. Weekday rush hours go above it.`,
  below: (n: string) => `under ${n}`,
  between: (a: string, b: string) => `${a} to ${b}`,
  andAbove: (n: string) => `${n} and above`,
  forecastTitle: "The forecast",
  forecastModels:
    "Two machine-learning models learn from entries recorded in recent years: day of the week, school holidays, public holidays and bridge days, season. The forecast is their mean.",
  forecastHours: "Hours come from the station’s usual profile for that kind of day.",
  accuracyTitle: "How accurate it is",
  accuracyHow: (start: string, end: string, minMonths: string, maxMonths: string) =>
    `Measured on the days from ${start} to ${end}, each forecast without the last ${minMonths} to ${maxMonths} months of data, to reproduce the publication delay.`,
  accuracyHowShort: (start: string, end: string) =>
    `Measured on the days from ${start} to ${end}, each forecast with the publication delay reproduced.`,
  accuracyCaveats:
    "These figures are about the daily total: the hour-by-hour split was not measured. Small stations are forecast less well than large ones.",
  about: (v: string) => `≈\u00a0${v}%`,
  tileStation: "average error per station, on a day’s total",
  tileNetwork: "error on the whole network’s total",
  tileBandValue: (k: number) => `${k}\u00a0in\u00a010`,
  tileBand: "days within the forecast range",
  tileSpecial: (season: number) =>
    `error on 24, 25, 31 December and 1 January (${season}–${season + 1} festive season)`,
  spread: (median: string, p90: string) =>
    `Station by station: half of the stations have an average error under ${median}%, 9 in 10 under ${p90}%.`,
  spreadBase: (n: number, total: number, minDays: number) =>
    `${n} of ${total} stations have at least ${minDays} measured days; the others have no figure.`,
  delayTitle: "A delay of several months",
  delay: (dataEnd: string, issue: string, minMonths: string, maxMonths: string) =>
    `Validations are published late. The current forecast uses data published up to ${dataEnd}; calculated on ${issue}, it covers days ${minMonths} to ${maxMonths} months after that last known day.`,
  delayNoForecast: (dataEnd: string) =>
    `Validations are published late: the available data end on ${dataEnd}.`,
  limitsTitle: "Limits",
  limitsEvents: "Engineering works, strikes and incidents are not taken into account.",
  limitsSpecial: (season: number) =>
    `24, 25, 31 December and 1 January are corrected from the same days in earlier years; the correction was checked on the ${season}–${season + 1} festive season only. Their hours are less certain.`,
  limitsSpecialShort:
    "24, 25, 31 December and 1 January are corrected from the same days in earlier years; their hours are less certain.",
  limitsTrend:
    "The past year’s growth in ridership is carried forward: if it slows, the forecast may be too high.",
  traffic: "No cookies, no analytics script.",
};

export const method = { fr, en };
