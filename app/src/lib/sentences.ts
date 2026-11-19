// Sentences built from the facts in lib/state.ts. They describe entries; they never tell
// people what to do (design spec, section 5).
import type { CommonStrings } from "./i18n/common";
import type { DayFacts, NowFacts } from "./state";
import type { ForecastDate, ForecastReason } from "./types";

function less(t: CommonStrings, drop: number): string {
  if (drop >= 0.42 && drop <= 0.58) return t.lessHalf;
  if (drop < 0.15) return t.lessSlight;
  return t.lessPct(Math.round((drop * 100) / 10) * 10);
}

/** Summary under the headline of a "now" screen. */
export function nowSummary(t: CommonStrings, f: NowFacts): string {
  if (f.offHours) return t.nowOffHours;
  if (f.ground === "nuit") {
    if (f.calmerHour == null || f.calmerDrop == null) return t.nowBusyAllDay;
    return `${t.nowBusy} ${t.calmerAround(less(t, f.calmerDrop), t.hour(f.calmerHour))}`;
  }
  if (f.band === "quiet") {
    return f.busyFromHour == null ? t.nowQuietAllDay : t.nowQuietUntil(t.hour(f.busyFromHour));
  }
  return f.busyFromHour == null ? t.nowModerateAllDay : t.nowModerateUntil(t.hour(f.busyFromHour));
}

/** One short fact for a home tile. */
export function tileFact(t: CommonStrings, f: NowFacts): string {
  if (f.offHours) return t.nowOffHours;
  if (f.ground === "nuit") {
    if (f.calmerHour == null || f.calmerDrop == null) return t.tileBusyAllDay;
    return t.calmerAround(less(t, f.calmerDrop), t.hour(f.calmerHour));
  }
  if (f.busyFromHour == null) return t.tileQuietAllDay;
  return f.band === "quiet"
    ? t.tileQuietUntil(t.hour(f.busyFromHour))
    : t.tileModerateUntil(t.hour(f.busyFromHour));
}

/** Headline of a chosen date: when the day is busiest. */
export function dayHeadline(t: CommonStrings, f: DayFacts): string {
  if (!f.busiestWindow) return t.dayNoData;
  return t.dayBusiest(t.hour(f.busiestWindow[0]), t.hour(f.busiestWindow[1]));
}

export function dayCalmest(t: CommonStrings, f: DayFacts): string | null {
  if (!f.calmestWindow) return null;
  return t.dayCalmest(t.hour(f.calmestWindow[0]), t.hour(f.calmestWindow[1]));
}

/** "Environ 30 % de moins qu’un jour de semaine habituel." Null without a forecast delta. */
export function dayComparison(t: CommonStrings, d: ForecastDate | null): string | null {
  if (!d || d.delta_pct == null) return null;
  const usual = t.usualDay[d.day_type];
  const n = Math.abs(Math.round(d.delta_pct));
  if (n < 3) return t.deltaSame(usual);
  return d.delta_pct > 0 ? t.deltaMore(n, usual) : t.deltaLess(n, usual);
}

const SPECIAL: ForecastReason[] = ["christmas_eve", "christmas_day", "new_years_eve", "new_years_day"];
/** Special days whose hourly profile is less certain (data-quality.md, "Special days"). */
export const isSpecialDay = (d: ForecastDate | null) =>
  !!d && d.reasons.some((r) => SPECIAL.includes(r));

/** First reason, to name the day: "Jeudi 24 décembre, veille de Noël". */
export function dayReason(t: CommonStrings, d: ForecastDate | null): string | null {
  const r = d?.reasons[0];
  return r ? t.reason[r] : null;
}
