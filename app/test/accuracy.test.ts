// accuracy.json (schemas/accuracy.v1.schema.json), the place.v2 `accuracy` field, and the
// helpers the method page uses.
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import { describe, expect, it } from "vitest";
import {
  type AccuracyFile,
  accuracySpread,
  accuracyTiles,
  backtestLagMonths,
  bandRanges,
  forecastWindow,
  monthsOf,
  parseAccuracy,
} from "../src/lib/accuracy";
import type { IndexFile, PlaceFile } from "../src/lib/types";

const SCHEMAS = path.resolve(__dirname, "../../schemas");
const FIXTURES = path.resolve(__dirname, "fixtures");
const REAL = path.resolve(__dirname, "../public/data");
const load = (f: string) => JSON.parse(readFileSync(f, "utf-8"));

function validators() {
  const ajv = new Ajv2020({ allErrors: true, strict: false });
  addFormats(ajv);
  for (const n of ["place.v1", "place.v2", "accuracy.v1"])
    ajv.addSchema(load(path.join(SCHEMAS, `${n}.schema.json`)), `${n}.schema.json`);
  return {
    accuracy: ajv.getSchema("accuracy.v1.schema.json")!,
    place: ajv.getSchema("place.v1.schema.json")!,
    place2: ajv.getSchema("place.v2.schema.json")!,
  };
}

const fixture = () => load(path.join(FIXTURES, "accuracy.json")) as AccuracyFile;

describe("accuracy.json contract", () => {
  it("fixture validates", () => {
    const v = validators();
    expect(v.accuracy(fixture()), JSON.stringify(v.accuracy.errors)).toBe(true);
  });

  it.skipIf(!existsSync(path.join(REAL, "accuracy.json")))("public/data validates", () => {
    const v = validators();
    const a = load(path.join(REAL, "accuracy.json"));
    expect(v.accuracy(a), JSON.stringify(v.accuracy.errors)).toBe(true);
  });

  it("rejects an unknown tile, a negative error and a coverage above 1", () => {
    const v = validators();
    expect(v.accuracy({ ...fixture(), tiles: { best_station: 1 } })).toBe(false);
    expect(v.accuracy({ ...fixture(), tiles: { station_wape_pct: -1 } })).toBe(false);
    expect(v.accuracy({ ...fixture(), tiles: { band: { level: 0.8, coverage: 1.2 } } })).toBe(
      false,
    );
  });

  it("place.v2 accepts accuracy (object or null), place.v1 does not", () => {
    const v = validators();
    const p = load(path.join(FIXTURES, "places/71264.json")) as PlaceFile;
    const v2 = {
      ...p,
      schema_version: 2,
      forecast: { issue_date: "2026-11-18", data_end: "2026-06-30", dates: [] },
      accuracy: { wape_pct: 8.4, n_days: 391 },
    };
    expect(v.place2(v2), JSON.stringify(v.place2.errors)).toBe(true);
    expect(v.place2({ ...v2, accuracy: null })).toBe(true);
    expect(v.place2({ ...v2, accuracy: { wape_pct: -1, n_days: 391 } })).toBe(false);
    expect(v.place2({ ...v2, accuracy: { wape_pct: 8.4 } })).toBe(false);
    expect(v.place({ ...p, accuracy: { wape_pct: 8.4, n_days: 391 } })).toBe(false);
  });
});

describe("method page helpers", () => {
  it("parses the file, and null without it or for another version", () => {
    const text = readFileSync(path.join(FIXTURES, "accuracy.json"), "utf-8");
    expect(parseAccuracy(text)?.schema_version).toBe(1);
    expect(parseAccuracy(null)).toBeNull();
    expect(parseAccuracy("{not json")).toBeNull();
    expect(parseAccuracy(JSON.stringify({ ...fixture(), schema_version: 2 }))).toBeNull();
  });

  it("tiles in mockup order, missing ones left out", () => {
    const a = fixture();
    a.tiles = {
      special_days: { wape_pct: 13.3, season: 2025, n_rows: 4972 },
      station_wape_pct: 10.1,
      band: { level: 0.8, coverage: 0.806 },
    };
    expect(accuracyTiles(a)).toEqual([
      { kind: "station", pct: 10.1 },
      { kind: "band", inTen: 8 },
      { kind: "special", pct: 13.3, season: 2025 },
    ]);
    expect(accuracyTiles(null)).toEqual([]);
  });

  it("spread needs both figures", () => {
    const a = fixture();
    expect(accuracySpread(a)?.minDays).toBe(a.min_days);
    a.places.p90_pct = null;
    expect(accuracySpread(a)).toBeNull();
  });

  it("band ranges come from index.json", () => {
    const idx = load(path.join(FIXTURES, "index.json")) as IndexFile;
    const r = bandRanges(idx);
    expect(r.map((x) => [x.from, x.below])).toEqual([
      [null, 40],
      [40, 70],
      [70, 100],
      [100, null],
    ]);
    expect(bandRanges({})).toEqual([]);
  });

  it("months between the last data day and the forecast dates", () => {
    expect(monthsOf(142)).toBe(5);
    expect(monthsOf(225)).toBe(7);
    const p = {
      forecast: {
        issue_date: "2026-11-18",
        data_end: "2026-06-30",
        dates: [{ d: "2026-11-19" }, { d: "2027-02-10" }],
      },
    } as unknown as PlaceFile;
    expect(forecastWindow(p)).toEqual({
      dataEnd: "2026-06-30",
      issueDate: "2026-11-18",
      minMonths: 5,
      maxMonths: 7,
    });
    expect(forecastWindow(null)).toBeNull();
    expect(backtestLagMonths(fixture())).toEqual({ min: 4, max: 6 });
  });
});
