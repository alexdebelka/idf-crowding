// Pure logic of the station screens: date parameter, chart marks, crowd layouts, notes.
// No React, no DOM: tested in test/station.test.ts.
import type { BarMark, ChartVariant, LegendItem } from "@/components/shared/BarChart";
import { fullCrowd, rng, type CrowdRow, type Person, type Zone } from "@/lib/crowd";
import type { CommonStrings } from "@/lib/i18n/common";
import type { DayFacts, NowFacts } from "@/lib/state";
import { isIsoDate } from "@/lib/time";
import type { Band, PlaceAccuracy, PlaceFile } from "@/lib/types";

export type Layout = "phone" | "tablet" | "computer";

/** Same breakpoints as globals.css: phone < 700 px, tablet 700–1179 px, computer >= 1180 px. */
export const layoutOf = (width: number): Layout =>
  width >= 1180 ? "computer" : width >= 700 ? "tablet" : "phone";

// ---- Date parameter (?d=YYYY-MM-DD) ----

/** The chosen date of the URL, or null for the "now" screen: missing, malformed, today, past,
 *  or not one of the Place's forecast dates. `today` is the operating date. */
export function chosenDate(raw: string | null | undefined, today: string, available: string[]): string | null {
  if (!isIsoDate(raw)) return null;
  if (raw <= today) return null;
  return available.includes(raw) ? raw : null;
}

/** Reads `d` from a query string ("?d=2026-12-24"). */
export function dateParam(search: string): string | null {
  return new URLSearchParams(search).get("d");
}

/** Query string for a date (empty for the "now" screen); other parameters are kept. */
export function withDate(search: string, date: string | null): string {
  const p = new URLSearchParams(search);
  if (date) p.set("d", date);
  else p.delete("d");
  const s = p.toString();
  return s ? `?${s}` : "";
}

/** Limits of the native date picker: today to the last forecast date. Null without forecast. */
export function pickerRange(today: string, available: string[]): { min: string; max: string } | null {
  const ahead = available.filter((d) => d > today);
  if (!ahead.length) return null;
  return { min: today, max: ahead[ahead.length - 1] };
}

// ---- Chart marks and legends ----

export function nowMarks(f: NowFacts): Partial<Record<number, BarMark>> {
  const marks: Partial<Record<number, BarMark>> = {};
  if (!f.offHours) marks[f.hour] = "now";
  if (f.ground === "nuit" && f.calmerHour != null) marks[f.calmerHour] = "calmer";
  return marks;
}

export function dayMarks(f: DayFacts): Partial<Record<number, BarMark>> {
  const marks: Partial<Record<number, BarMark>> = {};
  for (const h of f.busiest) marks[h] = "busiest";
  for (const h of f.calmest) marks[h] = "calmest";
  return marks;
}

/** Legend items for the marks actually drawn (the legend never names a missing mark). */
export function legendFor(marks: Partial<Record<number, BarMark>>, t: CommonStrings): LegendItem[] {
  const present = new Set(Object.values(marks));
  const all: LegendItem[] = [
    { mark: "now", label: t.legendNow },
    { mark: "calmer", label: t.legendCalmer },
    { mark: "busiest", label: t.legendBusiest },
    { mark: "calmest", label: t.legendCalmest },
  ];
  return all.filter((it) => present.has(it.mark));
}

export const nowVariant = (f: NowFacts): ChartVariant => (f.ground === "nuit" ? "full" : "calm");

/** Phone chart: scroll offset that opens on the current hour with two hours before it. */
export function scrollToHour(hour: number, hours: number[], step = 36): number {
  const i = hours.indexOf(hour);
  return i < 0 ? 0 : Math.max(0, (i - 2) * step);
}

// ---- Per-station accuracy (owner, 2026-11-19: at least 180 scored days) ----

export const MIN_ACCURACY_DAYS = 180;

export function shownAccuracy(place: Pick<PlaceFile, "accuracy">): PlaceAccuracy | null {
  const a = place.accuracy;
  if (!a || !Number.isFinite(a.wape_pct) || a.n_days < MIN_ACCURACY_DAYS) return null;
  return a;
}

// ---- Crowds (design spec, section 6 "People") ----

/** A layer of people drawn in its own SVG of `width` × `height`. */
export interface CrowdLayer {
  rows: CrowdRow[];
  width: number;
  height: number;
  /** "bottom": the SVG sits on the bottom of its band (phone, tablet); "top": under the chart. */
  anchor: "top" | "bottom";
  /** Smallest band height that still shows every figure (only empty space above is cut). */
  minVisible: number;
}

