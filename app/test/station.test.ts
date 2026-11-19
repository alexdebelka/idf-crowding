// Pure logic of the station screens: date parameter, chart marks, crowd layouts, notes.
import { describe, expect, it } from "vitest";
import {
  bottomOf,
  calmScene,
  chosenDate,
  COMPUTER_FULL_OVERLAP,
  countPeople,
  dateParam,
  dayMarks,
  fullScene,
  layoutOf,
  legendFor,
  nb,
  spread,
  nowMarks,
  pickerRange,
  scrollToHour,
  shownAccuracy,
  topOf,
  withDate,
  type Layout,
} from "../src/components/station/logic";
import { seedOf } from "../src/lib/crowd";
import { STRINGS } from "../src/lib/i18n";
import { dayFacts, nowFacts } from "../src/lib/state";
import { CHART_HOURS, HOUR_ORDER } from "../src/lib/time";
import type { Band } from "../src/lib/types";

const day = (m: Record<number, number>) => HOUR_ORDER.map((h) => m[h] ?? 0);
const t = STRINGS.fr.common;
const AVAILABLE = ["2026-11-19", "2026-11-20", "2026-12-24", "2027-02-10"];
const WIDTH: Record<Layout, number> = { phone: 390, tablet: 820, computer: 1440 };

describe("date parameter", () => {
  it("accepts only a forecast date after today", () => {
    expect(chosenDate("2026-12-24", "2026-11-19", AVAILABLE)).toBe("2026-12-24");
    expect(chosenDate("2026-11-19", "2026-11-19", AVAILABLE)).toBeNull(); // today = now screen
    expect(chosenDate("2026-11-18", "2026-11-19", AVAILABLE)).toBeNull(); // past
    expect(chosenDate("2026-12-25", "2026-11-19", AVAILABLE)).toBeNull(); // no forecast
    expect(chosenDate("2027-03-01", "2026-11-19", AVAILABLE)).toBeNull(); // beyond the range
    for (const bad of [null, undefined, "", "24/12/2026", "2026-13-01", "2026-12-24T10:00", "x"]) {
      expect(chosenDate(bad, "2026-11-19", AVAILABLE)).toBeNull();
    }
  });
  it("reads and writes the query string", () => {
    expect(dateParam("?d=2026-12-24")).toBe("2026-12-24");
    expect(dateParam("")).toBeNull();
    expect(withDate("", "2026-12-24")).toBe("?d=2026-12-24");
    expect(withDate("?d=2026-12-24", null)).toBe("");
    expect(withDate("?x=1&d=2026-12-24", "2027-01-01")).toBe("?x=1&d=2027-01-01");
  });
  it("limits the picker to today and the last forecast date", () => {
    expect(pickerRange("2026-11-19", AVAILABLE)).toEqual({ min: "2026-11-19", max: "2027-02-10" });
    expect(pickerRange("2027-02-10", AVAILABLE)).toBeNull();
    expect(pickerRange("2026-11-19", [])).toBeNull();
  });
  it("picks the layout from the width", () => {
    expect([390, 699, 700, 1179, 1180, 1920].map(layoutOf)).toEqual([
      "phone", "phone", "tablet", "tablet", "computer", "computer",
    ]);
  });
});

describe("chart marks", () => {
  const scores = day({ 7: 60, 8: 120, 9: 95, 10: 58, 11: 45, 16: 80, 17: 110, 18: 90, 19: 50 });
  it("full: now and the next calmer hour", () => {
    const m = nowMarks(nowFacts(scores, 8));
    expect(m).toEqual({ 8: "now", 10: "calmer" });
    expect(legendFor(m, t).map((x) => x.label)).toEqual([t.legendNow, t.legendCalmer]);
  });
  it("calm: now only", () => {
    const m = nowMarks(nowFacts(scores, 12));
    expect(m).toEqual({ 12: "now" });
    expect(legendFor(m, t)).toHaveLength(1);
  });
  it("no mark outside the chart hours", () => {
    expect(nowMarks(nowFacts(scores, 2))).toEqual({});
  });
  it("date: busiest and calmest", () => {
    const s = day({ 7: 70, 8: 121, 9: 102, 10: 67, 11: 63, 12: 77, 13: 79, 14: 86, 15: 105, 16: 130, 17: 146, 18: 124, 19: 82, 20: 54 });
    const m = dayMarks(dayFacts(s));
    expect(m).toEqual({ 8: "busiest", 16: "busiest", 17: "busiest", 18: "busiest", 10: "calmest", 11: "calmest" });
    expect(legendFor(m, t).map((x) => x.mark)).toEqual(["busiest", "calmest"]);
  });
  it("opens the phone chart on the current hour", () => {
    expect(scrollToHour(5, CHART_HOURS)).toBe(0);
    expect(scrollToHour(8, CHART_HOURS)).toBe(36);
    expect(scrollToHour(2, CHART_HOURS)).toBe(0);
  });
});

describe("typography", () => {
  it("keeps hours, percentages and colons with their number", () => {
    expect(nb("Plus chargé de 16 h à 19 h.")).toBe("Plus chargé de 16\u00a0h à 19\u00a0h.");
    expect(nb("Pour cette gare : écart moyen de 7,9 %.")).toBe("Pour cette gare\u00a0: écart moyen de 7,9\u00a0%.");
    expect(nb("About 10% fewer around 10:00.")).toBe("About 10% fewer around 10:00.");
  });
});

describe("per-station accuracy", () => {
  it("is shown from 180 scored days", () => {
    expect(shownAccuracy({ accuracy: { wape_pct: 8.4, n_days: 180 } })).toEqual({ wape_pct: 8.4, n_days: 180 });
    expect(shownAccuracy({ accuracy: { wape_pct: 8.4, n_days: 179 } })).toBeNull();
    expect(shownAccuracy({ accuracy: null })).toBeNull();
    expect(shownAccuracy({})).toBeNull();
  });
});

