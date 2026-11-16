"""Error metrics on a long prediction table (one row per model x station x date).

WAPE = sum |y - p| / sum y (main metric), MAE, MAPE on rows with y >= MAPE_MIN_Y (small
counts make percentage errors explode: a station with 3 entries predicted 9 is +200 %).
"""

from __future__ import annotations

import polars as pl

MAPE_MIN_Y = 100
BUCKETS = [(1, 7, "1-7"), (8, 28, "8-28"), (29, 60, "29-60")]


def horizon_bucket(h: pl.Expr) -> pl.Expr:
    e = pl.lit(None, pl.String)
    for lo, hi, name in reversed(BUCKETS):
        e = pl.when(h.is_between(lo, hi)).then(pl.lit(name)).otherwise(e)
    return e


def error_aggs() -> list[pl.Expr]:
    err = (pl.col("y") - pl.col("pred")).abs()
    pos = pl.col("y") >= MAPE_MIN_Y
    return [
        pl.len().alias("n"),
        (err.sum() / pl.col("y").sum()).alias("wape"),
        err.mean().alias("mae"),
        (err.filter(pos) / pl.col("y").filter(pos)).mean().alias("mape"),
    ]


def summarize(long: pl.DataFrame, by: list[str]) -> pl.DataFrame:
    return long.group_by(["model", *by]).agg(error_aggs()).sort(["model", *by])


def network_level(long: pl.DataFrame, by: list[str] | None = None) -> pl.DataFrame:
    """Errors on network daily totals (sum over scored stations of each origin x date)."""
    by = by or []
    daily = long.group_by(["model", "origin", "date", *by]).agg(
        pl.col("y").sum(), pl.col("pred").sum()
    )
    return summarize(daily, by)


def gains(table: pl.DataFrame, model: str, baselines: list[str], by: list[str]) -> pl.DataFrame:
    """1 - WAPE(model) / WAPE(baseline) per group (positive = model better)."""
    idx = by or ["group"]
    t = table if by else table.with_columns(pl.lit("all").alias("group"))
    w = t.pivot(on="model", index=idx, values="wape")
    return w.select(
        *idx,
        *[(1 - pl.col(model) / pl.col(b)).alias(f"gain_vs_{b}") for b in baselines],
    ).sort(idx)
