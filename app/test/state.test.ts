// Date and state logic behind every screen: Paris clock, operating day, bands, facts, sentences.
import { describe, expect, it } from "vitest";
import { fullCrowd, scatter, seedOf } from "../src/lib/crowd";
import { STRINGS } from "../src/lib/i18n";
import { dayComparison, dayHeadline, nowSummary, tileFact } from "../src/lib/sentences";
import { bandOf, chartHours, dayFacts, dayView, groundOf, nowFacts } from "../src/lib/state";
import { CHART_HOURS, HOUR_ORDER, addDays, hourIndex, parisClock, serviceNow } from "../src/lib/time";
import type { ForecastDate, PlaceFile } from "../src/lib/types";

/** Operating-day array from a clock-hour map. */
const day = (m: Record<number, number>) => HOUR_ORDER.map((h) => m[h] ?? 0);
const t = STRINGS.fr.common;

describe("time", () => {
  it("reads the Paris clock whatever the device zone", () => {
    expect(parisClock(new Date("2026-11-19T07:30:00Z"))).toEqual({ date: "2026-11-19", hour: 8, minute: 30 });
    expect(parisClock(new Date("2026-07-01T22:15:00Z"))).toEqual({ date: "2026-07-02", hour: 0, minute: 15 });
  });
  it("keeps the hours before 04 h in the previous operating day", () => {
    expect(serviceNow(new Date("2026-11-19T00:30:00Z"))).toEqual({ date: "2026-11-18", hour: 1, index: 21 });
    expect(serviceNow(new Date("2026-11-19T03:10:00Z"))).toEqual({ date: "2026-11-19", hour: 4, index: 0 });
  });
  it("orders hours as the Place files do", () => {
    expect(HOUR_ORDER.map(hourIndex)).toEqual([...Array(24).keys()]);
    expect(CHART_HOURS).toHaveLength(20);
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
  });
});

describe("bands and grounds", () => {
  it("maps four bands onto two grounds", () => {
    expect([0, 39, 40, 69, 70, 99, 100, 180].map((s) => bandOf(s))).toEqual([
      "quiet", "quiet", "moderate", "moderate", "busy", "busy", "very_busy", "very_busy",
    ]);
    expect(groundOf("moderate")).toBe("signal");
    expect(groundOf("busy")).toBe("nuit");
  });
});

describe("now facts and sentences", () => {
  const scores = day({ 7: 60, 8: 120, 9: 95, 10: 58, 11: 45, 16: 80, 17: 110, 18: 90, 19: 50 });
  it("full: finds the next calmer hour and how much lower it is", () => {
    const f = nowFacts(scores, 8);
    expect(f).toMatchObject({ band: "very_busy", ground: "nuit", calmerHour: 10, busyFromHour: null });
    expect(f.calmerDrop).toBeCloseTo(1 - 58 / 120, 5);
    expect(nowSummary(t, f)).toBe("Beaucoup d’entrées en ce moment. Moitié moins vers 10\u00a0h.");
    expect(tileFact(t, f)).toBe("Moitié moins vers 10\u00a0h.");
  });
  it("calm: says until when", () => {
    const f = nowFacts(scores, 12);
    expect(f).toMatchObject({ band: "quiet", ground: "signal", busyFromHour: 16, calmerHour: null });
    expect(nowSummary(t, f)).toBe("Peu d’entrées en ce moment, et jusqu’à 16\u00a0h environ.");
    expect(nowSummary(t, nowFacts(scores, 11))).toBe(
      "Entrées modérées en ce moment. Plus d’entrées à partir de 16\u00a0h.",
    );
  });
  it("handles the end of the day and the closed hours", () => {
    expect(nowSummary(t, nowFacts(scores, 20))).toBe(t.nowQuietAllDay);
    expect(nowFacts(scores, 2)).toMatchObject({ offHours: true, band: "quiet" });
    const lateBusy = day({ 22: 90, 23: 85, 0: 80 });
    expect(nowSummary(t, nowFacts(lateBusy, 22))).toBe(t.nowBusyAllDay);
  });
  it("never advises", () => {
    const all = JSON.stringify([STRINGS.fr.common, STRINGS.en.common], (_k, v) =>
      typeof v === "function" ? String(v) : v,
    ).toLowerCase();
    for (const w of ["attendez", "partez", "évitez", "you should", "avoid", "wait"]) {
      expect(all).not.toContain(w);
    }
  });
});

