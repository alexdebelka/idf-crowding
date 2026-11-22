// Routing and eviction decisions of public/sw.js. The file is a plain script: it is evaluated
// in a vm context with a stub `self`, and exposes its pure functions through `self.__swTest`.
import fs from "node:fs";
import vm from "node:vm";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const ORIGIN = "https://apoint.test";

interface Route {
  strategy: string;
  cache?: string;
  stationId?: string;
  opened?: boolean;
}
interface SwApi {
  VERSION: string;
  MAX_STATIONS: number;
  MAX_STATIC_ENTRIES: number;
  NETWORK_TIMEOUT_MS: number;
  stationIdOf(p: string): string | null;
  stationIdFromMessage(d: unknown): string | null;
  cacheKeyOf(u: URL): string;
  routeFor(u: URL, r: { method: string; mode: string; hasRange?: boolean }, origin: string): Route;
  touchRecent(recent: string[], id: string): string[];
  planPrune(recent: string[], cached: string[], max: number, pinned?: string[]): { recent: string[]; purge: string[] };
  favouritesFromMessage(d: unknown): string[] | null;
  MAX_FAVOURITES: number;
  staticEvictions(keys: string[], max: number): string[];
  isCacheable(r: unknown): boolean;
  staticUrlsIn(t: string): string[];
}

function loadSw(): SwApi {
  const file = fileURLToPath(new URL("../public/sw.js", import.meta.url));
  let api: SwApi | undefined;
  const self = {
    addEventListener: () => {},
    location: { origin: ORIGIN },
    __swTest: (x: SwApi) => {
      api = x;
    },
  };
  vm.runInNewContext(fs.readFileSync(file, "utf8"), { self, URL, Response: class {}, Request: class {} });
  if (!api) throw new Error("sw.js did not expose its test API");
  return api;
}

const sw = loadSw();
const route = (path: string, mode = "cors", method = "GET", hasRange = false): Route =>
  // copy out of the vm realm
  JSON.parse(JSON.stringify(sw.routeFor(new URL(ORIGIN + path), { method, mode, hasRange }, ORIGIN)));

describe("service worker constants", () => {
  it("has a version and bounded caches", () => {
    expect(sw.VERSION).toMatch(/^v\d+$/);
    expect(sw.MAX_STATIONS).toBeGreaterThanOrEqual(5); // the home shows 4
    expect(sw.MAX_STATIONS).toBeLessThanOrEqual(20);
    expect(sw.NETWORK_TIMEOUT_MS).toBeGreaterThan(0);
  });
});

describe("stationIdOf", () => {
  it("reads the id from station pages, payloads and data files", () => {
    expect(sw.stationIdOf("/p/71264/")).toBe("71264");
    expect(sw.stationIdOf("/p/71264")).toBe("71264");
    expect(sw.stationIdOf("/p/71264/__next.p.$d$id.__PAGE__.txt")).toBe("71264");
    expect(sw.stationIdOf("/p/71264/index.txt")).toBe("71264");
    expect(sw.stationIdOf("/data/places/71264.json")).toBe("71264");
  });
  it("returns null for anything else", () => {
    for (const p of ["/", "/a-propos/", "/p/", "/p//", "/data/index.json", "/data/places/", "/data/places/a/b.json", "/pp/1/", "/p/%E0%A4%A/", "/p/a b/"]) {
      expect(sw.stationIdOf(p), p).toBeNull();
    }
  });
  it("refuses ids that are not plain", () => {
    expect(sw.stationIdOf("/p/..%2F..%2Fx/")).toBeNull();
    expect(sw.stationIdOf("/p/" + "1".repeat(40) + "/")).toBeNull();
  });
});

describe("stationIdFromMessage", () => {
  it("accepts the page's message and nothing else", () => {
    expect(sw.stationIdFromMessage({ type: "station-opened", id: "71264" })).toBe("71264");
    expect(sw.stationIdFromMessage({ type: "station-opened", id: "../x" })).toBeNull();
    expect(sw.stationIdFromMessage({ type: "station-opened", id: 5 })).toBeNull();
    expect(sw.stationIdFromMessage({ type: "other", id: "1" })).toBeNull();
    expect(sw.stationIdFromMessage(null)).toBeNull();
    expect(sw.stationIdFromMessage("station-opened")).toBeNull();
  });
});

