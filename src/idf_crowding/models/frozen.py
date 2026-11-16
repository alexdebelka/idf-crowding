"""Features recomputed at a forecast origin from data before it only (no leakage).

`features_daily` computes `short_pass_share` and `station_type` with all published data,
including the test period of a backtest. At an origin (first day of the forecast window):
    short_pass_share  dates >= origin get the value of the last date before the origin
                      (the monthly share of the month before; past months are unchanged
                      because each month's share only uses that month's validations)
    station_type      k-means on the most recent profile periods that ended before the
                      origin, covering >= 12 months (4 quarters, or quarters + a semester)
"""

from __future__ import annotations

import re
from datetime import date

import polars as pl

from idf_crowding.features.stations import station_types

PERIOD = re.compile(r"^(\d{4})(Q[1-4]|S[12])$")


def period_bounds(period: str) -> tuple[date, date]:
    """(first day, first day after) of a profile period such as 2025Q3 or 2024S1."""
    m = PERIOD.match(period)
    if not m:
        raise ValueError(f"unknown profile period: {period!r}")
    year, part = int(m.group(1)), m.group(2)
    n = int(part[1])
    first_month = 3 * (n - 1) + 1 if part[0] == "Q" else 6 * (n - 1) + 1
    length = 3 if part[0] == "Q" else 6
    end_month = first_month + length
    end = date(year + (end_month - 1) // 12, (end_month - 1) % 12 + 1, 1)
    return date(year, first_month, 1), end


def add_months(d: date, months: int) -> date:
    i = d.year * 12 + (d.month - 1) + months
    return date(i // 12, i % 12 + 1, d.day)


def periods_before(periods: list[str], origin: date, months: int = 12) -> list[str]:
    """The most recent profile periods that ended before `origin`, newest first, until
    they cover at least `months` months (4 quarters; quarters + a semester before mid-2024,
    when profiles were published per semester). Returned oldest first."""
    ended = [p for p in periods if PERIOD.match(p) and period_bounds(p)[1] <= origin]
    ended.sort(key=lambda p: period_bounds(p)[1], reverse=True)
    keep, covered = [], 0
    for p in ended:
        a, b = period_bounds(p)
        if keep and b > period_bounds(keep[-1])[0]:
            continue  # overlaps a newer period already kept
        keep.append(p)
        covered += (b.year - a.year) * 12 + b.month - a.month
        if covered >= months:
            break
    return sorted(keep, key=lambda p: period_bounds(p)[0])


def freeze_short_pass_share(df: pl.DataFrame, origin: date) -> pl.DataFrame:
    """Dates >= origin get the last short_pass_share observed before the origin."""
    past = df.filter(pl.col("date") < origin)
    if past.height == 0:
        raise ValueError(f"no data before origin {origin}")
    last = past.sort("date")["short_pass_share"][-1]
    return df.with_columns(
        pl.when(pl.col("date") >= origin)
        .then(pl.lit(last))
        .otherwise(pl.col("short_pass_share"))
        .alias("short_pass_share")
    )


def frozen_station_types(
    profiles: pl.DataFrame, origin: date, months: int = 12, min_periods: int = 2
) -> pl.DataFrame:
    periods = periods_before(profiles["period"].unique().to_list(), origin, months)
    if len(periods) < min_periods:
        raise ValueError(f"only {len(periods)} profile periods before {origin}: {periods}")
    return station_types(profiles, periods=periods)


def apply_frozen(df: pl.DataFrame, origin: date, profiles: pl.DataFrame) -> pl.DataFrame:
    """Replace short_pass_share, station_type and am_share_7_10 by their values at origin."""
    types = frozen_station_types(profiles, origin)
    out = freeze_short_pass_share(df, origin).drop("station_type", "am_share_7_10", strict=False)
    return out.join(types.drop("station_type_periods"), on="station_id", how="left")
