"""Recent station level at a forecast origin (option A: closures, works, reopenings).

A station closed for works, partly closed, or just reopened sits far from its usual level.
Calendar features cannot see that; the station's recent share of network entries can.
At an origin o, from station-days strictly before o:
    share_ratio_7    station share of network entries over [o-7, o) / share over [o-365, o)
    share_ratio_28   same over [o-28, o)
    missing_share_28 share of the 28 days before o with no published count for the station
Shares use only days where the station has a count (network total = all stations that
day), so network-wide dips (holidays, strikes) cancel out. No quality flag is used: flags
come from a centred rolling median that looks after the date.

Training rows need the same features computed at their own (pseudo-)origin, so the
training set is stacked: pseudo-origins every `step_months` from `first` up to the
origin, each with the rows [o', min(o' + horizon, origin)), its features at o', the
horizon (days since o', 1 = o') and short_pass_share frozen at o' as in the test.
"""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from idf_crowding.models.frozen import add_months

LEVEL_FEATURES = ["horizon", "share_ratio_7", "share_ratio_28", "missing_share_28"]


def network_totals(data: pl.DataFrame) -> pl.DataFrame:
    return data.group_by("date").agg(pl.col("n_entries").sum().alias("network"))


def level_features(
    data: pl.DataFrame, network: pl.DataFrame, origin: date, long_days: int = 365
) -> pl.DataFrame:
    """station_id x (share_ratio_7, share_ratio_28, missing_share_28) at `origin`."""
    past = data.filter(
        pl.col("date").is_between(origin - timedelta(days=long_days), origin, closed="left")
    ).join(network, on="date", how="left")
    has = pl.col("n_entries").is_not_null()

    def share(days: int) -> pl.Expr:
        recent = has & (pl.col("date") >= origin - timedelta(days=days))
        return pl.col("n_entries").filter(recent).sum() / pl.col("network").filter(recent).sum()

    long_share = pl.col("n_entries").filter(has).sum() / pl.col("network").filter(has).sum()
    last28 = pl.col("date") >= origin - timedelta(days=28)
    return past.group_by("station_id").agg(
        (share(7) / long_share).alias("share_ratio_7"),
        (share(28) / long_share).alias("share_ratio_28"),
        (
            pl.col("n_entries").filter(last28).is_null().sum()
            / pl.max_horizontal(pl.lit(1), (pl.col("date").filter(last28)).count())
        )
        .cast(pl.Float64)
        .alias("missing_share_28"),
    )


def with_level(
    rows: pl.DataFrame, data: pl.DataFrame, network: pl.DataFrame, origin: date
) -> pl.DataFrame:
    """Add horizon and the level features at `origin` to rows dated >= origin."""
    return rows.with_columns(
        ((pl.col("date") - pl.lit(origin)).dt.total_days() + 1).cast(pl.Int32).alias("horizon")
    ).join(level_features(data, network, origin), on="station_id", how="left")


def pseudo_origins(first: date, origin: date, step_months: int) -> list[date]:
    out, o = [], first
    while o < origin:
        out.append(o)
        o = add_months(o, step_months)
    return out


def stacked_training(
    data: pl.DataFrame,
    clean: pl.DataFrame,
    origin: date,
    horizon: int,
    first: date,
    step_months: int = 2,
) -> pl.DataFrame:
    """Clean training rows before `origin`, one block per pseudo-origin (see module doc).
    `data` = all rows (for features), `clean` = rows allowed as training targets."""
    past = data.filter(pl.col("date") < origin)
    network = network_totals(past)
    daily_share = past.group_by("date").agg(pl.col("short_pass_share").first()).sort("date")
    blocks = []
    for o in pseudo_origins(first, origin, step_months):
        end = min(o + timedelta(days=horizon), origin)
        rows = clean.filter(pl.col("date").is_between(o, end, closed="left"))
        if rows.height == 0:
            continue
        before = daily_share.filter(pl.col("date") < o)
        if before.height:
            rows = rows.with_columns(
                pl.lit(before["short_pass_share"][-1]).alias("short_pass_share")
            )
        blocks.append(with_level(rows, data, network, o))
    return pl.concat(blocks)