describe("crowds", () => {
  const seed = seedOf("71264");
  const layouts: Layout[] = ["phone", "tablet", "computer"];
  const calmBands: Band[] = ["quiet", "moderate"];

  it("calm draws fewer people than full, moderate more than quiet", () => {
    for (const l of layouts) {
      const w = WIDTH[l];
      const n = (b: Band) => {
        const s = calmScene(l, b, w, seed);
        return countPeople(s.front.rows) + (s.back ? countPeople(s.back.rows) : 0);
      };
      const busy = countPeople(fullScene(l, "busy", w, seed).rows);
      const veryBusy = countPeople(fullScene(l, "very_busy", w, seed).rows);
      expect(n("quiet")).toBeLessThan(n("moderate"));
      expect(n("moderate") * 2).toBeLessThan(busy);
      expect(busy).toBeLessThan(veryBusy);
    }
  });

  it("computer, calm: 10 behind the chart and 7 in front when quiet", () => {
    const s = calmScene("computer", "quiet", 1440, seed);
    expect(s.back && countPeople(s.back.rows)).toBe(10);
    expect(countPeople(s.front.rows)).toBe(7);
    expect(s.front.rows.map((r) => r.blur)).toEqual([0.6, 0, 0]);
  });

  it("keeps the rabbit's place free", () => {
    for (const l of layouts) {
      for (const b of calmBands) {
        for (const w of [WIDTH[l], WIDTH[l] + 150]) {
          const s = calmScene(l, b, w, seed);
          const r = s.rabbit;
          const x1 = w - r.right;
          const x0 = x1 - (r.height * 100) / 134;
          const rabbitTop = s.front.height - r.bottom - r.height;
          for (const row of s.front.rows) {
            for (const p of row.people) {
              const half = 11 * p.scale;
              const feet = p.y + 71 * p.scale;
              if (feet < rabbitTop) continue; // far row, entirely above the rabbit
              expect(p.x + half <= x0 || p.x - half >= x1).toBe(true);
            }
          }
          expect(rabbitTop).toBeGreaterThanOrEqual(0);
        }
      }
    }
  });

  it("people in front stay inside their band, below the chart", () => {
    for (const l of layouts) {
      for (const b of calmBands) {
        const s = calmScene(l, b, WIDTH[l], seed);
        // The band starts under the chart: nothing may reach above its top or below its end.
        expect(topOf(s.front.rows)).toBeGreaterThanOrEqual(0);
        expect(bottomOf(s.front.rows)).toBeLessThanOrEqual(s.front.height);
        // Bottom-anchored bands may shrink to `minVisible`: only empty space is cut.
        expect(s.front.height - topOf(s.front.rows)).toBeLessThanOrEqual(s.front.minVisible + 1);
        if (s.back) {
          // Behind the bars: within the bar area (above the hour labels, 200 px tall).
          expect(topOf(s.back.rows)).toBeGreaterThanOrEqual(0);
          expect(bottomOf(s.back.rows)).toBeLessThanOrEqual(200);
        }
      }
    }
  });

  it("full: only the far rows reach behind the computer chart", () => {
    for (const b of ["busy", "very_busy"] as const) {
      const layer = fullScene("computer", b, 1440, seed);
      for (const row of layer.rows) {
        for (const p of row.people) {
          const headTop = p.y - 8 * p.scale - row.blur * 2;
          // Sharp figures (blur < 3) never stand in the chart area.
          if (row.blur < 3) expect(headTop).toBeGreaterThanOrEqual(COMPUTER_FULL_OVERLAP - 6);
        }
      }
    }
    for (const l of ["phone", "tablet"] as const) {
      const layer = fullScene(l, "very_busy", WIDTH[l], seed);
      expect(layer.minVisible).toBeLessThanOrEqual(layer.height);
      expect(topOf(layer.rows)).toBeGreaterThanOrEqual(layer.height - layer.minVisible);
    }
  });

  it("fits the space left under the content on phone and tablet", () => {
    for (const l of ["phone", "tablet"] as const) {
      for (const space of [120, 260, 300, 380, 900]) {
        for (const b of calmBands) {
          const s = calmScene(l, b, WIDTH[l], seed, space);
          expect(topOf(s.front.rows)).toBeGreaterThanOrEqual(0);
          expect(bottomOf(s.front.rows)).toBeLessThanOrEqual(s.front.height);
          expect(s.front.height - s.rabbit.bottom - s.rabbit.height).toBeGreaterThanOrEqual(0);
        }
        const full = fullScene(l, "very_busy", WIDTH[l], seed, space);
        expect(topOf(full.rows)).toBeGreaterThanOrEqual(0);
        expect(full.height).toBeLessThanOrEqual(l === "phone" ? 400 : 470);
      }
    }
  });

  it("spreads calm people unevenly, never in a cluster", () => {
    for (let k = 0; k < 20; k += 1) {
      const row = spread({ x0: 0, x1: 1440, y: 20, scale: 1, blur: 0, depth: 4, count: 5, pair: true }, k);
      expect(row.people).toHaveLength(5);
      const xs = row.people.map((p) => p.x);
      const gaps = xs.slice(1).map((x, i) => x - xs[i]);
      // exactly one overlapping pair, every other gap wide
      expect(gaps.filter((g) => g < 22 * 1.8)).toHaveLength(1);
      expect(new Set(gaps.map(Math.round)).size).toBe(gaps.length);
    }
  });

  it("is stable for a station and a screen", () => {
    expect(calmScene("phone", "quiet", 390, seed)).toEqual(calmScene("phone", "quiet", 390, seed));
  });
});
