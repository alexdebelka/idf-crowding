// Clock and calendar helpers. All "now" logic runs in Europe/Paris, whatever the device zone.
import type { DayTypeCode } from "./types";

export const TZ = "Europe/Paris";

/** Hour order of every 24-value array in the Place files: the operating day, 04 h to 03 h. */
export const HOUR_ORDER = [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 0, 1, 2, 3];
/** Hours drawn in the charts: 5 h to 0 h, 20 bars (design spec, section 6). */
export const CHART_HOURS = [5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 0];

/** Position of clock hour `h` in an operating-day array. */
export const hourIndex = (h: number) => (h - 4 + 24) % 24;

export interface ParisClock {
  /** Calendar date in Paris, YYYY-MM-DD. */
  date: string;
  hour: number;
  minute: number;
}

export function parisClock(now: Date = new Date()): ParisClock {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(now);
  const get = (t: string) => parts.find((p) => p.type === t)?.value ?? "0";
  return {
    date: `${get("year")}-${get("month")}-${get("day")}`,
    hour: Number(get("hour")) % 24,
    minute: Number(get("minute")),
  };
}

/** Date arithmetic on YYYY-MM-DD strings (UTC, so no daylight-saving surprises). */
export function addDays(iso: string, n: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** 0 = Sunday … 6 = Saturday. */
export const weekdayOf = (iso: string) => new Date(`${iso}T00:00:00Z`).getUTCDay();

export interface ServiceNow {
  /** Operating date: before 04 h the service still belongs to the previous calendar day. */
  date: string;
  hour: number;
  /** Position of the current hour in an operating-day array. */
  index: number;
}

export function serviceNow(now: Date = new Date()): ServiceNow {
  const c = parisClock(now);
  return { date: c.hour < 4 ? addDays(c.date, -1) : c.date, hour: c.hour, index: hourIndex(c.hour) };
}

/** Day type of a date when no forecast says better: ignores school and public holidays. */
export function defaultDayType(iso: string): DayTypeCode {
  const wd = weekdayOf(iso);
  if (wd === 0) return "DIJFP";
  if (wd === 6) return "SAHV";
  return "JOHV";
}

export const isIsoDate = (s: string | null | undefined): s is string =>
  !!s && /^\d{4}-\d{2}-\d{2}$/.test(s) && !Number.isNaN(Date.parse(`${s}T00:00:00Z`));
