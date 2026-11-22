// Worker of the site: answers /api/next/<place id> (next departures, in real time) and hands
// every other request to the static assets. wrangler.jsonc only runs it for /api/*, so pages
// and data stay plain static asset requests. Design: docs/adr/0004-next-departures-worker.md.
//
// The visitor's browser only talks to this site. The Worker asks the PRIM "Prochains passages"
// API (Île-de-France Mobilités, ODbL) with a key kept as a secret (PRIM_API_KEY); nothing about
// the visitor is sent along. Answers are kept in the edge cache so that many visitors on one
// station cost one PRIM request per TTL.
import { parseStopMonitoring, type DeparturesAnswer } from "../src/lib/departures";

interface Fetcher {
  fetch(input: Request | string): Promise<Response>;
}
interface Env {
  ASSETS: Fetcher;
  PRIM_API_KEY?: string;
}
interface Ctx {
  waitUntil(p: Promise<unknown>): void;
}

const PRIM_URL = "https://prim.iledefrance-mobilites.fr/marketplace/stop-monitoring";
const PLACE_ID = /^[A-Za-z0-9_-]{1,32}$/;
const TTL_OK = 30; // seconds an answer is shared
const TTL_ERROR = 60; // PRIM failed: do not retry at once
const TTL_QUOTA = 600; // PRIM said the daily or per-second quota is spent: back off
const MAX_STOPS = 3; // stop areas asked per Place
const TIMEOUT_MS = 8000;

function json(body: DeparturesAnswer | { status: "not_found" }, status: number, ttl: number): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": ttl > 0 ? `public, max-age=${ttl}` : "no-store",
      "x-content-type-options": "nosniff",
      "referrer-policy": "no-referrer",
    },
  });
}

const empty = (status: DeparturesAnswer["status"]): DeparturesAnswer => ({
  status,
  now: new Date().toISOString(),
  rows: [],
});

async function departures(id: string, request: Request, env: Env): Promise<Response> {
  if (!env.PRIM_API_KEY) return json(empty("off"), 200, 0);

  // The Place file gives the stop areas and the lines; an unknown id costs no PRIM request.
  const placeRes = await env.ASSETS.fetch(new URL(`/data/places/${id}.json`, request.url).toString());
  if (!placeRes.ok) return json({ status: "not_found" }, 404, TTL_ERROR);
  const place =
    ((await placeRes.json()) as { place?: { station_ids?: unknown; stop_areas?: unknown; lines?: unknown } })
      .place ?? {};
  // stop_areas is only written when the real-time ZdC differ from the Counting points
  const areas = Array.isArray(place.stop_areas) ? place.stop_areas : place.station_ids;
  const stops = (Array.isArray(areas) ? areas : [])
    .filter((s): s is number | string => /^[0-9]{1,9}$/.test(String(s)))
    .slice(0, MAX_STOPS);
  const lines = (Array.isArray(place.lines) ? place.lines : [])
    .map((l) => (l && typeof l === "object" ? String((l as { id?: unknown }).id ?? "") : ""))
    .filter(Boolean);
  if (!stops.length || !lines.length) return json(empty("ok"), 200, TTL_OK);

  const answers: unknown[] = [];
  let quota = false;
  await Promise.all(
    stops.map(async (stop) => {
      const url = `${PRIM_URL}?MonitoringRef=${encodeURIComponent(`STIF:StopArea:SP:${stop}:`)}`;
      try {
        const res = await fetch(url, {
          headers: { apikey: env.PRIM_API_KEY as string, accept: "application/json" },
          signal: AbortSignal.timeout(TIMEOUT_MS),
        });
        if (res.status === 429) quota = true;
        else if (res.ok) answers.push(await res.json());
      } catch {
        /* counted as a failure below */
      }
    }),
  );
  if (!answers.length) return quota ? json(empty("quota"), 200, TTL_QUOTA) : json(empty("error"), 200, TTL_ERROR);

  const now = Date.now();
  const body: DeparturesAnswer = {
    status: "ok",
    now: new Date(now).toISOString(),
    rows: parseStopMonitoring(answers, lines, now),
  };
  return json(body, 200, TTL_OK);
}

const worker = {
  async fetch(request: Request, env: Env, ctx: Ctx): Promise<Response> {
    const url = new URL(request.url);
    if (!url.pathname.startsWith("/api/")) return env.ASSETS.fetch(request);

    const m = /^\/api\/next\/([^/]+)\/?$/.exec(url.pathname);
    if (!m || !PLACE_ID.test(m[1])) return json({ status: "not_found" }, 404, TTL_ERROR);
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response(null, { status: 405, headers: { allow: "GET, HEAD" } });
    }

    const cache = (caches as unknown as { default: Cache }).default;
    const key = new Request(`${url.origin}/api/next/${m[1]}`);
    const hit = await cache.match(key);
    if (hit) return hit;
    const res = await departures(m[1], request, env);
    if (res.headers.get("cache-control") !== "no-store") ctx.waitUntil(cache.put(key, res.clone()));
    return res;
  },
};

export default worker;
