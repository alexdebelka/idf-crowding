"""Naive baselines. `history` holds clean rows before the origin only (the caller filters)."""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl


def seasonal_naive(
    history: pl.DataFrame, targets: pl.DataFrame, origin: date, weeks: int = 4
) -> pl.Series:
    """Mean of the same weekday over the `weeks` weeks before the origin, per station."""
    start = origin - timedelta(weeks=weeks)
    ref = (
        history.filter(pl.col("date").is_between(start, origin, closed="left"))
        .group_by("station_id", "weekday")
        .agg(pl.col("n_entries").mean().alias("pred"))
    )
    return _join_pred(targets, ref, ["station_id", "weekday"])


def day_type_mean(
    history: pl.DataFrame, targets: pl.DataFrame, origin: date, days: int = 365
) -> pl.Series:
    """Per-station mean by day type over the `days` days before the origin."""
    start = origin - timedelta(days=days)
    ref = (
        history.filter(
            pl.col("date").is_between(start, origin, closed="left")
            & pl.col("day_type").is_not_null()
        )
        .group_by("station_id", "day_type")
        .agg(pl.col("n_entries").mean().alias("pred"))
    )
    return _join_pred(targets, ref, ["station_id", "day_type"])


def _join_pred(targets: pl.DataFrame, ref: pl.DataFrame, on: list[str]) -> pl.Series:
    t = targets.select(on).with_row_index("_i")
    return t.join(ref, on=on, how="left").sort("_i")["pred"].cast(pl.Float64)
