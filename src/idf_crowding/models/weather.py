"""Production-like weather for a forecast issued at an origin (step 4).

At issue date o (data cutoff c = o - lag), the weather of the forecast days is not observed
yet. A weather forecast covers about `forecast_days` days; after that only climatology is
known. The backtest uses:
    dates <  o + forecast_days   observed weather (stands in for a weather forecast; the
                                 forecast error is ignored, so days 1-16 are optimistic)
    dates >= o + forecast_days   day-of-year climatology: mean of every date before c whose
                                 calendar day is within +- `window` days (all years since the
                                 weather source starts)
Weather is one regional series per date (features_daily repeats it for every station).
"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from idf_crowding.models.gbm import WEATHER

DOY_CYCLE = 366  # day of year 1..366; Dec 31 of a common year is 2 days from Jan 1


def daily_weather(features: pl.DataFrame | pl.LazyFrame) -> pl.DataFrame:
    """One row per date with the weather columns."""
    lf = features.lazy() if isinstance(features, pl.DataFrame) else features
    return lf.select("date", *WEATHER).unique("date").sort("date").collect()


def climatology(weather: pl.DataFrame, cutoff: date, window: int = 7) -> pl.DataFrame:
    """doy (1..366) -> mean of each weather column over dates < cutoff within +- window days
    of that calendar day."""
    past = weather.filter(pl.col("date") < cutoff).with_columns(
        pl.col("date").dt.ordinal_day().cast(pl.Int32).alias("_doy")
    )
    if past.height == 0:
        raise ValueError(f"no weather before {cutoff}")
    offsets = pl.DataFrame({"_k": list(range(-window, window + 1))}, schema={"_k": pl.Int32})
    return (
        past.join(offsets, how="cross")
        .with_columns(((pl.col("_doy") - 1 + pl.col("_k")) % DOY_CYCLE + 1).alias("doy"))
        .group_by("doy")
        .agg(pl.col(c).mean() for c in WEATHER)
        .sort("doy")
    )


def production_weather(
    test: pl.DataFrame,
    weather: pl.DataFrame,
    origin: date,
    cutoff: date,
    forecast_days: int = 16,
    window: int = 7,
) -> pl.DataFrame:
    """`test` with weather after the forecast range replaced by climatology at `cutoff`,
    plus `weather_source` (observed / climatology)."""
    clim = climatology(weather, cutoff, window).rename({c: f"_clim_{c}" for c in WEATHER})
    far = pl.col("date") >= origin + timedelta(days=forecast_days)
    return (
        test.with_row_index("_i")
        .with_columns(pl.col("date").dt.ordinal_day().cast(pl.Int32).alias("_doy"))
        .join(clim, left_on="_doy", right_on="doy", how="left")
        .sort("_i")
        .with_columns(
            [pl.when(far).then(pl.col(f"_clim_{c}")).otherwise(pl.col(c)).alias(c) for c in WEATHER]
            + [
                pl.when(far)
                .then(pl.lit("climatology"))
                .otherwise(pl.lit("observed"))
                .alias("weather_source")
            ]
        )
        .drop("_i", "_doy", *[f"_clim_{c}" for c in WEATHER])
    )
