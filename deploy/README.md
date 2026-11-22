# Scheduling the collectors

The disruption logger is a one-shot command (`uv run idf-disruptions poll`); any scheduler
can run it. Run it every 5 minutes (the default PRIM quota for new tokens is 1000
requests/day). Gaps between successful polls are logged in `data/live/disruptions/gaps.jsonl`
whatever the scheduler.

Templates use placeholders: `@REPO@` (absolute path of this repo), `@UV@` (output of
`command -v uv`) and `@PATH@` (a PATH that contains `rclone`).

## launchd (macOS)

Shortcut: `scripts/install_launchd.sh disruptions` (and `backup`) renders the template,
loads it and prints its state. Manual equivalent:

```sh
mkdir -p logs
for f in deploy/launchd/*.plist.in; do
  sed -e "s|@REPO@|$PWD|g" -e "s|@UV@|$(command -v uv)|g" -e "s|@PATH@|$PATH|g" "$f" \
    > ~/Library/LaunchAgents/$(basename "${f%.in}")
done
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/idf-crowding.disruptions.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/idf-crowding.backup.plist
```

Stop: `launchctl bootout gui/$(id -u)/idf-crowding.disruptions`.
The host must stay awake for polls to run (e.g. `pmset`, or disable sleep on power).

## systemd (Linux)

See `deploy/systemd/`. Add a second timer for `scripts/backup_live.sh` if needed.

## cron

See `deploy/cron/crontab.example`.

## Compaction

`uv run idf-disruptions compact` packs every finished UTC day of `data/live/disruptions/raw/`
into `snapshots.tar.xz` (+ `compacted.json`), then re-reads it and checks every snapshot
against its `.json.gz` file and the hash logged at poll time. Originals are kept unless
`delete_after_compact = true` (config) or `--delete-originals` is given. Schedule it nightly
before the backup: `scripts/install_launchd.sh compact`, or the cron line in
`deploy/cron/crontab.example`. Read snapshots with `idf_crowding.live.compact.read_snapshot`.

## Backup

`data/live` can't be re-downloaded. `scripts/backup_live.sh` copies it to `$BACKUP_REMOTE`
with `rclone copy` (never deletes remote files). Configure the destination in `.env`
(see `.env.example`); use a storage token scoped to that one bucket.

Check status any time: `uv run idf-disruptions status`.

## Web app (static, Cloudflare)
The app is a Next.js static export (ADR 0001). The build host runs the pipeline, builds the
site and uploads `app/out` to Cloudflare Workers static assets. Nothing runs at request time.

First time, on the build host:

```sh
cd app && npm ci
npx wrangler login            # or set CLOUDFLARE_API_TOKEN (Workers Scripts: Edit)
```

Next departures (ADR 0004) need the PRIM key as a Worker secret, once:

```sh
npx wrangler secret put PRIM_API_KEY     # paste the key when asked; it is never written to a file
```

Without the secret the site works and the departures block stays hidden. Check after a deploy:
`curl https://<site>/api/next/71264`.

Each refresh (after new IDFM data, `make ingest clean features`):

```sh
make score                     # data/processed/typical_week.parquet + app/public/data/*.json
cd app
npm run check                  # lint, types, JSON schema tests
npm run build                  # -> app/out (static HTML + /data/*.json)
npx wrangler deploy            # uploads app/out (wrangler.jsonc)
```

Preview locally: `npx serve out` (or `python3 -m http.server -d out`).

Notes:
- `app/out` has ~3 300 files (538 Places on the first build); Workers static assets allow
  20 000 files of up to 25 MiB each on the free plan. If date forecasts outgrow this, move
  `data/` to R2 without changing the app (ADR 0001).
- The published `/data/*.json` files are derived from IDFM data: ODbL, attribution kept in
  every file and page footer.
- Choose the custom domain in the Cloudflare dashboard (Workers → the project → Domains).
  Use no IDFM, RATP, SNCF or Navigo names or logos in the domain or site name.
- A GitHub Action can rebuild from the same commands as a backup builder; it needs the
  processed data, which is not in git.
