import { normalize } from "./format";
import type { IndexPlace } from "./types";

export interface SearchEntry {
  place: IndexPlace;
  name: string; // normalized
  words: string[];
  extra: string; // normalized town + line names
}

export function buildEntries(places: IndexPlace[]): SearchEntry[] {
  return places.map((p) => {
    const name = normalize(p.name);
    return {
      place: p,
      name,
      words: name.split(" "),
      extra: normalize(`${p.town ?? ""} ${p.lines.map((l) => l.name).join(" ")}`),
    };
  });
}

/** Accent-insensitive search. Rank: name starts with query > a word starts with each token >
 *  name contains query > town/line match; ties by weekday entries (larger stations first). */
export function search(entries: SearchEntry[], query: string, limit = 20): IndexPlace[] {
  const q = normalize(query);
  if (!q) return [];
  const tokens = q.split(" ");
  const scored: [number, SearchEntry][] = [];
  for (const e of entries) {
    let rank = -1;
    if (e.name.startsWith(q)) rank = 0;
    else if (tokens.every((t) => e.words.some((w) => w.startsWith(t)))) rank = 1;
    else if (e.name.includes(q)) rank = 2;
    else if (tokens.every((t) => e.words.some((w) => w.startsWith(t)) || e.extra.includes(t)))
      rank = 3;
    if (rank >= 0) scored.push([rank, e]);
  }
  scored.sort(
    (a, b) =>
      a[0] - b[0] ||
      (b[1].place.weekday_entries ?? 0) - (a[1].place.weekday_entries ?? 0) ||
      a[1].name.localeCompare(b[1].name),
  );
  return scored.slice(0, limit).map(([, e]) => e.place);
}
