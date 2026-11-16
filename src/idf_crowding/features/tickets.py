"""The 2025 ticket-change ramp: monthly share of `short_passes` in network validations.

From January 2025 magnetic tickets were replaced by contactless media that are counted,
so short passes went from ~1 % to ~17 % of validations over Jan-Jun 2025 and then levelled
off. The share per calendar month is the feature; dates after the last observed month get
the last observed value (the plateau), dates before the first month the first value.
"""

from __future__ import annotations

import polars as pl

GROUP = "short_passes"


def monthly_share(tickets: pl.LazyFrame) -> pl.DataFrame:
    month = pl.col("date").dt.truncate("1mo").alias("month")
    is_short = pl.col("ticket_group") == GROUP
    return (
        tickets.group_by(month)
        .agg(
            (pl.col("n_validations").filter(is_short).sum() / pl.col("n_validations").sum()).alias(
                "short_pass_share"
            )
        )
        .sort("month")
        .collect()
    )


def ramp_for_dates(dates: pl.DataFrame, shares: pl.DataFrame) -> pl.Series:
    """short_pass_share for each date (by month; forward/backward filled at the ends)."""
    d = dates.select("date").with_columns(pl.col("date").dt.truncate("1mo").alias("month"))
    out = d.join(shares, on="month", how="left").sort("date")
    first, last = shares["short_pass_share"][0], shares["short_pass_share"][-1]
    m0, m1 = shares["month"].min(), shares["month"].max()
    filled = out.with_columns(
        pl.when(pl.col("month") > m1)
        .then(pl.lit(last))
        .when(pl.col("month") < m0)
        .then(pl.lit(first))
        .otherwise(pl.col("short_pass_share"))
        .alias("short_pass_share")
    )
    return dates.select("date").join(
        filled.select("date", "short_pass_share"), on="date", how="left"
    )["short_pass_share"]
