# Next departures in real time: one Worker route, the site's own origin only

The station screen shows the next departures in minutes, like a platform screen. The data is the PRIM "Prochains passages" API of Île-de-France Mobilités (unit request, SIRI Lite `stop-monitoring`, ODbL; DATA_SOURCES.md #15). It needs an API key, so the browser cannot ask it directly, and the promise "no third-party request" forbids it anyway.

## Decision

- `app/worker/index.ts` answers `GET /api/next/<place id>`. `wrangler.jsonc` sets `main`, an `ASSETS` binding and `run_worker_first: ["/api/*"]`: only `/api/*` invokes the Worker. Pages, data and the service worker stay static asset requests (free, unlimited, `_headers` applies), as in ADR 0003. This replaces "no Worker script" in ADR 0003 for that one path.
- The Worker reads `/data/places/<id>.json` from the assets (stop areas = `place.stop_areas` when present, else `place.station_ids`; lines = `place.lines`), asks PRIM for `STIF:StopArea:SP:<id>:` per stop area (at most 3), keeps the Place's lines, and answers `{ status, now, rows: [{ line, dest, times, atStop }] }` (`app/src/lib/departures.ts`, tested in `app/test/departures.test.ts`). An unknown Place costs no PRIM request.
- The key is a Worker secret (`PRIM_API_KEY`). Without it the route answers `status: "off"` and the screen shows nothing.
- Nothing about the visitor goes to PRIM: the request carries the stop area and the key only.
- The browser asks every 30 s while the page is visible, on the "now" view only; the service worker does not touch `/api/*`.

## Quota

PRIM sets a daily quota per API. For the unit request it is 1,000 requests a day by default (5 per second); the project's key was raised to the maximum, 1,000,000 a day, on 2026-11-19 (asked on the PRIM "API usage" page). Answers are kept 30 s in the edge cache (per Cloudflare location), a PRIM failure 60 s, a quota refusal (HTTP 429) 10 minutes, so one station costs at most 2,880 requests a day per location. The limit that binds first is Cloudflare's: each call to `/api/next/*` is one Worker invocation (100,000 a day on the free plan, about 830 hours of station viewing).

## Not verified yet

The parser follows the documented answer; it has not been run against a live answer from the build environment (no access to PRIM there). Check after the first deploy: `curl https://<site>/api/next/71264`.

## Consequences

- The method page should name the real-time source and say the site relays it without storing anything.
- Coverage follows PRIM's real-time perimeter: a station without real-time data shows no block.

## References

- Call parameters (stop area and line identifiers): https://prim.iledefrance-mobilites.fr/en/aide-et-contact/documentation/prise-en-main-des-api/prise-en-main-des-api-prochains-passages/structure-des-requetes-parametres-dappel
- API page (quotas, licence): https://prim.iledefrance-mobilites.fr/en/apis/idfm-ivtr-requete_unitaire
- `run_worker_first` with route patterns: https://developers.cloudflare.com/workers/static-assets/binding/
