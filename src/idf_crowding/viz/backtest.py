"""Tables for notebooks/02_backtest.ipynb (plots only there)."""

from __future__ import annotations

import polars as pl

from idf_crowding.models.metrics import error_aggs


def long_scored(pred: pl.DataFrame, models: list[str]) -> pl.DataFrame:
    keep = ["origin", "station_id", "date", "horizon", "horizon_bucket", "station_type"]
    return pred.filter(pl.col("scored")).unpivot(
        on=models, index=[*keep, "day_type", "y"], variable_name="model", value_name="pred"
    )


def wape_by_horizon(long: pl.DataFrame) -> pl.DataFrame:
    """model x horizon (days) WAPE over all origins and stations."""
    return long.group_by("model", "horizon").agg(error_aggs()).sort("model", "horizon")


def network_series(pred: pl.DataFrame, origin, models: list[str]) -> pl.DataFrame:
    """Daily totals of scored stations for one origin: actual and each model."""
    p = pred.filter(pl.col("scored") & (pl.col("origin") == origin))
    return (
        p.group_by("date").agg(pl.col("y").sum(), *[pl.col(m).sum() for m in models]).sort("date")
    )


def station_bias(pred: pl.DataFrame, model: str, n: int = 10) -> pl.DataFrame:
    """Station x origin pairs with the largest absolute error of `model` (share of the
    origin's total absolute error, relative bias = sum(y - pred) / sum(y))."""
    p = pred.filter(pl.col("scored")).with_columns((pl.col("y") - pl.col(model)).alias("e"))
    tot = p.group_by("origin").agg(pl.col("e").abs().sum().alias("total"))
    return (
        p.group_by("origin", "station_id")
        .agg(pl.col("e").abs().sum().alias("abs_err"), pl.col("e").sum(), pl.col("y").sum())
        .join(tot, on="origin")
        .select(
            "origin",
            "station_id",
            (pl.col("abs_err") / pl.col("total")).alias("share_of_error"),
            (pl.col("e") / pl.col("y")).alias("rel_bias"),
        )
        .sort("share_of_error", descending=True)
        .head(n)
    )


def station_band(pred: pl.DataFrame, station_id: int, origin) -> pl.DataFrame:
    """One station and origin: actual, point forecast and the 80 % conformal band."""
    return (
        pred.filter((pl.col("station_id") == station_id) & (pl.col("origin") == origin))
        .select("date", "y", "lgbm", "conf_lo", "conf_hi", "scored")
        .sort("date")
    )
