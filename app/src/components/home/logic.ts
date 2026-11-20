// Pure logic of the home screen (tested in test/home.test.ts).
import type { CommonStrings } from "@/lib/i18n/common";
import { tileFact } from "@/lib/sentences";
import { recentOnly } from "@/lib/favourites";
import { MAX_SAVED, type SavedPlace } from "@/lib/saved";
import { type BandRule, dayView, nowFacts } from "@/lib/state";
import { serviceNow } from "@/lib/time";
import type { Band, IndexPlace, PlaceFile } from "@/lib/types";

export const BIG_COUNT = 3;

/** The largest stations by weekday entries (the home when no station has been opened yet). */
export function largestPlaces(places: IndexPlace[], n = BIG_COUNT): SavedPlace[] {
  return [...places]
    .filter((p) => (p.weekday_entries ?? 0) > 0)
    .sort((a, b) => (b.weekday_entries ?? 0) - (a.weekday_entries ?? 0) || a.name.localeCompare(b.name))
    .slice(0, n)
    .map((p) => ({ id: p.id, name: p.name }));
}

export type HomeSection = { kind: "favourites" | "recent" | "big"; stations: SavedPlace[] };

/** Sections of the home: favourites, then recent stations that are not favourites; the largest
 *  stations only when the device has neither. */
export function homeSections(
  favourites: SavedPlace[],
  recent: SavedPlace[],
  big: SavedPlace[],
): HomeSection[] {
  const out: HomeSection[] = [];
  if (favourites.length) out.push({ kind: "favourites", stations: favourites });
  const rest = recentOnly(recent, favourites, MAX_SAVED);
  if (rest.length) out.push({ kind: "recent", stations: rest });
  if (!out.length && big.length) out.push({ kind: "big", stations: big });
  return out;
}

export interface TileState {
  name: string;
  band: Band;
  ground: "signal" | "nuit";
  headline: string;
  fact: string;
}

/** What a tile says about a station at `now` (Paris clock, operating day). Null when the file
 *  has no usable day. */
export function tileState(
  file: PlaceFile,
  now: Date,
  rules: BandRule[],
  t: CommonStrings,
): TileState | null {
  const sn = serviceNow(now);
  const view = dayView(file, sn.date);
  if (!view) return null;
  const f = nowFacts(view.scores, sn.hour, rules);
  return {
    name: file.place.name,
    band: f.band,
    ground: f.ground,
    headline: t.headline[f.band],
    fact: tileFact(t, f),
  };
}

/** Key that changes when the Paris hour (or operating date) changes: tiles refresh on it. */
export const hourKey = (now: Date): string => {
  const s = serviceNow(now);
  return `${s.date}T${s.hour}`;
};

/** The station screens link to `/#recherche`: the field takes focus. */
export const wantsSearchFocus = (hash: string): boolean => hash.replace(/^#/, "") === "recherche";

/** Next index in a list of `n` results for an arrow key; -1 means "none highlighted". */
export function moveActive(current: number, n: number, key: "ArrowDown" | "ArrowUp"): number {
  if (n <= 0) return -1;
  if (key === "ArrowDown") return current < 0 || current >= n - 1 ? 0 : current + 1;
  return current <= 0 ? n - 1 : current - 1;
}

export const stationHref = (id: string) => `/p/${encodeURIComponent(id)}/`;
