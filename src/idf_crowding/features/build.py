"""Build data/processed/features_daily.parquet (Phase 4).

    idf-features build

One row per station x date with the target `n_entries` and:
    calendar   weekday, month, day_of_year, year, is_public_holiday, is_bridge,
               is_school_holiday, day_type, is_covid, is_strike_2019
    weather    precip_mm, snow_cm, precip_hours, tmax_c, tmin_c   (Paris, daily)
    tickets    short_pass_share   (2025 ticket-change ramp, by month)
    station    station_type (origin / mixed / destination), am_share_7_10
    quality    quality_flag (missing / low / high / null), network_ratio (network total /
               its usual level for that weekday: < 0.8 = strike, holiday week...)

Rows are added for dates flagged "missing" inside a station's active span (n_entries
null), so the model sees gaps explicitly. Sources not downloaded yet give null columns
and a warning; nothing is guessed.
"""

from __future__ import annotations

import argparse
import sys
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from idf_crowding.clean.quality import network_daily
from idf_crowding.config import load_config
from idf_crowding.features.calendar import (
    calendar_features,
    load_public_holidays,
    load_school_holidays,
)
from idf_crowding.features.stations import station_types
from idf_crowding.features.tickets import monthly_share, ramp_for_dates
from idf_crowding.features.weather import empty_weather, load_weather


@dataclass(frozen=True)
class Paths:
    raw: Path
    interim: Path
    processed: Path

    @classmethod
    def from_config(cls) -> Paths:
        data = Path(load_config()["paths"]["data_dir"])
        return cls(data / "raw", data / "interim", data / "processed")


def build(paths: Paths, log: Callable[[str], None] = print) -> pl.DataFrame:
    daily = pl.read_parquet(paths.processed / "station_daily.parquet").select(
        "station_id", "date", "n_entries", "n_masked_rows"
    )
    flags = pl.read_parquet(paths.processed / "quality/station_day_flags.parquet")

    # explicit rows for missing station-days
    missing = flags.filter(pl.col("flag") == "missing").select(
        "station_id",
        "date",
        pl.lit(None, pl.Int64).alias("n_entries"),
        pl.lit(None, pl.Int64).alias("n_masked_rows"),
    )
    base = pl.concat([daily, missing.cast(daily.schema)]).unique(["station_id", "date"])
    base = base.join(
        flags.select("station_id", "date", pl.col("flag").alias("quality_flag")),
        on=["station_id", "date"],
        how="left",
    ).join(network_daily(daily), on="date", how="left")

    dates = base.select("date").unique().sort("date")
    holidays = load_public_holidays(paths.raw)
    school = load_school_holidays(paths.raw)
    weather = load_weather(paths.raw)
    for name, src in [
        ("public holidays", holidays),
        ("school holidays", school),
        ("weather", weather),
    ]:
        if src is None:
            warnings.warn(
                f"{name}: no raw file yet, columns left null (run `idf-ingest run`)",
                stacklevel=2,
            )
    cal = calendar_features(dates["date"], holidays, school)

    if weather is None:
        cal = cal.with_columns(empty_weather())
    else:
        cal = cal.join(weather, on="date", how="left")

    shares = monthly_share(pl.scan_parquet(paths.interim / "validations_daily_tickets.parquet"))
    cal = cal.with_columns(ramp_for_dates(cal, shares).alias("short_pass_share"))

    types = station_types(pl.read_parquet(paths.processed / "station_profiles.parquet"))

    out = (
        base.join(cal, on="date", how="left")
        .join(types.drop("station_type_periods"), on="station_id", how="left")
        .sort("station_id", "date")
    )
    target = paths.processed / "features_daily.parquet"
    out.write_parquet(target)
    log(
        f"features: {out.height:,} rows x {out.width} cols -> {target.name}; "
        f"station types from {types['station_type_periods'][0]}"
    )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="idf-features", description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["build"])
    parser.parse_args(argv)
    build(Paths.from_config())
    return 0


if __name__ == "__main__":
    sys.exit(main())
