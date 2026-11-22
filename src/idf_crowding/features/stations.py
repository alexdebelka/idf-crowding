"""Station type from the working-day hourly profile (k-means, k = 3).

Uses the last 4 published quarters of JOHV profiles. Clusters are named by the share of
weekday entries between 7 and 10 h: highest = "origin" (outer ring, morning departures),
lowest = "destination" (Paris and business districts, evening peak), middle = "mixed".
Stations without a profile in all 4 quarters (new stations, stations missing from some
published files) are assigned to the nearest cluster centre using their own profile: the mean
over the clustering periods they do have, else their most recent period in `fallback_periods`.
They do not move the centres. Stations with no profile at all get null.
"""

from __future__ import annotations

import re

import numpy as np
import polars as pl

from idf_crowding.viz.eda import cluster_profiles, profile_matrix

NAMES = ["origin", "mixed", "destination"]
QUARTER = re.compile(r"^\d{4}Q[1-4]$")
PERIOD = re.compile(r"^\d{4}(Q[1-4]|S[12])$")


def last_quarters(profiles: pl.DataFrame, n: int = 4) -> list[str]:
    periods = sorted(p for p in profiles["period"].unique().to_list() if QUARTER.match(p))
    return periods[-n:]


def partial_profiles(
    profiles: pl.DataFrame, periods: list[str], fallback_periods: list[str], exclude: list[int]
) -> tuple[np.ndarray, list[int]]:
    """station x 24 hourly shares (JOHV) for stations not in `exclude`: mean over the
    `periods` they have; if none, their most recent period in `fallback_periods`."""
    p = profiles.filter(
        (pl.col("day_type") == "JOHV") & ~pl.col("station_id").is_in(pl.Series(exclude).implode())
    )
    order = {q: i for i, q in enumerate(sorted(set(fallback_periods) | set(periods), key=_end))}
    inside = p.filter(pl.col("period").is_in(periods))
    have = inside["station_id"].unique()
    latest = (
        p.filter(
            pl.col("period").is_in(fallback_periods) & ~pl.col("station_id").is_in(have.implode())
        )
        .with_columns(pl.col("period").replace_strict(order, default=-1).alias("rank"))
        .filter(pl.col("rank") == pl.col("rank").max().over("station_id"))
        .drop("rank")
    )
    both = pl.concat([inside, latest])
    if both.height == 0:
        return np.zeros((0, 24)), []
    wide = (
        both.group_by("station_id", "hour")
        .agg(pl.col("share").mean())
        .pivot(on="hour", index="station_id", values="share")
        .fill_null(0)
        .sort("station_id")
    )
    cols = [str(h) for h in range(24)]
    for c in cols:
        if c not in wide.columns:
            wide = wide.with_columns(pl.lit(0.0).alias(c))
    m = wide.select(cols).to_numpy()
    ok = m.sum(axis=1) > 0
    m = m[ok] / m[ok].sum(axis=1, keepdims=True)
    return m, [i for i, keep in zip(wide["station_id"].to_list(), ok, strict=True) if keep]


def _end(period: str) -> tuple[int, int]:
    """Sort key: (year, last month) of a period such as 2025Q3 or 2024S1."""
    year, part = int(period[:4]), period[4:]
    return year, int(part[1]) * (3 if part[0] == "Q" else 6)


def station_types(
    profiles: pl.DataFrame,
    k: int = 3,
    seed: int = 0,
    periods: list[str] | None = None,
    fallback_periods: list[str] | None = None,
) -> pl.DataFrame:
    """Station types from `periods` (default: the last 4 published quarters). Stations
    without a profile in all of them get the nearest centre (see module docstring);
    `fallback_periods` defaults to all published periods."""
    periods = periods if periods is not None else last_quarters(profiles)
    if fallback_periods is None:
        fallback_periods = [q for q in profiles["period"].unique().to_list() if PERIOD.match(q)]
    m, ids = profile_matrix(profiles, periods, "JOHV")
    labels, centers = cluster_profiles(m, k, seed)
    am = centers[:, 7:10].sum(axis=1)
    rank = np.argsort(-am)  # cluster index sorted by AM share, descending
    name_of = {int(c): NAMES[i] for i, c in enumerate(rank)}
    pm, pids = partial_profiles(profiles, periods, fallback_periods, ids)
    if pids:
        d = ((pm[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        labels = np.concatenate([labels, d.argmin(axis=1)])
        m = np.vstack([m, pm])
        ids = ids + pids
    return pl.DataFrame(
        {
            "station_id": ids,
            "station_type": [name_of[int(x)] for x in labels],
            "am_share_7_10": m[:, 7:10].sum(axis=1),
        }
    ).with_columns(pl.lit(",".join(periods)).alias("station_type_periods"))