describe("chosen date", () => {
  const scores = day({ 7: 70, 8: 121, 9: 102, 10: 67, 11: 63, 12: 77, 13: 79, 14: 86, 15: 105, 16: 130, 17: 146, 18: 124, 19: 82, 20: 54 });
  it("marks the busiest window and the calmest daytime pair", () => {
    const f = dayFacts(scores);
    expect(f.busiest).toEqual([8, 16, 17, 18]);
    expect(f.busiestWindow).toEqual([16, 19]);
    expect(f.calmest).toEqual([10, 11]);
    expect(dayHeadline(t, f)).toBe("Plus chargé de 16\u00a0h à 19\u00a0h.");
    expect(chartHours(scores)).toHaveLength(20);
  });
  it("is safe on an empty day", () => {
    expect(dayFacts(day({}))).toMatchObject({ busiest: [], busiestWindow: null, calmest: [] });
  });
  it("compares with the typical day of the same day type", () => {
    const d = { day_type: "JOVS", delta_pct: -30, reasons: ["christmas_eve"] } as unknown as ForecastDate;
    expect(dayComparison(t, d)).toBe("Environ 30\u00a0% de moins qu’un jour de semaine de vacances scolaires.");
    expect(dayComparison(t, { ...d, delta_pct: 1 })).toBe("Comme un jour de semaine de vacances scolaires.");
    expect(dayComparison(t, { ...d, delta_pct: null })).toBeNull();
  });
  it("uses the forecast of the date, else the typical week", () => {
    const hours = HOUR_ORDER.map((h) => ({ h, expected_entries: 0, score: h, band: "quiet" as const }));
    const place = {
      day_types: { JOHV: { hours }, DIJFP: { hours: hours.map((r) => ({ ...r, score: 1 })) } },
      forecast: { dates: [{ d: "2026-11-20", day_type: "JOHV", scores: Array(24).fill(7) }] },
    } as unknown as PlaceFile;
    expect(dayView(place, "2026-11-20")).toMatchObject({ source: "forecast", scores: Array(24).fill(7) });
    expect(dayView(place, "2027-06-07")).toMatchObject({ source: "typical", dayType: "JOHV", scores: HOUR_ORDER });
    expect(dayView(place, "2027-06-06")?.scores[0]).toBe(1); // Sunday
    expect(dayView(place, "2027-06-05")?.dayType).toBe("JOHV"); // Saturday profile missing
  });
});

describe("crowd", () => {
  it("is stable for a seed and denser when very busy", () => {
    const a = fullCrowd({ width: 390, density: "very_busy", seed: seedOf("71264") });
    const b = fullCrowd({ width: 390, density: "very_busy", seed: seedOf("71264") });
    const c = fullCrowd({ width: 390, density: "busy", seed: seedOf("71264") });
    const n = (rows: typeof a) => rows.reduce((s, r) => s + r.people.length, 0);
    expect(a).toEqual(b);
    expect(a).toHaveLength(6);
    expect(n(c)).toBeLessThan(n(a) / 2);
  });
  it("scatters calm people irregularly and outside the kept-free spans", () => {
    const row = scatter({ x0: 0, x1: 390, y: 236, scale: 0.95, blur: 0, depth: 4, count: 4, avoid: [[200, 340]] }, 7);
    expect(row.people.length).toBe(4);
    for (const p of row.people) expect(p.x < 200 - 10 || p.x > 340 + 10).toBe(true);
    const gaps = row.people.slice(1).map((p, i) => Math.round(p.x - row.people[i].x));
    expect(new Set(gaps).size).toBeGreaterThan(1);
  });
});

describe("dates in words", () => {
  it("writes the first of the month the French way", async () => {
    const { formatDate, formatDayLong } = await import("../src/lib/i18n");
    expect(formatDate("2025-07-01", "fr")).toBe("1er juillet 2025");
    expect(formatDate("2026-06-30", "fr")).toBe("30 juin 2026");
    expect(formatDate("2026-12-11", "fr")).toBe("11 décembre 2026");
    expect(formatDayLong("2027-01-01", "fr")).toBe("Vendredi 1er janvier");
    expect(formatDate("2025-07-01", "en")).toBe("1 July 2025");
  });
});

describe("launch intro", () => {
  it("plays the end of the scene in about two and a half seconds", async () => {
    const { SPLASH_FROM, SPLASH_SPEED, SPLASH_TO, splashTime } = await import("../src/lib/intro");
    expect(splashTime(0)).toBe(SPLASH_FROM);
    const length = (SPLASH_TO - SPLASH_FROM) / SPLASH_SPEED;
    expect(length).toBeGreaterThan(2);
    expect(length).toBeLessThan(3);
    expect(splashTime(length - 0.01)).toBeLessThan(SPLASH_TO);
    expect(splashTime(length + 0.01)).toBeNull();
  });
});
