import type { HourRow } from "./types";

/** "08:00" */
export const hh = (h: number) => `${String(h).padStart(2, "0")}:00`;
/** "08:00–08:59" */
export const hourRange = (h: number) => `${hh(h)}–${String(h).padStart(2, "0")}:59`;

/** Hours shown in charts: operating day from 05:00 to 01:00 (02–04 h are ~0 everywhere). */
export const SHOWN = new Set([5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 0, 1]);
export const shownHours = (rows: HourRow[]) => rows.filter((r) => SHOWN.has(r.h));

/** Lower-case, no accents, punctuation -> space. Used for accent-insensitive search. */
export function normalize(s: string): string {
  return s
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

export function formatInt(n: number, lang: string): string {
  return new Intl.NumberFormat(lang === "fr" ? "fr-FR" : "en-GB").format(Math.round(n));
}

/** Rounds entries for display: no false precision on raw validations. */
export function roundEntries(n: number): number {
  if (n < 100) return Math.round(n / 5) * 5;
  if (n < 1000) return Math.round(n / 10) * 10;
  return Math.round(n / 100) * 100;
}