export interface Rabbit {
  /** Distance from the right edge and the bottom of the band, height of the mark. */
  right: number;
  bottom: number;
  height: number;
}

export interface CalmScene {
  /** Computer only: people behind the bars (coordinates from the top of the chart). */
  back: CrowdLayer | null;
  front: CrowdLayer;
  rabbit: Rabbit;
}

const RABBIT_RATIO = 100 / 134;
const rabbitSpan = (width: number, r: Rabbit, margin: number): [number, number] => {
  const x1 = width - r.right;
  return [x1 - r.height * RABBIT_RATIO - margin, x1 + margin];
};

/** Calm platform: few people, placed irregularly, one overlapping pair, rabbit bottom right.
 *  "moderate" draws more people than "quiet", still irregular. `space` is the height left
 *  for the band under the content (phone, tablet): the people move up or down to fit it. */
export function calmScene(layout: Layout, band: Band, width: number, seed: number, space?: number): CalmScene {
  const more = band === "moderate";
  if (layout === "phone") {
    // Short of room, the far row goes first, then the rabbit shrinks (170 px as drawn).
    const h = clamp(space ?? 420, 200, 420);
    const rabbit = { right: Math.max(16, width - 207 - 127), bottom: 44, height: clamp(h - 70, 130, 170) };
    const avoid = [rabbitSpan(width, rabbit, 6)];
    // Far row: as drawn (270 px above the bottom), else at the top of the band while it still
    // stands behind the near row's heads.
    const farY = Math.max(14, h - 270);
    const rows = [
      farY + 45 <= h - 184 + 4 ? spread(zone(-6, width + 6, farY, 0.63, 1.5, 1, more ? 5 : 3, false, avoid), seed) : null,
      spread(zone(10, width - 10, h - 184, 0.95, 0, 4, more ? 4 : 3, true, avoid), seed + 1),
    ].filter((r): r is CrowdRow => r != null);
    return { back: null, front: { rows, width, height: h, anchor: "bottom", minVisible: h }, rabbit };
  }
  if (layout === "tablet") {
    const h = clamp(space ?? 470, 260, 470);
    const rabbit = { right: Math.max(24, width - 460 - 187), bottom: 57, height: clamp(h - 90, 180, 250) };
    const avoid = [rabbitSpan(width, rabbit, 8)];
    const farY = Math.max(18, h - 311);
    const rows = [
      farY + 57 <= h - 214 + 4 ? spread(zone(-10, width + 10, farY, 0.8, 1.5, 1, more ? 6 : 4, false, avoid), seed) : null,
      spread(zone(40, width - 20, h - 214, 1.24, 0, 4, more ? 3 : 2, true, avoid), seed + 1),
    ].filter((r): r is CrowdRow => r != null);
    return { back: null, front: { rows, width, height: h, anchor: "bottom", minVisible: h }, rabbit };
  }
  // Computer (DesktopGo, the reference): 10 behind the chart in two soft layers (6 far, 4
  // nearer), 7 in front at three depths, uneven gaps; the front band sits under the hour labels.
  const rabbit = { right: Math.max(72, width - 1188 - 84), bottom: 10, height: 112 };
  const avoid = [rabbitSpan(width, rabbit, 10)];
  const back = [
    spread(zone(90, width - 90, 56, 0.42, 2.5, 0, more ? 8 : 6), seed),
    spread(zone(150, width - 150, 112, 0.56, 1.2, 1, more ? 5 : 4), seed + 1),
  ];
  const front = [
    spread(zone(40, width - 40, 13, 0.74, 0.6, 3, more ? 4 : 3, false, avoid), seed + 2),
    spread(zone(160, width - 100, 22, 0.98, 0, 4, more ? 3 : 2, true, avoid), seed + 3),
    spread(zone(420, width - 60, 33, 1.25, 0, 5, 2, false, avoid), seed + 4),
  ];
  return {
    back: { rows: back, width, height: 200, anchor: "top", minVisible: 200 },
    front: { rows: front, width, height: 130, anchor: "top", minVisible: 130 },
    rabbit,
  };
}

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** Irregular but spread placement: one figure per slot of the zone, at a random point of the
 *  slot (so gaps are uneven and nobody clusters), outside the kept-free spans. With `pair`,
 *  one figure gets a neighbour shoulder to shoulder (the count stays the same). */
