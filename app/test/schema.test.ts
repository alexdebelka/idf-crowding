// The JSON contract (schemas/*.v1.schema.json) checked from the TypeScript side.
import { existsSync, readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import Ajv2020 from "ajv/dist/2020";
import addFormats from "ajv-formats";
import { describe, expect, it } from "vitest";
import type { IndexFile, PlaceFile } from "../src/lib/types";

const SCHEMAS = path.resolve(__dirname, "../../schemas");
const load = (f: string) => JSON.parse(readFileSync(f, "utf-8"));

function validators() {
  const ajv = new Ajv2020({ allErrors: true, strict: false });
  addFormats(ajv);
  const place = load(path.join(SCHEMAS, "place.v1.schema.json"));
  const index = load(path.join(SCHEMAS, "index.v1.schema.json"));
  ajv.addSchema(place, "place.v1.schema.json");
  ajv.addSchema(index, "index.v1.schema.json");
  return {
    place: ajv.getSchema("place.v1.schema.json")!,
    index: ajv.getSchema("index.v1.schema.json")!,
  };
}

function check(dir: string) {
  const v = validators();
  const index = load(path.join(dir, "index.json")) as IndexFile;
  expect(v.index(index), JSON.stringify(v.index.errors)).toBe(true);
  const files = readdirSync(path.join(dir, "places")).filter((f) => f.endsWith(".json"));
  expect(files.length).toBe(index.places.length);
  for (const f of files) {
    const p = load(path.join(dir, "places", f)) as PlaceFile;
    expect(v.place(p), `${f}: ${JSON.stringify(v.place.errors)}`).toBe(true);
    expect(p.place.id).toBe(f.replace(/\.json$/, ""));
  }
}

describe("JSON contract v1", () => {
  it("fixtures validate", () => check(path.resolve(__dirname, "fixtures")));

  it("rejects a wrong band and a missing hour", () => {
    const v = validators();
    const p = load(path.resolve(__dirname, "fixtures/places/71264.json"));
    p.day_types.JOHV.hours[0].band = "packed";
    expect(v.place(p)).toBe(false);
    const q = load(path.resolve(__dirname, "fixtures/places/71264.json"));
    q.day_types.JOHV.hours.pop();
    expect(v.place(q)).toBe(false);
  });

  const real = path.resolve(__dirname, "../public/data");
  it.skipIf(!existsSync(path.join(real, "index.json")))("public/data validates", () => check(real));
});
