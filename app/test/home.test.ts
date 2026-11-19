// Pure logic of the home screen: largest-stations fallback, tile state, install decisions, hash.
import { describe, expect, it } from "vitest";
import { hourKey, largestPlaces, moveActive, stationHref, tileState, wantsSearchFocus } from "../src/components/home/logic";
import { STRINGS } from "../src/lib/i18n";
import { installMode, isIos, laterActive, shouldAutoOffer, LATER_DAYS } from "../src/lib/install";
import { DEFAULT_BANDS } from "../src/lib/state";
import { HOUR_ORDER } from "../src/lib/time";
import type { IndexPlace, PlaceFile } from "../src/lib/types";

const t = STRINGS.fr.common;

const place = (id: string, name: string, entries: number | null): IndexPlace => ({
  id,
  name,
  weekday_entries: entries,
  lines: [],
});

describe("largest stations (home without a station opened)", () => {
  const places = [
    place("a", "Petite", 1000),
    place("b", "Grande", 90000),
    place("c", "Moyenne", 40000),
    place("d", "Sans chiffre", null),
    place("e", "Autre grande", 70000),
  ];
  it("takes the three largest by weekday entries", () => {
    expect(largestPlaces(places).map((p) => p.id)).toEqual(["b", "e", "c"]);
  });
  it("ignores stations without entries and keeps id and name only", () => {
    expect(largestPlaces(places, 10).map((p) => p.id)).not.toContain("d");
    expect(largestPlaces(places, 1)).toEqual([{ id: "b", name: "Grande" }]);
  });
  it("returns fewer when the index is small", () => {
    expect(largestPlaces([place("x", "X", 5)])).toHaveLength(1);
    expect(largestPlaces([])).toEqual([]);
  });
});

/** A Place file whose typical weekday has `score(h)` at each clock hour. */
function file(score: (h: number) => number): PlaceFile {
  const hours = HOUR_ORDER.map((h) => ({ h, expected_entries: 0, score: score(h), band: "quiet" as const }));
  return {
    schema_version: 1,
    generated_at: "2026-11-11T00:00:00Z",
    data_period: { start: "2025-07-01", end: "2026-06-30" },
    place: { id: "1", name: "Test – Gare", station_ids: [], lines: [] },
    reference_level: 100,
    day_types: {
      JOHV: {
        hours,
        daily_entries: 0,
        n_days: 100,
        low_confidence: false,
        best_slots: { quietest: [], around_peaks: [] },
      },
    },
    attribution: { source: "", source_url: "", license: "", license_url: "" },
  };
}

describe("tile state", () => {
  // Peak 8 h–9 h, quiet from 10 h, busy again 17 h–19 h.
  const f = file((h) => (h === 8 || h === 9 ? 130 : h === 17 || h === 18 ? 80 : h === 10 ? 60 : 20));
  it("is busy at the morning peak (Nuit) and speaks of entries", () => {
    // 2026-11-19 07:30 UTC = 08 h 30 in Paris (a Thursday).
    const s = tileState(f, new Date("2026-11-19T07:30:00Z"), DEFAULT_BANDS, t)!;
    expect(s.band).toBe("very_busy");
    expect(s.ground).toBe("nuit");
    expect(s.headline).toBe("Très chargé.");
    expect(s.fact).toBe("Moitié moins vers 10\u00a0h.");
    expect(s.fact).not.toMatch(/monde/);
  });
  it("is calm at midday (Signal), with the next busy hour", () => {
    const s = tileState(f, new Date("2026-11-19T11:00:00Z"), DEFAULT_BANDS, t)!;
    expect(s.ground).toBe("signal");
    expect(s.headline).toBe("Calme.");
    expect(s.fact).toBe("Peu d’entrées jusqu’à 17\u00a0h environ.");
  });
  it("speaks English with the English strings", () => {
    const s = tileState(f, new Date("2026-11-19T07:30:00Z"), DEFAULT_BANDS, STRINGS.en.common)!;
    expect(s.headline).toBe("Very busy.");
  });
  it("returns null for a file without any usable day", () => {
    const empty = { ...f, day_types: {} };
    expect(tileState(empty, new Date("2026-11-19T07:30:00Z"), DEFAULT_BANDS, t)).toBeNull();
  });
  it("changes its refresh key with the Paris hour only", () => {
    expect(hourKey(new Date("2026-11-19T07:05:00Z"))).toBe(hourKey(new Date("2026-11-19T07:55:00Z")));
    expect(hourKey(new Date("2026-11-19T07:55:00Z"))).not.toBe(hourKey(new Date("2026-11-19T08:05:00Z")));
  });
});

describe("install decisions", () => {
  it("hides the button when already installed", () => {
    expect(installMode({ standalone: true, ios: true, hasPromptEvent: true })).toBe("none");
  });
  it("offers the browser prompt when the event was captured", () => {
    expect(installMode({ standalone: false, ios: false, hasPromptEvent: true })).toBe("prompt");
  });
  it("shows the Share-sheet hint on iOS (no prompt event)", () => {
    expect(installMode({ standalone: false, ios: true, hasPromptEvent: false })).toBe("ios");
  });
  it("offers nothing where install is impossible", () => {
    expect(installMode({ standalone: false, ios: false, hasPromptEvent: false })).toBe("none");
  });
  it("detects iPhone, iPad and iPadOS posing as a Mac", () => {
    expect(isIos("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)", "iPhone", 5)).toBe(true);
    expect(isIos("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", "MacIntel", 5)).toBe(true);
    expect(isIos("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", "MacIntel", 0)).toBe(false);
    expect(isIos("Mozilla/5.0 (Linux; Android 14)", "Linux armv8l", 5)).toBe(false);
  });
  it("remembers 'Plus tard' for a limited time", () => {
    const day = 86_400_000;
    const now = 1_800_000_000_000;
    expect(laterActive(null, now)).toBe(false);
    expect(laterActive(now - 2 * day, now)).toBe(true);
    expect(laterActive(now - (LATER_DAYS + 1) * day, now)).toBe(false);
  });
  it("auto-offers only to returning visitors who did not say 'later'", () => {
    const now = 1_800_000_000_000;
    expect(shouldAutoOffer("prompt", true, null, now)).toBe(true);
    expect(shouldAutoOffer("prompt", false, null, now)).toBe(false);
    expect(shouldAutoOffer("prompt", true, now - 1000, now)).toBe(false);
    expect(shouldAutoOffer("none", true, null, now)).toBe(false);
  });
});

describe("search field helpers", () => {
  it("focuses the field for #recherche only", () => {
    expect(wantsSearchFocus("#recherche")).toBe(true);
    expect(wantsSearchFocus("recherche")).toBe(true);
    expect(wantsSearchFocus("")).toBe(false);
    expect(wantsSearchFocus("#autre")).toBe(false);
  });
  it("moves through the results with wrap-around", () => {
    expect(moveActive(-1, 3, "ArrowDown")).toBe(0);
    expect(moveActive(2, 3, "ArrowDown")).toBe(0);
    expect(moveActive(-1, 3, "ArrowUp")).toBe(2);
    expect(moveActive(0, 3, "ArrowUp")).toBe(2);
    expect(moveActive(1, 3, "ArrowUp")).toBe(0);
    expect(moveActive(0, 0, "ArrowDown")).toBe(-1);
  });
  it("links to the station page", () => {
    expect(stationHref("71264")).toBe("/p/71264/");
  });
});