export function spread(z: Zone, seed: number): CrowdRow {
  const rand = rng(seed);
  const w = 22 * z.scale;
  const free = (x: number) => !(z.avoid ?? []).some(([a, b]) => x + w / 2 > a && x - w / 2 < b);
  const apart = (x: number, xs: number[]) => xs.every((o) => Math.abs(o - x) >= w * 1.8);
  const n = z.pair && z.count >= 2 ? z.count - 1 : z.count;
  const slot = (z.x1 - z.x0) / n;
  const xs: number[] = [];
  for (let i = 0; i < n; i += 1) {
    let placed = false;
    for (let k = 0; k < 24 && !placed; k += 1) {
      const x = z.x0 + slot * (i + 0.12 + rand() * 0.76);
      if (free(x) && apart(x, xs)) {
        xs.push(x);
        placed = true;
      }
    }
    // Slot taken by a kept-free span: anywhere free instead.
    for (let k = 0; k < 200 && !placed; k += 1) {
      const x = z.x0 + rand() * (z.x1 - z.x0);
      if (free(x) && apart(x, xs)) {
        xs.push(x);
        placed = true;
      }
    }
  }
  if (z.pair && z.count >= 2 && xs.length) {
    const order = xs.map((_, i) => i).sort(() => rand() - 0.5);
    for (const i of order) {
      const side = rand() < 0.5 ? -1 : 1;
      const x = xs[i] + side * w * 0.8;
      if (free(x) && x > z.x0 - w && x < z.x1 + w) {
        xs.push(x);
        break;
      }
    }
  }
  xs.sort((a, b) => a - b);
  const people: Person[] = xs.map((x) => ({ x, y: z.y + (rand() - 0.5) * 10 * z.scale, scale: z.scale }));
  return { depth: z.depth, blur: z.blur, people };
}

function zone(
  x0: number,
  x1: number,
  y: number,
  scale: number,
  blur: number,
  depth: number,
  count: number,
  pair = false,
  avoid: [number, number][] = [],
): Zone {
  return { x0, x1, y, scale, blur, depth, count, pair, avoid };
}

/** Full platform: receding rows, denser when very busy. No rabbit. `space` as in calmScene. */
export function fullScene(
  layout: Layout,
  band: "busy" | "very_busy",
  width: number,
  seed: number,
  space?: number,
): CrowdLayer {
  const density = band;
  // Phone and tablet: short of room, the whole crowd is drawn smaller (never cut mid-body).
  if (layout === "phone") {
    const k = clamp((space ?? 400) / 400, 0.6, 1);
    const rows = fullCrowd({ width, height: 400 * k, density, seed, scale: k });
    const h = Math.round(400 * k);
    return { rows, width, height: h, anchor: "bottom", minVisible: h - topOf(rows) };
  }
  if (layout === "tablet") {
    const k = clamp((space ?? 470) / 470, 0.6, 1);
    const rows = fullCrowd({ width, height: 520 * k, density, seed, scale: 1.3 * k });
    const h = Math.round(470 * k);
    return { rows, width, height: h, anchor: "bottom", minVisible: h - topOf(rows) };
  }
  // Computer (DesktopWait): the two far rows stand behind the bars, the others under the labels.
  const rows = fullCrowd({ width, height: 352, density, seed, scale: 0.9 });
  return { rows, width, height: 256, anchor: "top", minVisible: 256 };
}

/** Highest point drawn (head top minus blur), in SVG units. */
export function topOf(rows: CrowdRow[]): number {
  let top = Infinity;
  for (const r of rows) for (const p of r.people) top = Math.min(top, p.y - 8 * p.scale - r.blur * 2);
  return Number.isFinite(top) ? Math.max(0, Math.floor(top)) : 0;
}

/** Lowest point drawn (feet), in SVG units. */
export function bottomOf(rows: CrowdRow[]): number {
  let bottom = 0;
  for (const r of rows) for (const p of r.people) bottom = Math.max(bottom, p.y + 11 * p.scale + 60 * p.scale);
  return bottom;
}

export const countPeople = (rows: CrowdRow[]) => rows.reduce((n, r) => n + r.people.length, 0);

/** Computer, full: how far the crowd band reaches up behind the chart (the two far rows). */
export const COMPUTER_FULL_OVERLAP = 94;

/** French typography: no line break inside "16 h" or "10 %", nor before ":". */
export const nb = (text: string) =>
  text.replace(/(\d) (h|%)(?=[\s.,;:!?)]|$)/g, "$1\u00a0$2").replace(/ ([:;!?])/g, "\u00a0$1");