describe("cacheKeyOf", () => {
  it("drops query and hash", () => {
    expect(sw.cacheKeyOf(new URL(ORIGIN + "/p/1/__next._tree.txt?_rsc=abc#x"))).toBe(ORIGIN + "/p/1/__next._tree.txt");
    expect(sw.cacheKeyOf(new URL(ORIGIN + "/?q=gare#recherche"))).toBe(ORIGIN + "/");
  });
});

describe("routeFor: which strategy for which URL", () => {
  it("navigations are network first", () => {
    expect(route("/", "navigate")).toEqual({ strategy: "navigate", cache: "shell" });
    expect(route("/a-propos/", "navigate")).toEqual({ strategy: "navigate", cache: "shell" });
    expect(route("/p/71264/", "navigate")).toEqual({ strategy: "navigate", cache: "stations", stationId: "71264", opened: true });
    expect(route("/inconnu/", "navigate").strategy).toBe("navigate");
  });
  it("hashed build files are cache first, fonts too", () => {
    expect(route("/_next/static/chunks/abc.js", "no-cors")).toEqual({ strategy: "cache-first", cache: "shell" });
    expect(route("/_next/static/chunks/abc.css", "no-cors").strategy).toBe("cache-first");
    expect(route("/fonts/onest-latin-wght-normal.woff2", "cors")).toEqual({ strategy: "cache-first", cache: "shell" });
  });
  it("brand files and icons are stale-while-revalidate", () => {
    expect(route("/brand/mark.svg", "no-cors")).toEqual({ strategy: "swr", cache: "shell" });
    expect(route("/icons/icon-192.png", "no-cors").strategy).toBe("swr");
  });
  it("data is stale-while-revalidate; a station file belongs to its station", () => {
    expect(route("/data/index.json")).toEqual({ strategy: "swr", cache: "data" });
    expect(route("/data/places/71264.json")).toEqual({ strategy: "swr", cache: "stations", stationId: "71264", opened: false });
  });
  it("Next.js payload files are network first; a prefetch is not 'opened'", () => {
    expect(route("/p/71264/__next.p.$d$id.__PAGE__.txt")).toEqual({ strategy: "network-first", cache: "stations", stationId: "71264", opened: false });
    expect(route("/p/71264/__next._tree.txt?_rsc=zz").strategy).toBe("network-first");
    expect(route("/index.txt")).toEqual({ strategy: "network-first", cache: "shell" });
    expect(route("/a-propos/__next.a-propos.__PAGE__.txt")).toEqual({ strategy: "network-first", cache: "shell" });
  });
  it("leaves alone: other origins, non-GET, ranges, the worker, the manifest, anything unknown", () => {
    expect(sw.routeFor(new URL("https://other.test/_next/static/a.js"), { method: "GET", mode: "no-cors" }, ORIGIN).strategy).toBe("ignore");
    expect(route("/data/index.json", "cors", "POST").strategy).toBe("ignore");
    expect(route("/fonts/onest-latin-wght-normal.woff2", "cors", "GET", true).strategy).toBe("ignore");
    expect(route("/sw.js").strategy).toBe("ignore");
    expect(route("/manifest.webmanifest").strategy).toBe("ignore");
    expect(route("/cdn-cgi/rum").strategy).toBe("ignore");
    expect(route("/something.bin", "cors").strategy).toBe("ignore");
  });
});

