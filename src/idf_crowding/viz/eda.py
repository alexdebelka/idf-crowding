"""Tables behind the Phase 3 exploration notebook (notebooks/01_exploration.ipynb).

Plotting stays in the notebook; every number it shows comes from a function here.
Day types without a holiday calendar (Phase 4) are approximated from the weekday only.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from idf_crowding.clean.quality import network_daily

HOURS = list(range(24))
DAY_TYPES = ["JOHV", "JOVS", "SAHV", "SAVS", "DIJFP"]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def network_series(daily: pl.DataFrame) -> pl.DataFrame:
    """Daily network total and its centred 7-day mean."""
    return (
        daily.group_by("date")
        .agg(pl.col("n_entries").sum().alias("total"))
        .sort("date")
        .with_columns(pl.col("total").rolling_mean(7, center=True).alias("total_7d"))
    )


def normal_days(daily: pl.DataFrame, low: float = 0.8, high: float = 1.25) -> pl.Series:
    """Dates whose network total is close to its usual weekday level (drops strikes,
    public holidays and holiday weeks without needing a calendar)."""
    net = network_daily(daily)
    return net.filter(pl.col("network_ratio").is_between(low, high))["date"]


def weekday_index(
    daily: pl.DataFrame, years: list[int] | None = None, totals: pl.DataFrame | None = None
) -> pl.DataFrame:
    """Per year: mean network entries on each weekday / mean of Tue-Thu (normal days).

    `totals` (date, total) replaces the network total, e.g. a total without one ticket
    group; normal days are still chosen from `daily`."""
    net = totals if totals is not None else network_series(daily)
    net = net.filter(pl.col("date").is_in(normal_days(daily).implode()))
    net = net.with_columns(
        pl.col("date").dt.year().alias("year"), pl.col("date").dt.weekday().alias("weekday")
    )
    if years:
        net = net.filter(pl.col("year").is_in(years))
    by = net.group_by("year", "weekday").agg(pl.col("total").mean())
    mid = (
        by.filter(pl.col("weekday").is_in([2, 3, 4]))
        .group_by("year")
        .agg(pl.col("total").mean().alias("midweek"))
    )
    return (
        by.join(mid, on="year")
        .with_columns((pl.col("total") / pl.col("midweek")).alias("index"))
        .select("year", "weekday", "index")
        .sort("year", "weekday")
    )


def ticket_totals(tickets: pl.LazyFrame, exclude: list[str]) -> pl.DataFrame:
    """Daily network validations without some ticket groups (date, total)."""
    return (
        tickets.filter(~pl.col("ticket_group").is_in(exclude))
        .group_by("date")
        .agg(pl.col("n_validations").sum().alias("total"))
        .sort("date")
        .collect()
    )


def monthly_index(daily: pl.DataFrame, years: list[int]) -> pl.DataFrame:
    """Per year: mean daily network entries per month / that year's mean."""
    net = network_series(daily).with_columns(
        pl.col("date").dt.year().alias("year"), pl.col("date").dt.month().alias("month")
    )
    net = net.filter(pl.col("year").is_in(years))
    m = net.group_by("year", "month").agg(pl.col("total").mean())
    return (
        m.with_columns((pl.col("total") / pl.col("total").mean().over("year")).alias("index"))
        .select("year", "month", "index")
        .sort("year", "month")
    )


def profile_matrix(
    profiles: pl.DataFrame, periods: list[str], day_type: str
) -> tuple[np.ndarray, list[int]]:
    """station x 24 matrix of hourly shares, averaged over `periods` (stations present in
    all of them). Rows sum to 1."""
    p = profiles.filter(pl.col("period").is_in(periods) & (pl.col("day_type") == day_type))
    keep = (
        p.group_by("station_id")
        .agg(pl.col("period").n_unique().alias("n"))
        .filter(pl.col("n") == len(periods))["station_id"]
    )
    wide = (
        p.filter(pl.col("station_id").is_in(keep.implode()))
        .group_by("station_id", "hour")
        .agg(pl.col("share").mean())
        .pivot(on="hour", index="station_id", values="share")
        .fill_null(0)
        .sort("station_id")
    )
    cols = [str(h) for h in HOURS]
    for c in cols:
        if c not in wide.columns:
            wide = wide.with_columns(pl.lit(0.0).alias(c))
    m = wide.select(cols).to_numpy()
    m = m / m.sum(axis=1, keepdims=True)
    return m, wide["station_id"].to_list()


def station_heatmap(profiles: pl.DataFrame, station_id: int, periods: list[str]) -> np.ndarray:
    """day type (DAY_TYPES order) x 24 hourly shares for one station."""
    rows = []
    for dt in DAY_TYPES:
        m, ids = profile_matrix(profiles, periods, dt)
        rows.append(m[ids.index(station_id)] if station_id in ids else np.full(24, np.nan))
    return np.vstack(rows)


def weighted_profile(m: np.ndarray, ids: list[int], weights: dict[int, float]) -> np.ndarray:
    """Network profile: station profiles weighted by their daily entries."""
    w = np.array([weights.get(i, 0.0) for i in ids])
    return (m * w[:, None]).sum(axis=0) / w.sum()


def peak_share(profile: np.ndarray, hours: range) -> float:
    return float(profile[list(hours)].sum())


def mean_daily(daily: pl.DataFrame, year: int) -> dict[int, float]:
    """Mean daily entries per station over one year (normal days only)."""
    d = daily.filter(
        (pl.col("date").dt.year() == year) & pl.col("date").is_in(normal_days(daily).implode())
    )
    agg = d.group_by("station_id").agg(pl.col("n_entries").mean())
    return dict(agg.iter_rows())


def cluster_profiles(m: np.ndarray, k: int, seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """k-means on hourly shares. Returns (labels, centroids), clusters ordered by the hour
    of their centroid's peak so labels are stable across runs."""
    from sklearn.cluster import KMeans

    km = KMeans(n_clusters=k, n_init=20, random_state=seed).fit(m)
    order = np.argsort(km.cluster_centers_.argmax(axis=1), kind="stable")
    remap = {old: new for new, old in enumerate(order)}
    labels = np.array([remap[x] for x in km.labels_])
    return labels, km.cluster_centers_[order]


def choose_k(m: np.ndarray, ks: range, seed: int = 0) -> dict[int, float]:
    """Silhouette score per k."""
    from sklearn.metrics import silhouette_score

    return {k: float(silhouette_score(m, cluster_profiles(m, k, seed)[0])) for k in ks}
