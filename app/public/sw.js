/* à point: service worker. Plain JavaScript, no library, same-origin GET only.
   Design and update behaviour: docs/adr/0003-pwa-offline-and-caching.md.
   The routing decisions are pure functions at the top, exposed to the unit tests at the bottom. */
"use strict";

/* Bump VERSION when this file's caching layout or logic changes: every cache of this
   worker with another version is deleted on activate. A new deploy of the site does not
   need a bump (pages are network first, hashed files never change). */
const VERSION = "v3";
const CACHE_SHELL = "apoint-shell-" + VERSION;
const CACHE_STATIONS = "apoint-stations-" + VERSION;
const CACHE_DATA = "apoint-data-" + VERSION;
const CACHE_PREFIX = "apoint-";

const MAX_STATIONS = 8; // the home shows the 4 most recent; keep a few more
const MAX_STATIC_ENTRIES = 150; // files under /_next/static/ kept in the shell cache (oldest dropped)
const NETWORK_TIMEOUT_MS = 4000; // network first: after this, a cached copy wins if there is one
const META_PATH = "/__sw/recent-stations"; // synthetic key, inside the stations cache
const FAV_PATH = "/__sw/favourite-stations"; // same, for the favourites (never evicted)
const MAX_FAVOURITES = 12; // as in src/lib/favourites.ts

const PRECACHE_PAGES = ["/", "/a-propos/"];
const PRECACHE_FILES = [
  "/fonts/onest-latin-wght-normal.woff2",
  "/fonts/onest-latin-ext-wght-normal.woff2",
  "/brand/mark.svg",
  "/brand/intro.js",
  "/brand/favicon.svg",
  // full payloads read by a client-side link that was not prefetched
  "/index.txt",
  "/a-propos/index.txt",
];

/* ---------- pure functions ---------- */

const STATION_ID = /^[A-Za-z0-9_-]{1,32}$/;

/** Station id found in a path: /p/<id>/..., /p/<id> or /data/places/<id>.json; else null. */
function stationIdOf(pathname) {
  let m = /^\/p\/([^/]+)(?:\/|$)/.exec(pathname);
  if (!m) m = /^\/data\/places\/([^/]+)\.json$/.exec(pathname);
  if (!m) return null;
  let id;
  try {
    id = decodeURIComponent(m[1]);
  } catch {
    return null;
  }
  return STATION_ID.test(id) ? id : null;
}

/** Cache key of a request: the URL without query and hash (static files; the Next.js
    payloads carry a throw-away ?_rsc= value). */
function cacheKeyOf(url) {
  return url.origin + url.pathname;
}

/**
 * Which strategy for which request.
 * req = { method, mode, hasRange }.
 * strategy: "ignore" | "navigate" | "network-first" | "cache-first" | "swr"
 * cache: "shell" | "stations" | "data"; stationId and opened only for station entries
 * ("opened" = the visitor opened that station by navigating to its page. Client-side opening is
 * reported by the page with a message, see stationIdFromMessage; a prefetched payload or the
 * Place file read by the home for its tiles does not count.)
 */
function routeFor(url, req, origin) {
  const ignore = { strategy: "ignore" };
  if (url.origin !== origin) return ignore;
  if (req.method !== "GET" || req.hasRange) return ignore;
  const p = url.pathname;
  if (p === "/sw.js" || p === "/manifest.webmanifest" || p === "/_headers") return ignore;
  if (p.startsWith("/cdn-cgi/") || p.startsWith("/__sw/")) return ignore;

  const id = stationIdOf(p);
  if (p.startsWith("/data/")) {
    if (id) return { strategy: "swr", cache: "stations", stationId: id, opened: false };
    return { strategy: "swr", cache: "data" };
  }
  if (req.mode === "navigate") {
    if (id) return { strategy: "navigate", cache: "stations", stationId: id, opened: true };
    return { strategy: "navigate", cache: "shell" };
  }
  if (p.startsWith("/_next/static/") || p.startsWith("/fonts/")) {
    return { strategy: "cache-first", cache: "shell" };
  }
  if (p.startsWith("/brand/") || p.startsWith("/icons/")) {
    return { strategy: "swr", cache: "shell" };
  }
  if (p.endsWith(".txt")) {
    // Next.js payload files read by client-side navigation (/p/<id>/__next....txt, /index.txt...)
    if (id) return { strategy: "network-first", cache: "stations", stationId: id, opened: false };
    return { strategy: "network-first", cache: "shell" };
  }
  return ignore;
}

