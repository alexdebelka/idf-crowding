import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import type { Metadata } from "next";
import { MethodPage } from "@/components/method/MethodPage";
import { bandRanges, forecastWindow, parseAccuracy } from "@/lib/accuracy";
import { getIndex, getPlace } from "@/lib/data";
import type { PlaceFile } from "@/lib/types";

export const metadata: Metadata = { title: "Comment c’est calculé" };

const DATA_DIR = process.env.APP_DATA_DIR ?? path.join(process.cwd(), "public", "data");

/** accuracy.json if `idf-score build` wrote one (absent in CI: the page hides its figures). */
function readAccuracy() {
  const file = path.join(DATA_DIR, "accuracy.json");
  return parseAccuracy(existsSync(file) ? readFileSync(file, "utf-8") : null);
}

/** The forecast block of the first Place file (every Place shares issue date and data end). */
function firstPlace(ids: string[]): PlaceFile | null {
  if (ids.length === 0) return null;
  try {
    return getPlace(ids[0]);
  } catch {
    return null;
  }
}

export default function AboutPage() {
  const index = getIndex();
  const accuracy = readAccuracy();
  return (
    <MethodPage
      bands={bandRanges(index)}
      dataPeriod={index.data_period}
      accuracy={accuracy}
      forecast={forecastWindow(firstPlace(index.places.map((p) => p.id)))}
    />
  );
}
