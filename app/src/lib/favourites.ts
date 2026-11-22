"use client";
// Favourite stations ("Vos gares"): chosen by the person with the star on a station page.
// Kept in localStorage only; nothing leaves the device. The recent list (saved.ts) is separate.
import { useCallback, useEffect, useState } from "react";
import { notifyFavourites } from "@/components/pwa/register";
import type { SavedPlace } from "./saved";

const KEY = "favoris";
export const MAX_FAVOURITES = 12;
const EVENT = "apoint:favourites";
const ID = /^[A-Za-z0-9_-]{1,32}$/;

/* ---------- pure functions (tested in test/favourites.test.ts) ---------- */

/** Valid entries of a stored value, in order, no duplicate id, at most `max`. */
export function parseFavourites(raw: unknown, max = MAX_FAVOURITES): SavedPlace[] {
  if (!Array.isArray(raw)) return [];
  const seen = new Set<string>();
  const out: SavedPlace[] = [];
  for (const x of raw) {
    if (!x || typeof x.id !== "string" || typeof x.name !== "string" || !ID.test(x.id)) continue;
    if (seen.has(x.id)) continue;
    seen.add(x.id);
    out.push({ id: x.id, name: x.name });
    if (out.length >= max) break;
  }
  return out;
}

export type ToggleResult = { list: SavedPlace[]; result: "added" | "removed" | "full" };

/** Adds the station at the end, or removes it. A full list is left unchanged. */
export function toggleIn(list: SavedPlace[], place: SavedPlace, max = MAX_FAVOURITES): ToggleResult {
  if (list.some((p) => p.id === place.id)) {
    return { list: list.filter((p) => p.id !== place.id), result: "removed" };
  }
  if (list.length >= max) return { list, result: "full" };
  return { list: [...list, { id: place.id, name: place.name }], result: "added" };
}

/** Moves a station one place up (-1) or down (+1). Unchanged at either end or when absent. */
export function moveIn(list: SavedPlace[], id: string, delta: -1 | 1): SavedPlace[] {
  const i = list.findIndex((p) => p.id === id);
  const j = i + delta;
  if (i < 0 || j < 0 || j >= list.length) return list;
  const out = list.slice();
  [out[i], out[j]] = [out[j], out[i]];
  return out;
}

/** Recent stations that are not favourites, at most `max`. */
export function recentOnly(recent: SavedPlace[], favourites: SavedPlace[], max: number): SavedPlace[] {
  const fav = new Set(favourites.map((p) => p.id));
  return recent.filter((p) => !fav.has(p.id)).slice(0, max);
}

/* ---------- device storage ---------- */

export function readFavourites(): SavedPlace[] {
  try {
    return parseFavourites(JSON.parse(window.localStorage.getItem(KEY) ?? "[]"));
  } catch {
    return [];
  }
}

function write(list: SavedPlace[]): boolean {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(list));
  } catch {
    return false;
  }
  window.dispatchEvent(new CustomEvent(EVENT, { detail: list }));
  notifyFavourites(list.map((p) => p.id));
  return true;
}

/** Adds or removes a station. "error" when the device refuses to store it. */
export function toggleFavourite(place: SavedPlace): ToggleResult["result"] | "error" {
  const { list, result } = toggleIn(readFavourites(), place);
  if (result === "full") return result;
  return write(list) ? result : "error";
}

export function removeFavourite(id: string): void {
  write(readFavourites().filter((p) => p.id !== id));
}

export function moveFavourite(id: string, delta: -1 | 1): void {
  const list = readFavourites();
  const next = moveIn(list, id, delta);
  if (next !== list) write(next);
}

/** `null` until the device list has been read (first client render). */
export function useFavourites(): SavedPlace[] | null {
  const [favs, setFavs] = useState<SavedPlace[] | null>(null);
  const refresh = useCallback(() => setFavs(readFavourites()), []);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- hydrate from storage once
    refresh();
    window.addEventListener(EVENT, refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener(EVENT, refresh);
      window.removeEventListener("storage", refresh);
    };
  }, [refresh]);
  return favs;
}
