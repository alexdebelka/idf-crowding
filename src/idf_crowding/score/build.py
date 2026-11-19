"""Build the v0 typical week (Crowding score) and the app's JSON files.

    idf-score build

Reads data/processed (features_daily, station_profiles, stations) and the stop reference
in data/raw/idfm/reference (arrets-lignes, referentiel-des-lignes, zones-d-arrets, arrets).
Writes data/processed/typical_week.parquet and <app_data_dir>/{index.json,places/*.json}.
When data/processed/forecast/<cutoff>/forecast.parquet exists for the latest data cutoff,
place files also carry the date forecasts (place.v2, score/dated.py).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl

from idf_crowding.config import REPO_ROOT, load_config
from idf_crowding.features.calendar import load_public_holidays, load_school_holidays
from idf_crowding.features.stations import last_quarters
from idf_crowding.score import dated, export
from idf_crowding.score.places import assign, load_overrides
from idf_crowding.score.reference import (
    KIND_ORDER,
    apply_aliases,
    in_scope,
    lambert93_to_wgs84,
    line_info,
    stop_lines,
)
from idf_crowding.score.typical import (
    ScoreSettings,
    hourly_profiles,
    place_days,
    typical_week,
    usable_days,
    window,
)


@dataclass(frozen=True)
class Paths:
    raw: Path
    processed: Path
    app_data: Path
    places_file: Path | None

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> Paths:
        data = Path(config["paths"]["data_dir"])
        sc = config.get("score", {})
        pf = sc.get("places_file")
        return cls(
            data / "raw",
            data / "processed",
            Path(config["paths"]["app_data_dir"]),
            (REPO_ROOT / pf) if pf else None,
        )


def _line_key(line: dict[str, Any]) -> tuple:
    name = line["name"]
    num = int("".join(c for c in name if c.isdigit()) or 0)
    return (KIND_ORDER[line["kind"]], num, name)


def place_meta(
    members: pl.DataFrame,
    stations: pl.DataFrame,
    lines: pl.DataFrame,
    names: dict[str, str],
) -> dict[str, dict[str, Any]]:
    st = {r["station_id"]: r for r in stations.iter_rows(named=True)}
    lines_by_station: dict[int, list[dict[str, Any]]] = {}
    for r in lines.iter_rows(named=True):
        lines_by_station.setdefault(r["station_id"], []).append(
            {k: r[k] for k in ("line_id", "name", "kind", "color", "text_color")}
        )
    meta = {}
    for (pid,), grp in members.group_by("place_id"):
        sids = sorted(grp["station_id"].to_list())
        rows = [st[s] for s in sids if s in st]
        coords = [
            lambert93_to_wgs84(r["x_epsg2154"], r["y_epsg2154"])
            for r in rows
            if r["x_epsg2154"] is not None and r["y_epsg2154"] is not None
        ]
        seen: dict[str, dict[str, Any]] = {}
        for s in sids:
            for ln in lines_by_station.get(s, []):
                seen[ln["line_id"]] = {
                    "id": ln["line_id"],
                    "name": ln["name"],
                    "kind": ln["kind"],
                    "color": ln["color"],
                    "text_color": ln["text_color"],
                }
        first = rows[0] if rows else {}
        name = names.get(pid) or first.get("ref_name") or str(first.get("label", pid)).title()
        meta[pid] = {
            "id": pid,
            "name": name,
            "town": first.get("ref_town"),
            "lat": round(sum(c[0] for c in coords) / len(coords), 6) if coords else None,
            "lon": round(sum(c[1] for c in coords) / len(coords), 6) if coords else None,
            "station_ids": sids,
            "lines": sorted(seen.values(), key=_line_key),
        }
    return meta


def date_forecasts(
    paths: Paths,
    data_end: Any,
    members: pl.DataFrame,
    hourly: pl.DataFrame,
    levels: pl.DataFrame,
    refs: pl.DataFrame,
    now: datetime,
) -> dict[str, Any] | None:
    """The `forecast` input of export.place_records, or None without a production forecast."""
    path = dated.latest_forecast(paths.processed, data_end + timedelta(days=1))
    if path is None:
        return None
    fc = pl.read_parquet(path)
    daily = dated.place_daily(fc, members)
    reasons = dated.calendar_reasons(
        daily["date"].unique(), load_public_holidays(paths.raw), load_school_holidays(paths.raw)
    )
    today = now.astimezone(ZoneInfo("Europe/Paris")).date()
    return {
        "issue_date": fc["issue_date"].max().isoformat(),
        "data_end": fc["data_end"].max().isoformat(),
        "dates": dated.date_records(daily, hourly, levels, refs, reasons, today),
    }


def build(
    paths: Paths, s: ScoreSettings, log: Callable[[str], None] = print, now: datetime | None = None
) -> list[dict[str, Any]]:
    now = now or datetime.now(UTC)
    features = pl.read_parquet(paths.processed / "features_daily.parquet")
    profiles = pl.read_parquet(paths.processed / "station_profiles.parquet")
    stations = pl.read_parquet(paths.processed / "stations.parquet")

    sl = apply_aliases(stop_lines(paths.raw), {a: b for a, b, _ in s.zdc_aliases})
    scope = set(in_scope(sl, list(s.modes), list(s.extra_lines)).to_list())
    lines = sl.join(line_info(paths.raw), on="line_id").filter(
        pl.col("station_id").is_in(list(scope))
    )

    start, end = window(features, s.window_days)
    st_days = usable_days(features, s, start, end)
    overrides = load_overrides(paths.places_file)
    all_members = assign(sorted(st_days["station_id"].unique().to_list()), overrides)
    in_scope_places = all_members.filter(pl.col("station_id").is_in(list(scope)))["place_id"]
    members = all_members.filter(pl.col("place_id").is_in(in_scope_places.unique().implode()))

    periods = last_quarters(profiles, s.n_quarters)
    prof = hourly_profiles(profiles, periods)
    pdays = place_days(st_days, members)
    hourly, levels, refs = typical_week(pdays, st_days, prof, members, s)

    members = members.filter(pl.col("place_id").is_in(refs["place_id"].implode()))
    names = {str(b): n for _, b, n in s.zdc_aliases if n}
    names.update({o.id: o.name for o in overrides})
    meta = place_meta(members, stations, lines, names)
    forecast = date_forecasts(paths, end, members, hourly, levels, refs, now)
    records = export.place_records(
        hourly, levels, refs, meta, s, (start, end), periods, now, forecast
    )
    index = export.index_record(records, s, (start, end), now)

    paths.processed.mkdir(parents=True, exist_ok=True)
    hourly.join(levels, on=["place_id", "day_type"]).join(refs, on="place_id").write_parquet(
        paths.processed / "typical_week.parquet"
    )
    files = export.write(paths.app_data, index, records)
    low = levels.filter(pl.col("low_confidence")).height
    log(
        f"score: window {start} -> {end}, profiles {','.join(periods)}; "
        f"{len(records)} places in scope ({len(scope)} metro/RER/T4 stations in the reference), "
        f"{low} place x day types low-confidence; {len(files)} JSON files -> {paths.app_data}"
    )
    if forecast is None:
        log("score: no production forecast for this cutoff, place files are v1 (typical week)")
    else:
        n = [len(v) for v in forecast["dates"].values()]
        days = sorted({d["d"] for v in forecast["dates"].values() for d in v})
        span = f"{days[0]} -> {days[-1]}" if days else "no future dates"
        log(
            f"score: date forecasts (place.v2) for {len(n)} of {len(records)} places, {span}, "
            f"issued {forecast['issue_date']}, data to {forecast['data_end']}"
        )
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="idf-score", description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["build"])
    parser.parse_args(argv)
    config = load_config()
    build(Paths.from_config(config), ScoreSettings.from_config(config.get("score", {})))
    return 0


if __name__ == "__main__":
    sys.exit(main())
