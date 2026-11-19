// Forecast accuracy summary (accuracy.json, schemas/accuracy.v1.schema.json), written by
// `idf-score build` from the production-like backtest. The file is read at build time by
// app/a-propos/page.tsx; this module stays free of Node APIs so client components can use
// it. The page must build without the file (a missing file or tile hides that part).
import type { Band, IndexFile, PlaceFile } from "./types";

export interface Span {
  first: string;
  last: string;
}

export interface AccuracyFile {
  schema_version: 1;
  generated_at: string;
  log: {
    variant: string;
    lag_days: number;
    weather: "observed" | "production";
    model: string;
    model_label?: string;
    n_origins: number;
    origins: Span;
    period: { start: string; end: string };
    days_since_data?: { min: number; max: number };
  };
  min_days: number;
  day_definition: string;
  places: {
    n_places: number;
    n_with_figure: number;
    median_pct: number | null;
    p90_pct: number | null;
  };
  tiles: {
    station_wape_pct?: number;
    network_wape_pct?: number;
    band?: { level: number; coverage: number };
    special_days?: { wape_pct: number; season: number; n_rows: number; method?: string };
  };
}

/** Parsed accuracy.json, or null when the text is absent, invalid or of another version. */
export function parseAccuracy(text: string | null): AccuracyFile | null {
  if (text == null) return null;
  try {
    const a = JSON.parse(text) as AccuracyFile;
    return a?.schema_version === 1 && a.tiles && a.places && a.log ? a : null;
  } catch {
    return null;
  }
}

export type Tile =
  | { kind: "station"; pct: number }
  | { kind: "network"; pct: number }
  | { kind: "band"; inTen: number }
  | { kind: "special"; pct: number; season: number };

/** The method page's tiles, in mockup order; a tile without its figure is left out. */
export function accuracyTiles(a: AccuracyFile | null): Tile[] {
  if (!a) return [];
  const t = a.tiles;
  const out: Tile[] = [];
  if (t.station_wape_pct != null) out.push({ kind: "station", pct: t.station_wape_pct });
  if (t.network_wape_pct != null) out.push({ kind: "network", pct: t.network_wape_pct });
  if (t.band) out.push({ kind: "band", inTen: Math.round(t.band.coverage * 10) });
  if (t.special_days)
    out.push({ kind: "special", pct: t.special_days.wape_pct, season: t.special_days.season });
  return out;
}

/** Spread across Places, when both figures exist. */
export function accuracySpread(a: AccuracyFile | null) {
  if (!a || a.places.median_pct == null || a.places.p90_pct == null) return null;
  return {
    median: a.places.median_pct,
    p90: a.places.p90_pct,
    n: a.places.n_with_figure,
    total: a.places.n_places,
    minDays: a.min_days,
  };
}

const DAY_MS = 86_400_000;
const days = (from: string, to: string) =>
  Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / DAY_MS);

/** Months (30.44 days) in a number of days, rounded to the nearest whole month. */
export const monthsOf = (n: number) => Math.round(n / 30.44);

/** The forecast block's dates, for the "delay" section: data end, issue date, and the months
 *  between the last data day and the first / last forecast date. */
export interface ForecastWindow {
  dataEnd: string;
  issueDate: string;
  minMonths: number;
  maxMonths: number;
}

export function forecastWindow(p: PlaceFile | null): ForecastWindow | null {
  const f = p?.forecast;
  if (!f || f.dates.length === 0) return null;
  return {
    dataEnd: f.data_end,
    issueDate: f.issue_date,
    minMonths: monthsOf(days(f.data_end, f.dates[0].d)),
    maxMonths: monthsOf(days(f.data_end, f.dates[f.dates.length - 1].d)),
  };
}

/** Months of data left out in the backtest (days since the last data day, min / max). */
export function backtestLagMonths(a: AccuracyFile | null) {
  const d = a?.log.days_since_data;
  return d ? { min: monthsOf(d.min), max: monthsOf(d.max) } : null;
}

export interface BandRange {
  band: Band;
  from: number | null; // null = from 0
  below: number | null; // null = no upper bound
}

/** Score ranges of the four bands, from index.json `bands` (thresholds never hard-coded). */
export function bandRanges(index: Pick<IndexFile, "bands">): BandRange[] {
  const b = index.bands ?? [];
  return b.map((x, i) => ({ band: x.band, from: i === 0 ? null : b[i - 1].below, below: x.below }));
}
