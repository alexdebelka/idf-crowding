"use client";
// "Vos gares": the stations opened most recently on this device (owner decision, 2026-11-19).
// Kept in localStorage only; nothing leaves the device.
import { useCallback, useEffect, useState } from "react";

export interface SavedPlace {
  id: string;
  name: string;
}

const KEY = "gares";
export const MAX_SAVED = 4;
const EVENT = "apoint:saved";

export function readSaved(): SavedPlace[] {
  try {
    const raw = JSON.parse(window.localStorage.getItem(KEY) ?? "[]");
    if (!Array.isArray(raw)) return [];
    return raw
      .filter((x): x is SavedPlace => !!x && typeof x.id === "string" && typeof x.name === "string")
      .slice(0, MAX_SAVED);
  } catch {
    return [];
  }
}

/** Puts a station first in the list. Call it when a station page opens. */
export function touchSaved(place: SavedPlace): SavedPlace[] {
  const next = [
    { id: place.id, name: place.name },
    ...readSaved().filter((p) => p.id !== place.id),
  ].slice(0, MAX_SAVED);
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
    window.dispatchEvent(new CustomEvent(EVENT, { detail: next }));
  } catch {
    /* storage unavailable: the list just stays empty */
  }
  return next;
}

export function removeSaved(id: string): SavedPlace[] {
  const next = readSaved().filter((p) => p.id !== id);
  try {
    window.localStorage.setItem(KEY, JSON.stringify(next));
    window.dispatchEvent(new CustomEvent(EVENT, { detail: next }));
  } catch {
    /* ignore */
  }
  return next;
}

/** `null` until the device list has been read (first client render). */
export function useSaved(): SavedPlace[] | null {
  const [saved, setSaved] = useState<SavedPlace[] | null>(null);
  const refresh = useCallback(() => setSaved(readSaved()), []);
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
  return saved;
}

/** Same-origin fetch of a Place file (served from the cache when offline). */
export async function fetchPlaceFile<T = unknown>(id: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`/data/places/${encodeURIComponent(id)}.json`, { signal });
  if (!res.ok) throw new Error(`place ${id}: HTTP ${res.status}`);
  return (await res.json()) as T;
}
