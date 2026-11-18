"""Growth extrapolation for LightGBM.

Trees do not extrapolate the `t_days` trend past the training data, so with the data
published ~4 months late every day type is under-forecast, and weekends most: weekend
traffic grows faster (Sunday / weekday 0.45 in 2024 H1, 0.53 in 2026 H1). See
docs/data-quality.md "Growth extrapolation".

Per weekday class (Mon–Fri, Sat, Sun) the growth rate at a cutoff c is
g = mean daily network total over [c − window, c) / the same over the window 364 days
earlier (public holidays and flagged days out, stations with data on at least half the days of
both windows). The
LightGBM forecast for date d is multiplied by g ** ((d − c) / 364). The ensemble stays
mean(corrected LightGBM, TFT).
"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

WINDOW_DAYS = 182
MIN_COVERAGE = 0.5
CLASSES = ("wk", "sat", "sun")


def weekday_class(col: str = "date") -> pl.Expr:
    wd = pl.col(col).dt.weekday()
    return (
        pl.when(wd <= 5)
        .then(pl.lit("wk"))
        .when(wd == 6)
        .then(pl.lit("sat"))
        .otherwise(pl.lit("sun"))
    )


def growth_rates(
    features: pl.DataFrame | pl.LazyFrame, cutoff: date, window: int = WINDOW_DAYS
) -> pl.DataFrame:
    """cls, g: year-on-year growth of the mean daily network total per weekday class, over
    the `window` days before `cutoff` vs the same days 364 days earlier."""
    now = (cutoff - timedelta(days=window), cutoff)
    ago = (cutoff - timedelta(days=window + 364), cutoff - timedelta(days=364))
    lf = features.lazy() if isinstance(features, pl.DataFrame) else features
    period = (
        pl.when(pl.col("date").is_between(*now, closed="left"))
        .then(pl.lit("now"))
        .when(pl.col("date").is_between(*ago, closed="left"))
        .then(pl.lit("ago"))
    )
    d = (
        lf.filter(
            pl.col("n_entries").is_not_null()
            & pl.col("quality_flag").is_null()
            & ~pl.col("is_public_holiday").fill_null(False)
        )
        .with_columns(period.alias("p"))
        .filter(pl.col("p").is_not_null())
        .select("station_id", "date", "n_entries", "p")
        .collect()
    )
    # stations with data on at least half the days of both windows (openings, long closures
    # and recoding would otherwise read as growth)
    days = d.group_by("station_id", "p").agg(pl.col("date").n_unique().alias("n"))
    both = (
        days.filter(pl.col("n") >= window * MIN_COVERAGE)
        .group_by("station_id")
        .agg(pl.len().alias("k"))
        .filter(pl.col("k") == 2)
    )
    daily = (
        d.join(both.select("station_id"), on="station_id")
        .group_by("p", "date")
        .agg(pl.col("n_entries").sum())
        .with_columns(weekday_class().alias("cls"))
    )
    m = daily.group_by("p", "cls").agg(pl.col("n_entries").mean().alias("v"))
    g = (
        m.filter(pl.col("p") == "now")
        .join(m.filter(pl.col("p") == "ago"), on="cls", suffix="_ago")
        .select("cls", (pl.col("v") / pl.col("v_ago")).alias("g"))
    )
    return (
        pl.DataFrame({"cls": list(CLASSES)})
        .join(g, on="cls", how="left")
        .with_columns(pl.col("g").fill_null(1.0))
    )


def factor(cutoff: date) -> pl.Expr:
    """Expression for g ** ((date − cutoff) / 364); needs the column `g` joined (see apply)."""
    days = (pl.col("date") - pl.lit(cutoff)).dt.total_days()
    return (pl.col("g").log() * days / 364).exp()


def apply(rows: pl.DataFrame, rates: pl.DataFrame, cutoff: date, col: str = "lgbm") -> pl.DataFrame:
    """`col` × growth factor; adds `growth` (the factor) and `<col>_raw`."""
    return (
        rows.with_columns(weekday_class().alias("_cls"))
        .join(rates.rename({"cls": "_cls"}), on="_cls", how="left")
        .with_columns(factor(cutoff).fill_null(1.0).alias("growth"))
        .with_columns(pl.col(col).alias(f"{col}_raw"), (pl.col(col) * pl.col("growth")).alias(col))
        .drop("_cls", "g")
    )


def apply_log(
    log: pl.DataFrame, features: pl.DataFrame | pl.LazyFrame, window: int = WINDOW_DAYS
) -> pl.DataFrame:
    """Forecast log (backtest rows with a `cutoff` column): each origin's LightGBM rows ×
    the growth factor of its own cutoff (rates from data before that cutoff only)."""
    parts = []
    for (c,), part in log.group_by("cutoff", maintain_order=True):
        parts.append(apply(part, growth_rates(features, c, window), c))
    return pl.concat(parts, how="diagonal")
