# idf-crowding

Forecast how busy Île-de-France rail stations are by day and hour, from open data only,
to help travellers pick a quieter time slot.

Existing operator apps show live crowding of the next train. This project is about
*planning*: comparing time slots across the week, with calendar and weather effects,
using a transparent and reproducible method.

**Status:** v0. A typical-week crowding score for every metro and RER station (hour ×
day type, from the last 12 months of validations) and a static web app. Date forecasts
come next.

## Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

Configuration defaults are in `config.toml`; put local overrides in `config.local.toml`
(git-ignored). API keys go in `.env` (see `.env.example`); the code looks for `.env` in
this folder and its parents.

## Disruption logger

There is no public archive of past disruption messages, so the project logs them from the
PRIM "Messages Info Trafic" API (free account and API key required):

```sh
uv run idf-disruptions poll     # one request; raw response saved under data/live/
uv run idf-disruptions status   # last successful poll and any ongoing gap
```

Schedule `poll` every 5 minutes with cron, systemd or launchd: see `deploy/README.md`.
Each response is stored gzipped and unmodified (only when it changed), every poll is logged,
and gaps are recorded in `data/live/disruptions/gaps.jsonl`.

## Typical week and web app (v0)

```sh
make ingest clean features   # raw downloads -> harmonised tables -> features
make score                   # app/public/data/index.json + places/<id>.json
cd app && npm ci && npm run build && npx serve out
```

The **Crowding score** of an hour is the expected number of entries divided by the
station's own reference level (95th percentile of its hourly entries over the last 12
months), × 100. Method and data-quality rules: `docs/data-quality.md` ("Score").
The JSON files are the only interface between the pipeline and the app; their contract is
`schemas/*.v1.schema.json`, tested on both sides. Deployment: `deploy/README.md`.

## Layout

```
src/idf_crowding/   pipeline code (ingest, live, clean, features, models, viz)
tests/              pytest suite (no network, no downloads)
app/                static web app (Next.js export, TypeScript)
schemas/            JSON contract between pipeline and app
deploy/             scheduler templates
docs/adr/           design decisions
CONTEXT.md          domain glossary
DATA_SOURCES.md     data sources and licenses
```

Data is never committed: everything under `data/` is rebuilt from the sources.

## Data and attribution

Data comes from Île-de-France Mobilités (open data portal and PRIM) and other open sources
listed in [`DATA_SOURCES.md`](DATA_SOURCES.md), each under its own license. Validation data
and derived databases are under the ODbL; any published derived data from this project
will be ODbL too.

This is an independent project, not affiliated with or endorsed by Île-de-France
Mobilités, RATP or SNCF.

## License

Code: [MIT](LICENSE). Data: see above.
