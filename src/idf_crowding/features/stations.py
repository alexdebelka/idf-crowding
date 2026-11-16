"""Station type from the working-day hourly profile (k-means, k = 3).

Uses the last 4 published quarters of JOHV profiles. Clusters are named by the share of
weekday entries between 7 and 10 h: highest = "origin" (outer ring, morning departures),
lowest = "destination" (Paris and business districts, evening peak), middle = "mixed".
Stations without a profile in all 4 quarters get null.
"""

from __future__ import annotations

import re

import numpy as np
import polars as pl

from idf_crowding.viz.eda import cluster_profiles, profile_matrix

NAMES = ["origin", "mixed", "destination"]
QUARTER = re.compile(r"^\d{4}Q[1-4]$")


def last_quarters(profiles: pl.DataFrame, n: int = 4) -> list[str]:
    periods = sorted(p for p in profiles["period"].unique().to_list() if QUARTER.match(p))
    return periods[-n:]


def station_types(
    profiles: pl.DataFrame, k: int = 3, seed: int = 0, periods: list[str] | None = None
) -> pl.DataFrame:
    """Station types from `periods` (default: the last 4 published quarters)."""
    periods = periods if periods is not None else last_quarters(profiles)
    m, ids = profile_matrix(profiles, periods, "JOHV")
    labels, centers = cluster_profiles(m, k, seed)
    am = centers[:, 7:10].sum(axis=1)
    rank = np.argsort(-am)  # cluster index sorted by AM share, descending
    name_of = {int(c): NAMES[i] for i, c in enumerate(rank)}
    return pl.DataFrame(
        {
            "station_id": ids,
            "station_type": [name_of[int(x)] for x in labels],
            "am_share_7_10": m[:, 7:10].sum(axis=1),
        }
    ).with_columns(pl.lit(",".join(periods)).alias("station_type_periods"))
