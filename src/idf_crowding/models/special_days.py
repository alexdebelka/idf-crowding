"""Post-hoc correction for special days the models over-forecast.

Christmas Eve, Christmas Day, New Year's Eve and New Year's Day have far less traffic than
the ordinary holiday days that share their day type, and neither LightGBM (few years,
recency weights) nor TFT (smooth day of year) learns that: in the production-like backtest
both Christmases were over-forecast at network level (ensemble +23 % to +67 %, see
docs/data-quality.md "Special days").

Factor per (station, special day, model): log f = median over years of the station's
log1p ratio log1p(y) - log1p(point) (several origins covering one date are averaged
first), from forecast-log rows dated before the cutoff, shrunk to the station-type factor
(network factor for stations without a type): w = n / (n + k), n = number of years.
The corrected forecast is point x f, lo x f, hi x f (the band is multiplicative).
"""

from __future__ import annotations

from datetime import date

import polars as pl

# (month, day) -> name; chosen from the backtest (|network log ratio| > 0.15 in both years)
SPECIAL_DAYS: dict[tuple[int, int], str] = {
    (12, 24): "christmas_eve",
    (12, 25): "christmas_day",
    (12, 31): "new_years_eve",
    (1, 1): "new_years_day",
}
K_SHRINK = 2.0
# a station-year counts only if the station had this much data at the forecast's cutoff:
# young stations' errors shrink as their history grows (e.g. Orly, opened 2024-07)
MIN_HISTORY_DAYS = 730


def special_day(col: str = "date") -> pl.Expr:
    """Name of the special day of `col` (null on other dates)."""
    md = pl.col(col).dt.month().cast(pl.Int32) * 100 + pl.col(col).dt.day().cast(pl.Int32)
    keys = [m * 100 + d for (m, d) in SPECIAL_DAYS]
    return md.replace_strict(
        keys, list(SPECIAL_DAYS.values()), default=None, return_dtype=pl.String
    )


def _season(col: str = "date") -> pl.Expr:
    """Year of the Christmas season (Jan 1 belongs to the previous December)."""
    return pl.col(col).dt.year() - (pl.col(col).dt.month() == 1).cast(pl.Int32)


def station_year_ratios(
    log: pl.DataFrame,
    point: str,
    cutoff: date,
    first_seen: pl.DataFrame | None = None,
    min_history_days: int = MIN_HISTORY_DAYS,
) -> pl.DataFrame:
    """station_id, station_type, special_day, season, lr = mean over origins of
    log1p(y) - log1p(point), for clean log rows on special days dated before `cutoff`.
    With `first_seen` (station_id, first_date) and a `cutoff` column in the log, rows whose
    station had less than `min_history_days` of data at that forecast's cutoff are dropped."""
    if "exclude" in log.columns:
        log = log.filter(pl.col("exclude").is_null())
    if first_seen is not None and "cutoff" in log.columns:
        log = log.join(
            first_seen.select("station_id", "first_date"), on="station_id", how="left"
        ).filter((pl.col("cutoff") - pl.col("first_date")).dt.total_days() >= min_history_days)
    return (
        log.filter(
            (pl.col("date") < cutoff) & pl.col("y").is_not_null() & pl.col(point).is_not_null()
        )
        .with_columns(special_day().alias("special_day"))
        .filter(pl.col("special_day").is_not_null())
        .with_columns(
            _season().alias("season"),
            (pl.col("y").log1p() - pl.col(point).log1p()).alias("lr"),
        )
        .group_by("station_id", "special_day", "season")
        .agg(pl.col("station_type").drop_nulls().first(), pl.col("lr").mean())
    )


def factors(
    log: pl.DataFrame,
    point: str,
    cutoff: date,
    k: float = K_SHRINK,
    first_seen: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """station_id, special_day, log_f, n_years (station) and the shrinkage target.
    Stations absent from the log (or too young) get the station-type factor in `apply`."""
    r = station_year_ratios(log, point, cutoff, first_seen)
    if r.height == 0:
        return pl.DataFrame(
            schema={
                "station_id": pl.Int64,
                "special_day": pl.String,
                "log_f": pl.Float64,
                "n_years": pl.UInt32,
            }
        )
    net = r.group_by("special_day").agg(pl.col("lr").median().alias("lf_net"))
    typ = (
        r.filter(pl.col("station_type").is_not_null())
        .group_by("special_day", "station_type")
        .agg(pl.col("lr").median().alias("lf_type"))
    )
    st = (
        r.group_by("station_id", "special_day")
        .agg(
            pl.col("station_type").drop_nulls().first(),
            pl.col("lr").median().alias("lf_station"),
            pl.col("season").n_unique().alias("n_years"),
        )
        .join(net, on="special_day", how="left")
        .join(typ, on=["special_day", "station_type"], how="left")
        .with_columns(pl.coalesce("lf_type", "lf_net").alias("lf_target"))
    )
    w = pl.col("n_years") / (pl.col("n_years") + k)
    return st.with_columns(
        (w * pl.col("lf_station") + (1 - w) * pl.col("lf_target")).alias("log_f")
    ).select("station_id", "special_day", "station_type", "log_f", "n_years", "lf_target")


def targets(f: pl.DataFrame) -> pl.DataFrame:
    """special_day, station_type (null = network), log_f for stations without history."""
    return f.select("special_day", "station_type", pl.col("lf_target").alias("lf_fallback")).unique(
        ["special_day", "station_type"]
    )


def apply(
    rows: pl.DataFrame, f: pl.DataFrame, cols: tuple[str, ...] = ("point", "lo", "hi")
) -> pl.DataFrame:
    """Multiply `cols` by the factor on special days; adds `special_day` and `adjust`
    (1.0 on other dates). Stations without their own factor get their station type's
    (else the network median of the type targets)."""
    out = rows.with_columns(special_day().alias("special_day"))
    if f.height == 0:
        return out.with_columns(pl.lit(1.0).alias("adjust"))
    tg = targets(f)
    net = tg.group_by("special_day").agg(pl.col("lf_fallback").median().alias("lf_net"))
    out = (
        out.join(
            f.select("station_id", "special_day", "log_f"),
            on=["station_id", "special_day"],
            how="left",
        )
        .join(
            tg.filter(pl.col("station_type").is_not_null()),
            on=["special_day", "station_type"],
            how="left",
        )
        .join(net, on="special_day", how="left")
        .with_columns(
            pl.when(pl.col("special_day").is_null())
            .then(1.0)
            .otherwise(pl.coalesce("log_f", "lf_fallback", "lf_net", pl.lit(0.0)).exp())
            .alias("adjust")
        )
        .drop("log_f", "lf_fallback", "lf_net")
    )
    return out.with_columns(
        [(pl.col(c) * pl.col("adjust")).alias(c) for c in cols if c in out.columns]
    )
