// From a Place file to what a screen shows: the day's 24 scores, the current band, and the
// facts the sentences are built from. Pure functions, tested in test/state.test.ts.
import { CHART_HOURS, defaultDayType, hourIndex } from "./time";
import type { Band, DayTypeCode, ForecastDate, IndexFile, PlaceFile } from "./types";

export type BandRule = { band: Band; below: number | null };

/** Same thresholds as `config.toml` / `index.json` (`bands`). Used when the index is not at hand. */
export const DEFAULT_BANDS: BandRule[] = [
  { band: "quiet", below: 40 },
  { band: "moderate", below: 70 },
  { band: "busy", below: 100 },
  { band: "very_busy", below: null },
];

export const bandRules = (index?: Pick<IndexFile, "bands"> | null): BandRule[] =>
  index?.bands?.length ? index.bands : DEFAULT_BANDS;

export function bandOf(score: number, rules: BandRule[] = DEFAULT_BANDS): Band {
  for (const r of rules) if (r.below == null || score < r.below) return r.band;
  return "very_busy";
}

/** Design spec, section 2: two grounds, four headlines. */
export type Ground = "signal" | "nuit" | "papier";
export const groundOf = (band: Band): "signal" | "nuit" =>
  band === "quiet" || band === "moderate" ? "signal" : "nuit";
export const isCalm = (band: Band) => groundOf(band) === "signal";

/** Score at which the ground turns to Nuit (lower bound of "busy"). */
export function busyThreshold(rules: BandRule[] = DEFAULT_BANDS): number {
  return rules.find((r) => r.band === "moderate")?.below ?? 70;
}

export interface DayView {
  date: string;
  dayType: DayTypeCode;
  /** 24 Crowding scores in operating-day order (04 h … 03 h). */
  scores: number[];
  /** "forecast": the date has its own forecast; "typical": typical week of the day type. */
  source: "forecast" | "typical";
  entry: ForecastDate | null;
}

/** Scores of one date: its forecast when the Place file has one, else the typical week. */
export function dayView(place: PlaceFile, date: string): DayView | null {
  const entry = place.forecast?.dates.find((d) => d.d === date) ?? null;
  if (entry && entry.scores.length === 24) {
    return { date, dayType: entry.day_type, scores: entry.scores, source: "forecast", entry };
  }
  const wanted = defaultDayType(date);
  const fallbacks: DayTypeCode[] = [wanted, "JOHV", "JOVS", "SAHV", "SAVS", "DIJFP"];
  for (const dt of fallbacks) {
    const t = place.day_types[dt];
    if (t && t.hours.length === 24) {
      const scores = new Array<number>(24).fill(0);
      for (const r of t.hours) scores[hourIndex(r.h)] = r.score;
      return { date, dayType: dt, scores, source: "typical", entry: null };
    }
  }
  return null;
}

/** Forecast dates still ahead (or today), in order. `today` is the operating date. */
export function upcomingDates(place: PlaceFile, today: string): ForecastDate[] {
  return (place.forecast?.dates ?? []).filter((d) => d.d >= today);
}

export interface ChartHour {
  h: number;
  score: number;
}

/** The 20 chart hours (5 h … 0 h) of a day. */
export const chartHours = (scores: number[]): ChartHour[] =>
  CHART_HOURS.map((h) => ({ h, score: scores[hourIndex(h)] ?? 0 }));

export interface NowFacts {
  hour: number;
  score: number;
  band: Band;
  ground: "signal" | "nuit";
  /** Full state: first later chart hour today under the busy threshold. */
  calmerHour: number | null;
  /** Share of entries lost at `calmerHour` compared with now, 0–1. */
  calmerDrop: number | null;
  /** Calm state: first later chart hour today at or over the busy threshold. */
  busyFromHour: number | null;
  /** True between the last and the first chart hour (1 h – 4 h): the network is closed or nearly. */
  offHours: boolean;
}

export function nowFacts(scores: number[], hour: number, rules: BandRule[] = DEFAULT_BANDS): NowFacts {
  const score = scores[hourIndex(hour)] ?? 0;
  const band = bandOf(score, rules);
  const ground = groundOf(band);
  const limit = busyThreshold(rules);
  const pos = CHART_HOURS.indexOf(hour);
  const later = pos < 0 ? [] : CHART_HOURS.slice(pos + 1);
  let calmerHour: number | null = null;
  let busyFromHour: number | null = null;
  for (const h of later) {
    const s = scores[hourIndex(h)] ?? 0;
    if (calmerHour == null && s < limit) calmerHour = h;
    if (busyFromHour == null && s >= limit) busyFromHour = h;
  }
  const calmerDrop =
    ground === "nuit" && calmerHour != null && score > 0
      ? 1 - (scores[hourIndex(calmerHour)] ?? 0) / score
      : null;
  return {
    hour,
    score,
    band,
    ground,
    calmerHour: ground === "nuit" ? calmerHour : null,
    calmerDrop,
    busyFromHour: ground === "signal" ? busyFromHour : null,
    offHours: pos < 0,
  };
}

export interface DayFacts {
  /** Up to four highest chart hours (dark bars). */
  busiest: number[];
  /** Longest run of consecutive busiest hours holding the day's peak: [from, to) clock hours. */
  busiestWindow: [number, number] | null;
  /** The two consecutive daytime hours (7 h – 21 h) with the fewest entries (lime bars). */
  calmest: number[];
  calmestWindow: [number, number] | null;
  peakScore: number;
}

export function dayFacts(scores: number[]): DayFacts {
  const hours = chartHours(scores);
  const peakScore = Math.max(0, ...hours.map((x) => x.score));
  if (peakScore <= 0) {
    return { busiest: [], busiestWindow: null, calmest: [], calmestWindow: null, peakScore: 0 };
  }
  const ranked = [...hours].sort((a, b) => b.score - a.score || hours.indexOf(a) - hours.indexOf(b));
  const busiest = ranked
    .slice(0, 4)
    .filter((x) => x.score > 0)
    .map((x) => x.h);
  const pos = (h: number) => CHART_HOURS.indexOf(h);
  const set = new Set(busiest.map(pos));
  let from = pos(ranked[0].h);
  let to = from;
  while (set.has(from - 1)) from -= 1;
  while (set.has(to + 1)) to += 1;
  const end = (p: number) => (CHART_HOURS[p] + 1) % 24;
  const day = hours.filter((x) => x.h >= 7 && x.h <= 20);
  let best = 0;
  for (let i = 1; i < day.length - 1; i += 1) {
    if (day[i].score + day[i + 1].score < day[best].score + day[best + 1].score) best = i;
  }
  const calmest = [day[best].h, day[best + 1].h].filter((h) => !busiest.includes(h));
  return {
    busiest: busiest.sort((a, b) => pos(a) - pos(b)),
    busiestWindow: [CHART_HOURS[from], end(to)],
    calmest,
    calmestWindow: calmest.length === 2 ? [calmest[0], (calmest[1] + 1) % 24] : null,
    peakScore,
  };
}