describe("eviction", () => {
  it("touchRecent puts the opened station first without duplicates", () => {
    expect([...sw.touchRecent(["a", "b", "c"], "c")]).toEqual(["c", "a", "b"]);
    expect([...sw.touchRecent([], "a")]).toEqual(["a"]);
    expect([...sw.touchRecent(["a"], "b")]).toEqual(["b", "a"]);
  });
  it("planPrune drops the least recent stations beyond the bound, oldest first", () => {
    const recent = ["s1", "s2", "s3", "s4", "s5"];
    const plan = sw.planPrune(recent, ["s1", "s2", "s3", "s4", "s5"], 3);
    expect([...plan.recent]).toEqual(["s1", "s2", "s3"]);
    expect([...plan.purge]).toEqual(["s4", "s5"]);
  });
  it("planPrune also purges prefetched stations that were never opened", () => {
    const plan = sw.planPrune(["a", "b"], ["a", "x", "b", "y", "x"], 8);
    expect([...plan.recent]).toEqual(["a", "b"]);
    expect([...plan.purge]).toEqual(["x", "y"]);
  });
  it("a station opened again survives the eviction that would have taken it", () => {
    let recent: string[] = [];
    for (const id of ["1", "2", "3", "4"]) recent = [...sw.touchRecent(recent, id)];
    recent = [...sw.touchRecent(recent, "1")]; // 1 is the most recent again
    const plan = sw.planPrune(recent, ["1", "2", "3", "4"], 3);
    expect([...plan.purge]).toEqual(["2"]);
  });
  it("planPrune with nothing to purge", () => {
    expect([...sw.planPrune(["a"], ["a"], 8).purge]).toEqual([]);
  });
  it("staticEvictions keeps the newest entries", () => {
    expect([...sw.staticEvictions(["a", "b", "c", "d"], 3)]).toEqual(["a"]);
    expect([...sw.staticEvictions(["a", "b"], 3)]).toEqual([]);
    expect([...sw.staticEvictions(["a", "b", "c"], 0)]).toEqual(["a", "b", "c"]);
  });
});

describe("isCacheable: never opaque or failed responses", () => {
  const res = (o: Record<string, unknown>) => ({
    type: "basic",
    status: 200,
    ok: true,
    redirected: false,
    headers: { get: () => null },
    ...o,
  });
  it("accepts a plain same-origin 200", () => expect(sw.isCacheable(res({}))).toBe(true));
  it("refuses opaque, failed, partial, redirected and no-store responses", () => {
    expect(sw.isCacheable(res({ type: "opaque", status: 0, ok: false }))).toBe(false);
    expect(sw.isCacheable(res({ type: "cors" }))).toBe(false);
    expect(sw.isCacheable(res({ status: 404, ok: false }))).toBe(false);
    expect(sw.isCacheable(res({ status: 500, ok: false }))).toBe(false);
    expect(sw.isCacheable(res({ status: 206 }))).toBe(false);
    expect(sw.isCacheable(res({ redirected: true }))).toBe(false);
    expect(sw.isCacheable(res({ headers: { get: () => "no-store" } }))).toBe(false);
    expect(sw.isCacheable(null)).toBe(false);
  });
});

describe("staticUrlsIn", () => {
  it("finds the hashed files a page names, once", () => {
    const html =
      '<link rel="stylesheet" href="/_next/static/chunks/0yfg.css"/><script src="/_next/static/chunks/2r4s.js" async></script>' +
      '<script>x("/_next/static/chunks/2r4s.js");y("/fonts/a.woff2")</script>';
    expect([...sw.staticUrlsIn(html)].sort()).toEqual(["/_next/static/chunks/0yfg.css", "/_next/static/chunks/2r4s.js"]);
  });
});

describe("favourites in the worker", () => {
  it("favouritesFromMessage keeps valid ids, once, at most the maximum", () => {
    expect([...sw.favouritesFromMessage({ type: "favourites", ids: ["a", "a", "../x", 5, "b"] })!]).toEqual(["a", "b"]);
    expect([...sw.favouritesFromMessage({ type: "favourites", ids: [] })!]).toEqual([]);
    const many = Array.from({ length: 30 }, (_, i) => String(i));
    expect(sw.favouritesFromMessage({ type: "favourites", ids: many })).toHaveLength(sw.MAX_FAVOURITES);
    expect(sw.favouritesFromMessage({ type: "station-opened", id: "a" })).toBeNull();
    expect(sw.favouritesFromMessage({ type: "favourites", ids: "a" })).toBeNull();
  });
  it("planPrune never purges favourites, and they do not count towards the bound", () => {
    const plan = sw.planPrune(["s1", "s2", "s3"], ["s1", "s2", "s3", "f1", "old"], 2, ["f1"]);
    expect([...plan.recent]).toEqual(["s1", "s2"]);
    expect([...plan.purge].sort()).toEqual(["old", "s3"]);
  });
});
