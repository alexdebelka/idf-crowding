// FR / EN strings, one module per area so each screen owns its own file.
import { common } from "./common";
import { home } from "./home";
import { method } from "./method";
import { station } from "./station";

export type Lang = "fr" | "en";
export const LANGS: Lang[] = ["fr", "en"];

export const STRINGS = {
  fr: { common: common.fr, station: station.fr, home: home.fr, method: method.fr },
  en: { common: common.en, station: station.en, home: home.en, method: method.en },
};
export type Strings = (typeof STRINGS)["fr"];

const LOCALE: Record<Lang, string> = { fr: "fr-FR", en: "en-GB" };
export const localeOf = (lang: Lang) => LOCALE[lang];

const utc = (iso: string) => new Date(`${iso}T00:00:00Z`);
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
/** French writes the first of the month "1er". */
const premier = (s: string, lang: Lang) => (lang === "fr" ? s.replace(/(^|\s)1 (?=\p{L})/u, "$11er ") : s);

/** "30 juin 2026" / "30 June 2026". */
export function formatDate(iso: string, lang: Lang): string {
  return premier(
    new Intl.DateTimeFormat(LOCALE[lang], {
      day: "numeric",
      month: "long",
      year: "numeric",
      timeZone: "UTC",
    }).format(utc(iso)),
    lang,
  );
}

/** "Jeudi 24 décembre" / "Thursday 24 December". */
export function formatDayLong(iso: string, lang: Lang): string {
  return cap(
    premier(
      new Intl.DateTimeFormat(LOCALE[lang], {
        weekday: "long",
        day: "numeric",
        month: "long",
        timeZone: "UTC",
      }).format(utc(iso)),
      lang,
    ),
  );
}

/** "jeu. 24 déc." / "Thu 24 Dec" for the date pill. */
export function formatDayShort(iso: string, lang: Lang): string {
  return new Intl.DateTimeFormat(LOCALE[lang], {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(utc(iso));
}

/** One decimal under 10, none above: "8,4" / "12". */
export function formatPct(n: number, lang: Lang): string {
  return new Intl.NumberFormat(LOCALE[lang], {
    maximumFractionDigits: n < 10 ? 1 : 0,
  }).format(n);
}
