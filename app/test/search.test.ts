import { describe, expect, it } from "vitest";
import { normalize, roundEntries, shownHours } from "../src/lib/format";
import { defaultDayType } from "../src/lib/time";
import { buildEntries, search } from "../src/lib/search";
import type { IndexPlace } from "../src/lib/types";

const P = (id: string, name: string, town: string, w: number, lines: string[] = []): IndexPlace => ({
  id,
  name,
  town,
  weekday_entries: w,
  lines: lines.map((n) => ({ id: n, name: n, kind: "metro" })),
});
const places = [
  P("1", "Châtelet – Les Halles", "Paris 1er", 150000, ["1", "4"]),
  P("2", "Les Halles", "Paris 1er", 5000, ["4"]),
  P("3", "Saint-Lazare", "Paris 8e", 120000, ["13"]),
  P("4", "Nanterre - Université", "Nanterre", 20000),
  P("5", "Nanterre - Préfecture", "Nanterre", 30000),
];
const e = buildEntries(places);

describe("search", () => {
  it("is accent- and punctuation-insensitive", () => {
    expect(normalize("Châtelet – Les Halles")).toBe("chatelet les halles");
    expect(search(e, "chatelet")[0].id).toBe("1");
    expect(search(e, "CHÂTELET")[0].id).toBe("1");
  });
  it("ranks prefix matches first, then larger stations", () => {
    expect(search(e, "halles").map((p) => p.id)).toEqual(["1", "2"]);
    expect(search(e, "les h").map((p) => p.id)).toEqual(["2", "1"]);
    expect(search(e, "nanterre").map((p) => p.id)).toEqual(["5", "4"]);
  });
  it("matches token prefixes in any order and towns or lines", () => {
    expect(search(e, "laz st")).toEqual([]);
    expect(search(e, "lazare saint")[0].id).toBe("3");
    expect(search(e, "13").map((p) => p.id)).toEqual(["3"]);
  });
  it("returns nothing for an empty query", () => {
    expect(search(e, "  ")).toEqual([]);
  });
});

describe("format", () => {
  it("rounds entries without false precision", () => {
    expect([roundEntries(42), roundEntries(456), roundEntries(12345)]).toEqual([40, 460, 12300]);
  });
  it("shows 05:00 to 01:00 only", () => {
    const rows = Array.from({ length: 24 }, (_, h) => ({ h, expected_entries: 0, score: 0, band: "quiet" as const }));
    expect(shownHours(rows).map((r) => r.h)).toEqual([0, 1, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]);
  });
  it("guesses the day type from the weekday", () => {
    expect(defaultDayType("2026-11-14")).toBe("SAHV");
    expect(defaultDayType("2026-11-15")).toBe("DIJFP");
    expect(defaultDayType("2026-11-12")).toBe("JOHV");
  });
});