/** The page tells the worker which station it shows: { type: "station-opened", id }. */
function stationIdFromMessage(data) {
  if (!data || data.type !== "station-opened" || typeof data.id !== "string") return null;
  return STATION_ID.test(data.id) ? data.id : null;
}

/** The page sends the favourite stations: { type: "favourites", ids: [...] }. Null if invalid. */
function favouritesFromMessage(data) {
  if (!data || data.type !== "favourites" || !Array.isArray(data.ids)) return null;
  const out = [];
  for (const id of data.ids) {
    if (typeof id === "string" && STATION_ID.test(id) && !out.includes(id)) out.push(id);
    if (out.length >= MAX_FAVOURITES) break;
  }
  return out;
}

/** Recent stations list after the user opened `id`: most recent first, no duplicate. */
function touchRecent(recent, id) {
  return [id].concat(recent.filter((x) => x !== id));
}

/**
 * Eviction. `recent` is most recent first, `cachedIds` the station ids that have entries in
 * the cache. Keeps the `max` most recent; purges every cached id that is not kept (the oldest
 * ones, and ids that were only prefetched and never opened). `pinned` (favourites) are never
 * purged and do not count towards `max`.
 */
function planPrune(recent, cachedIds, max, pinned) {
  const kept = recent.slice(0, max);
  const keepSet = new Set(kept.concat(pinned || []));
  const purge = [];
  for (const id of cachedIds) if (!keepSet.has(id) && !purge.includes(id)) purge.push(id);
  return { recent: kept, purge: purge };
}

/** Keys to delete so that at most `max` remain (keys in insertion order, oldest first). */
function staticEvictions(keys, max) {
  return keys.slice(0, Math.max(0, keys.length - max));
}

/** Only complete same-origin 200 responses are stored: never opaque, failed, redirected or no-store. */
function isCacheable(res) {
  if (!res || res.type !== "basic" || res.status !== 200 || !res.ok || res.redirected) return false;
  const cc = res.headers && res.headers.get ? res.headers.get("cache-control") || "" : "";
  return !/no-store/i.test(cc);
}

/** Files under /_next/static/ named in a page or payload text. */
function staticUrlsIn(text) {
  const out = new Set();
  const re = /\/_next\/static\/[A-Za-z0-9_\-./%~$]+?\.(?:js|css|woff2)/g;
  let m;
  while ((m = re.exec(text))) out.add(m[0]);
  return Array.from(out);
}

/* ---------- cache helpers ---------- */

const CACHE_NAME = { shell: CACHE_SHELL, stations: CACHE_STATIONS, data: CACHE_DATA };

function openCache(kind) {
  return caches.open(CACHE_NAME[kind]);
}

let queue = Promise.resolve(); // serialises the recent-list read-modify-write
function serial(task) {
  const run = queue.then(task, task);
  queue = run.catch(() => {});
  return run;
}

