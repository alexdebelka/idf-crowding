"""`idf-ingest plan|run [--source ...]`: download every raw source into data/raw.

Sources: idfm (validations, stop reference, docs), calendar (public + school holidays),
weather (Open-Meteo). Files already on disk are skipped; each download is appended to
data/raw/manifest.jsonl.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

import httpx

from idf_crowding.ingest import calendar, idfm, weather

SOURCES = ["idfm", "calendar", "weather"]


def collect(
    client: httpx.Client, sources: list[str], today: date
) -> list[tuple[object, idfm.Item]]:
    """(settings, item) for every file to fetch, in source order."""
    out: list[tuple[object, idfm.Item]] = []
    if "idfm" in sources:
        s = idfm.Settings.from_config()
        out += [(s, i) for i in idfm.plan(client, s, today)]
    if "calendar" in sources:
        s = calendar.Settings.from_config()
        out += [(s, i) for i in calendar.plan(s, today)]
    if "weather" in sources:
        s = weather.Settings.from_config()
        out += [(s, i) for i in weather.plan(s, today)]
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="idf-ingest", description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["plan", "run"])
    parser.add_argument(
        "--source", action="append", choices=SOURCES, help="repeatable; default: all sources"
    )
    args = parser.parse_args(argv)
    sources = args.source or SOURCES

    with httpx.Client(timeout=120, follow_redirects=True) as client:
        items = collect(client, sources, date.today())
        todo = [(s, i) for s, i in items if not (s.raw_dir / i.dest).exists()]
        raw_dir = items[0][0].raw_dir if items else "-"
        print(f"{len(items)} files listed, {len(todo)} new, raw dir: {raw_dir}")
        if args.command == "plan":
            new = {id(i) for _, i in todo}
            for _, i in items:
                state = "new" if id(i) in new else "on disk"
                print(f"  [{state}] {i.dest.as_posix()}  ({i.period or '-'})")
            return 0
        total = 0
        for k, (s, i) in enumerate(todo, 1):
            print(f"[{k}/{len(todo)}] {i.dest.as_posix()} ...", flush=True)
            entry = idfm.download(client, i, s)
            if entry:
                total += entry["bytes"]
                print(f"    {entry['bytes'] / 1e6:.1f} MB  sha256 {entry['sha256'][:12]}")
        print(f"done: {len(todo)} files, {total / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
