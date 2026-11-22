// Next departures at a Place, from the PRIM "Prochains passages" answer (SIRI Lite,
// stop-monitoring). Pure functions shared by the Worker (worker/index.ts), the station screen
// and the tests. Design: docs/adr/0004-next-departures-worker.md.

/** One line and destination, with the next departure times (ISO 8601, soonest first). */
export interface DepartureRow {
  line: string; // line id as in the Place file, e.g. "C01374"
  dest: string;
  times: string[];
  atStop: boolean; // the first vehicle is at the platform
}

/** What /api/next/<place id> answers. `now` is the server clock when the list was built. */
export interface DeparturesAnswer {
  status: "ok" | "off" | "quota" | "error";
  now: string;
  rows: DepartureRow[];
}

export const MAX_TIMES = 2; // times kept per line and destination, like a platform screen
export const HORIZON_MS = 60 * 60_000; // nothing further than an hour ahead
const GRACE_MS = 30_000; // a departure this far in the past is still "at the platform"

type Json = Record<string, unknown>;
const obj = (v: unknown): Json => (v && typeof v === "object" ? (v as Json) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
/** SIRI Lite writes text as "x", { value: "x" } or [{ value: "x" }]. */
function text(v: unknown): string {
  if (typeof v === "string") return v.trim();
  if (Array.isArray(v)) return text(v[0]);
  const o = obj(v);
  return typeof o.value === "string" ? o.value.trim() : "";
}

/** "STIF:Line::C01374:" -> "C01374". */
export function lineIdOf(ref: string): string | null {
  const m = /:Line::([A-Za-z0-9]+):/.exec(ref);
  return m ? m[1] : null;
}

/**
 * Rows for the given lines from one or several stop-monitoring answers.
 * Kept: a known line, a destination, a time between now and now + 1 h, not cancelled, and not a
 * train that ends here. Rows are ordered by first departure.
 */
export function parseStopMonitoring(answers: unknown[], lineIds: string[], nowMs: number): DepartureRow[] {
  const wanted = new Set(lineIds);
  const found = new Map<string, { line: string; dest: string; visits: { t: number; iso: string; atStop: boolean }[] }>();
  for (const answer of answers) {
    const deliveries = arr(obj(obj(obj(answer).Siri).ServiceDelivery).StopMonitoringDelivery);
    for (const delivery of deliveries) {
      for (const visit of arr(obj(delivery).MonitoredStopVisit)) {
        const journey = obj(obj(visit).MonitoredVehicleJourney);
        const line = lineIdOf(text(journey.LineRef));
        if (!line || !wanted.has(line)) continue;
        const call = obj(journey.MonitoredCall);
        const status = `${text(call.DepartureStatus)} ${text(call.ArrivalStatus)}`.toLowerCase();
        if (status.includes("cancel")) continue;
        const dest = text(journey.DestinationName) || text(call.DestinationDisplay);
        if (!dest || dest === text(call.StopPointName)) continue;
        const iso =
          text(call.ExpectedDepartureTime) || text(call.ExpectedArrivalTime) || text(call.AimedDepartureTime);
        const t = Date.parse(iso);
        if (!Number.isFinite(t) || t < nowMs - GRACE_MS || t > nowMs + HORIZON_MS) continue;
        const key = `${line}|${dest.toLowerCase()}`;
        const row = found.get(key) ?? { line, dest, visits: [] };
        if (!row.visits.some((v) => v.t === t)) {
          row.visits.push({ t, iso: new Date(t).toISOString(), atStop: call.VehicleAtStop === true });
        }
        found.set(key, row);
      }
    }
  }
  const rows = Array.from(found.values()).map((r) => {
    r.visits.sort((a, b) => a.t - b.t);
    const kept = r.visits.slice(0, MAX_TIMES);
    return { line: r.line, dest: r.dest, times: kept.map((v) => v.iso), atStop: kept[0].atStop, first: kept[0].t };
  });
  rows.sort((a, b) => a.first - b.first || a.line.localeCompare(b.line) || a.dest.localeCompare(b.dest));
  return rows.map(({ line, dest, times, atStop }) => ({ line, dest, times, atStop }));
}

/** Whole minutes until `iso`, never negative; null when the time cannot be read. */
export function minutesUntil(iso: string, nowMs: number): number | null {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return null;
  return Math.max(0, Math.floor((t - nowMs) / 60_000));
}

/** Rows that still have a time ahead of `nowMs` (the list ages between two refreshes). */
export function stillAhead(rows: DepartureRow[], nowMs: number): DepartureRow[] {
  const out: DepartureRow[] = [];
  for (const r of rows) {
    const times = r.times.filter((t) => Date.parse(t) >= nowMs - GRACE_MS);
    if (times.length) out.push({ ...r, times, atStop: times.length === r.times.length && r.atStop });
  }
  return out;
}

export function isAnswer(v: unknown): v is DeparturesAnswer {
  const o = obj(v);
  return typeof o.status === "string" && typeof o.now === "string" && Array.isArray(o.rows);
}