async function readRecent(cache) {
  const hit = await cache.match(self.location.origin + META_PATH);
  if (!hit) return [];
  try {
    const list = await hit.json();
    return Array.isArray(list) ? list.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

async function readFavourites(cache) {
  const hit = await cache.match(self.location.origin + FAV_PATH);
  if (!hit) return [];
  try {
    return favouritesFromMessage({ type: "favourites", ids: await hit.json() }) || [];
  } catch {
    return [];
  }
}

function writeFavourites(cache, list) {
  return cache.put(
    self.location.origin + FAV_PATH,
    new Response(JSON.stringify(list), { headers: { "content-type": "application/json" } }),
  );
}

function writeRecent(cache, list) {
  return cache.put(
    self.location.origin + META_PATH,
    new Response(JSON.stringify(list), { headers: { "content-type": "application/json" } }),
  );
}

async function store(kind, key, res) {
  const cache = await openCache(kind);
  await cache.put(key, res);
  if (kind === "shell" && key.indexOf("/_next/static/") !== -1) {
    const keys = (await cache.keys()).map((r) => r.url);
    const staticKeys = keys.filter((u) => u.indexOf("/_next/static/") !== -1);
    for (const u of staticEvictions(staticKeys, MAX_STATIC_ENTRIES)) await cache.delete(u);
  }
}

async function fetchAndStore(kind, url, opts) {
  const res = await fetch(url, opts || { cache: "reload" });
  if (!isCacheable(res)) return null;
  const copy = res.clone();
  await store(kind, url, copy);
  return res;
}

/** A station was opened: move it to the front, evict the oldest, keep its page for offline. */
function trackStation(id) {
  return serial(async () => {
    const cache = await openCache("stations");
    await prune(cache, touchRecent(await readRecent(cache), id), await readFavourites(cache));
  }).then(() => ensureStationPage(id));
}

/** The favourites changed: store them, purge what is no longer kept, cache the new ones. */
function setFavourites(ids) {
  return serial(async () => {
    const cache = await openCache("stations");
    await writeFavourites(cache, ids);
    await prune(cache, await readRecent(cache), ids);
  }).then(async () => {
    for (const id of ids) await ensureStationPage(id);
  });
}

async function prune(cache, recent, favourites) {
  const cachedIds = [];
  for (const r of await cache.keys()) {
    const cid = stationIdOf(new URL(r.url).pathname);
    if (cid) cachedIds.push(cid);
  }
  const plan = planPrune(recent, cachedIds, MAX_STATIONS, favourites);
  await writeRecent(cache, plan.recent);
  for (const r of await cache.keys()) {
    const cid = stationIdOf(new URL(r.url).pathname);
    if (cid && plan.purge.includes(cid)) await cache.delete(r);
  }
}

/** What an opened station needs offline: its page (with the files it names), its full payload
    (client-side links) and its Place file (the home reads it for the tile). Fetched once, only
    what is missing: opening by a client-side link loads none of them. */
async function ensureStationPage(id) {
  const cache = await openCache("stations");
  const base = self.location.origin;
  const page = base + "/p/" + encodeURIComponent(id) + "/";
  const wanted = [page, page + "index.txt", base + "/data/places/" + encodeURIComponent(id) + ".json"];
  for (const url of wanted) {
    if (await cache.match(url)) continue;
    try {
      const res = await fetchAndStore("stations", url);
      if (res && url === page) await cacheStaticFiles(await res.text());
    } catch {
      /* best effort: it is cached on first use anyway */
    }
  }
}

async function cacheStaticFiles(text) {
  const cache = await openCache("shell");
  for (const path of staticUrlsIn(text)) {
    const url = self.location.origin + path;
    if (await cache.match(url)) continue;
    try {
      await fetchAndStore("shell", url);
    } catch {
      /* best effort: it is cached on first use anyway */
    }
  }
}

/* ---------- strategies ---------- */

/** Stores a network response in the background, then tracks the station if it was opened. */
function background(event, route, key, netPromise) {
  const job = netPromise
    .then(async (res) => {
      if (!isCacheable(res)) return;
      await store(route.cache, key, res.clone());
      if (route.stationId && route.opened) await trackStation(route.stationId);
    })
    .catch(() => {});
  event.waitUntil(job);
}

function timeout(ms, value) {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms));
}

async function networkFirst(event, route, key) {
  const cache = await openCache(route.cache);
  const cached = await cache.match(key);
  const net = fetch(event.request);
  background(event, route, key, net.then((r) => r.clone()));
  if (!cached) return net;
  const answer = net.then((res) => (res.status >= 500 ? cached : res)).catch(() => cached);
  return Promise.race([answer, timeout(NETWORK_TIMEOUT_MS, cached)]);
}

