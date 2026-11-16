"""Station closure days, detected from data before each day only.

A station closed or partly closed for works keeps a few entries (other exits, staff,
replacement services) instead of none, and a closure lasting several weeks is not
caught by the quality flags: they compare a day with a centred rolling median, which is
low too during a long closure. Those days then teach the model a lower level that
persists after the reopening.

Rule: the station's share of network entries that day, divided by its median share on
the same kind of day (working day / Saturday / Sunday-holiday) over the previous 365
days (at least `min_days` such days), below `ratio` → closure. Only past days enter the
median, so the flag can be used for training rows without leakage.
"""

from __future__ import annotations

import polars as pl

DAY_GROUP = (
    pl.when(pl.col("day_type").is_in(["SAHV", "SAVS"]))
    .then(pl.lit("SA"))
    .when(pl.col("day_type") == "DIJFP")
    .then(pl.lit("DI"))
    .otherwise(pl.lit("JO"))
)


def closure_ratio(data: pl.DataFrame, min_days: int = 20) -> pl.Series:
    """share / trailing 365-day median share on the same day group (null if unknown)."""
    net = data.group_by("date").agg(pl.col("n_entries").sum().alias("_net"))
    d = (
        data.select("station_id", "date", "day_type", "n_entries")
        .with_row_index("_i")
        .join(net, on="date", how="left")
        .with_columns((pl.col("n_entries") / pl.col("_net")).alias("_share"), DAY_GROUP.alias("_g"))
        .sort("station_id", "_g", "date")
        .with_columns(
            pl.col("_share")
            .rolling_median_by("date", window_size="365d", closed="left", min_samples=min_days)
            .over("station_id", "_g")
            .alias("_ref")
        )
        .sort("_i")
    )
    return (d["_share"] / d["_ref"]).alias("closure_ratio")


def is_closure(data: pl.DataFrame, ratio: float = 0.4, min_days: int = 20) -> pl.Series:
    return (closure_ratio(data, min_days) < ratio).fill_null(False).alias("is_closure")
