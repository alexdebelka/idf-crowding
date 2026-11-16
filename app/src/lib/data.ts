// Build-time data access (server components only). The JSON in public/data is written by
// `idf-score build`; it is the only interface with the Python pipeline.
import { readFileSync } from "node:fs";
import path from "node:path";
import type { IndexFile, PlaceFile } from "./types";

const DATA_DIR = process.env.APP_DATA_DIR ?? path.join(process.cwd(), "public", "data");

function read<T>(rel: string): T {
  const file = path.join(DATA_DIR, rel);
  try {
    return JSON.parse(readFileSync(file, "utf-8")) as T;
  } catch (e) {
    throw new Error(
      `Cannot read ${file}. Run \`make score\` in the repo (or \`npm run fixtures\`). ${e}`,
    );
  }
}

export function getIndex(): IndexFile {
  const idx = read<IndexFile>("index.json");
  if (idx.schema_version !== 1) throw new Error(`unsupported schema_version ${idx.schema_version}`);
  return idx;
}

export function getPlace(id: string): PlaceFile {
  const p = read<PlaceFile>(path.join("places", `${id}.json`));
  if (p.schema_version !== 1) throw new Error(`unsupported schema_version ${p.schema_version}`);
  return p;
}