async function staleWhileRevalidate(event, route, key) {
  const cache = await openCache(route.cache);
  const cached = await cache.match(key);
  const net = fetch(new Request(event.request, { cache: "no-cache" }));
  background(event, route, key, net.then((r) => r.clone()));
  if (cached) {
    if (route.stationId && route.opened) event.waitUntil(trackStation(route.stationId).catch(() => {}));
    net.catch(() => {});
    return cached;
  }
  return net;
}

async function cacheFirst(event, route, key) {
  const cache = await openCache(route.cache);
  const cached = await cache.match(key);
  if (cached) return cached;
  const net = fetch(event.request);
  background(event, route, key, net.then((r) => r.clone()));
  return net;
}

/** Offline and nothing cached for this page: the home, if it is cached. */
async function navigationFallback() {
  const cache = await openCache("shell");
  if (await cache.match(self.location.origin + "/")) {
    return Response.redirect(self.location.origin + "/", 302);
  }
  return null;
}

async function handle(event, route) {
  const key = cacheKeyOf(new URL(event.request.url));
  try {
    if (route.strategy === "navigate" || route.strategy === "network-first") {
      return await networkFirst(event, route, key);
    }
    if (route.strategy === "swr") return await staleWhileRevalidate(event, route, key);
    return await cacheFirst(event, route, key);
  } catch (err) {
    if (route.strategy === "navigate") {
      const fallback = await navigationFallback();
      if (fallback) return fallback;
    }
    throw err;
  }
}

/* ---------- lifecycle ---------- */

async function precache() {
  const cache = await openCache("shell");
  const home = await fetch("/", { cache: "reload" });
  if (!isCacheable(home)) throw new Error("home not cacheable");
  const homeText = await home.clone().text();
  await store("shell", self.location.origin + "/", home);
  const assets = new Set(staticUrlsIn(homeText));
  for (const page of PRECACHE_PAGES.slice(1)) {
    try {
      const res = await fetch(page, { cache: "reload" });
      if (!isCacheable(res)) continue;
      staticUrlsIn(await res.clone().text()).forEach((u) => assets.add(u));
      await store("shell", self.location.origin + page, res);
    } catch {
      /* best effort */
    }
  }
  const urls = PRECACHE_FILES.concat(Array.from(assets));
  for (const path of urls) {
    try {
      if (!(await cache.match(self.location.origin + path))) {
        await fetchAndStore("shell", self.location.origin + path);
      }
    } catch {
      /* best effort */
    }
  }
}

self.addEventListener("install", (event) => {
  event.waitUntil(precache().then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const current = [CACHE_SHELL, CACHE_STATIONS, CACHE_DATA];
      for (const name of await caches.keys()) {
        if (name.startsWith(CACHE_PREFIX) && !current.includes(name)) await caches.delete(name);
      }
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("message", (event) => {
  const id = stationIdFromMessage(event.data);
  if (id) event.waitUntil(trackStation(id).catch(() => {}));
  const favs = favouritesFromMessage(event.data);
  if (favs) event.waitUntil(setFavourites(favs).catch(() => {}));
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const route = routeFor(
    new URL(req.url),
    { method: req.method, mode: req.mode, hasRange: req.headers.has("range") },
    self.location.origin,
  );
  if (route.strategy === "ignore") return;
  event.respondWith(handle(event, route));
});

/* Unit tests evaluate this file with a stub `self` that has `__swTest`. */
if (typeof self.__swTest === "function") {
  self.__swTest({
    VERSION, MAX_STATIONS, MAX_STATIC_ENTRIES, NETWORK_TIMEOUT_MS,
    MAX_FAVOURITES, stationIdOf, stationIdFromMessage, favouritesFromMessage, cacheKeyOf, routeFor, touchRecent, planPrune, staticEvictions, isCacheable, staticUrlsIn,
  });
}
