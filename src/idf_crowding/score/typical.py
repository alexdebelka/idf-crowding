"""Typical week: daily level x hourly profile per Place and Day type, Reference level, score.

Rules (public: docs/data-quality.md "Score"):
1. Window = the last `window_days` of available data.
2. Usable station-days: in the window, entries present, no quality flag, a day type, and
   not a network-abnormal JOHV/SAHV day (network_ratio < disruption_ratio: strikes, snow).
3. Place days: sum of member stations on dates where every member is usable.
4. Daily level = mean entries per Place x Day type; < min_days days -> low confidence.
5. Hourly profile = mean of the last `n_quarters` quarterly profiles (hours a quarter does
   not report count as 0), renormalised to sum 1. Place profile = member profiles weighted
   by member daily level. Expected entries(hour) = daily level x share.
6. Reference level = p95 of hourly entries on actual usable days (daily entries x that
   day's day-type profile), public holidays and bridge days excluded. One per Place.
7. Crowding score = 100 x expected / reference (> 100 allowed); bands from config.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import polars as pl

DAY_TYPES = ["JOHV", "JOVS", "SAHV", "SAVS", "DIJFP"]
# Operating day runs 04:00 -> 03:59 (validation doc): hours listed in that order.
OPERATING_HOURS = list(range(4, 24)) + list(range(0, 4))


@dataclass(frozen=True)
class ScoreSettings:
    window_days: int = 365
    min_days: int = 8
    n_quarters: int = 4
    disruption_ratio: float = 0.8
    disruption_day_types: tuple[str, ...] = ("JOHV", "SAHV")
    reference_quantile: float = 0.95
    # upper bounds (exclusive) of each band; above the last one: "very_busy"
    bands: tuple[tuple[float, str], ...] = ((40, "quiet"), (70, "moderate"), (100, "busy"))
    slot_hours: tuple[int, int] = (6, 22)  # best slots start at 06:00 .. 21:00
    n_best: int = 3
    peak_windows: tuple[tuple[int, int], ...] = ((6, 12), (15, 21))
    peak_radius: int = 2
    modes: tuple[str, ...] = ("Metro", "RapidTransit")
    extra_lines: tuple[str, ...] = ("C01843",)  # T4 (counted per stop, validation doc)
    # reference ZdC -> data ZdC (lines, scope) and optional display name of the data ZdC
    zdc_aliases: tuple[tuple[int, int, str | None], ...] = ()

    @classmethod
    def from_config(cls, c: dict[str, Any]) -> ScoreSettings:
        b = c.get("bands", {})
        bands = (
            tuple((float(b[k]), k) for k in ("quiet", "moderate", "busy") if k in b) or cls.bands
        )
        return cls(
            window_days=c.get("window_days", cls.window_days),
            min_days=c.get("min_days", cls.min_days),
            n_quarters=c.get("n_quarters", cls.n_quarters),
            disruption_ratio=c.get("disruption_ratio", cls.disruption_ratio),
            reference_quantile=c.get("reference_quantile", cls.reference_quantile),
            bands=bands,
            slot_hours=tuple(c.get("slot_hours", cls.slot_hours)),
            n_best=c.get("n_best", cls.n_best),
            peak_windows=tuple(tuple(w) for w in c.get("peak_windows", cls.peak_windows)),
            peak_radius=c.get("peak_radius", cls.peak_radius),
            modes=tuple(c.get("modes", cls.modes)),
            extra_lines=tuple(c.get("extra_lines", cls.extra_lines)),
            zdc_aliases=tuple(
                (int(a["from"]), int(a["to"]), a.get("name")) for a in c.get("zdc_aliases", [])
            ),
        )


def window(features: pl.DataFrame, days: int) -> tuple[date, date]:
    end = features.filter(pl.col("n_entries").is_not_null())["date"].max()
    return end - timedelta(days=days - 1), end


def usable_days(features: pl.DataFrame, s: ScoreSettings, start: date, end: date) -> pl.DataFrame:
    abnormal = pl.col("day_type").is_in(s.disruption_day_types) & (
        pl.col("network_ratio") < s.disruption_ratio
    )
    return features.filter(
        pl.col("date").is_between(start, end),
        pl.col("n_entries").is_not_null(),
        pl.col("quality_flag").is_null(),
        pl.col("day_type").is_not_null(),
        ~abnormal.fill_null(False),
    ).select(
        "station_id",
        "date",
        "day_type",
        "n_entries",
        (pl.col("is_public_holiday").fill_null(False) | pl.col("is_bridge").fill_null(False)).alias(
            "is_holiday"
        ),
    )


def place_days(days: pl.DataFrame, members: pl.DataFrame) -> pl.DataFrame:
    """Sum member stations per Place x date, only where every member is usable."""
    size = members.group_by("place_id").agg(pl.len().alias("n_members"))
    return (
        days.join(members, on="station_id")
        .group_by("place_id", "date")
        .agg(
            pl.col("n_entries").sum(),
            pl.len().alias("n"),
            pl.col("day_type").first(),
            pl.col("is_holiday").first(),
        )
        .join(size, on="place_id")
        .filter(pl.col("n") == pl.col("n_members"))
        .drop("n", "n_members")
    )


def daily_levels(days: pl.DataFrame, key: str, min_days: int) -> pl.DataFrame:
    return (
        days.group_by(key, "day_type")
        .agg(pl.col("n_entries").mean().alias("daily_entries"), pl.len().alias("n_days"))
        .with_columns((pl.col("n_days") < min_days).alias("low_confidence"))
    )


def hourly_profiles(profiles: pl.DataFrame, periods: list[str]) -> pl.DataFrame:
    """Station x day_type x hour share: mean over `periods` (missing hours = 0), sums to 1."""
    p = profiles.filter(pl.col("period").is_in(periods))
    keys = p.select("period", "station_id", "day_type").unique()
    hours = pl.DataFrame({"hour": pl.Series(range(24), dtype=p.schema["hour"])})
    full = keys.join(hours, how="cross").join(
        p.select("period", "station_id", "day_type", "hour", "share"),
        on=["period", "station_id", "day_type", "hour"],
        how="left",
    )
    return (
        full.with_columns(pl.col("share").fill_null(0.0))
        .group_by("station_id", "day_type", "hour")
        .agg(pl.col("share").mean(), pl.col("period").n_unique().alias("n_quarters"))
        .with_columns(pl.col("share") / pl.col("share").sum().over("station_id", "day_type"))
        .filter(pl.col("share").is_not_nan())
    )


def place_profiles(
    station_prof: pl.DataFrame, station_levels: pl.DataFrame, members: pl.DataFrame
) -> pl.DataFrame:
    """Place x day_type x hour share = member shares weighted by member daily level."""
    w = station_levels.select("station_id", "day_type", pl.col("daily_entries").alias("w"))
    has_prof = station_prof.select("station_id", "day_type").unique()
    total = (
        has_prof.join(w, on=["station_id", "day_type"])
        .join(members, on="station_id")
        .group_by("place_id", "day_type")
        .agg(pl.col("w").sum().alias("w_total"))
    )
    return (
        station_prof.join(members, on="station_id")
        .join(w, on=["station_id", "day_type"])
        .group_by("place_id", "day_type", "hour")
        .agg((pl.col("share") * pl.col("w")).sum().alias("sw"))
        .join(total, on=["place_id", "day_type"])
        .with_columns((pl.col("sw") / pl.col("w_total")).alias("share"))
        .with_columns(pl.col("share") / pl.col("share").sum().over("place_id", "day_type"))
        .filter(pl.col("share").is_not_nan())
        .select("place_id", "day_type", "hour", "share")
    )


def reference_levels(days: pl.DataFrame, prof: pl.DataFrame, q: float) -> pl.DataFrame:
    """One Reference level per Place: quantile q of hourly entries on actual normal days."""
    return (
        days.filter(~pl.col("is_holiday"))
        .join(prof, on=["place_id", "day_type"])
        .with_columns((pl.col("n_entries") * pl.col("share")).alias("hourly"))
        .group_by("place_id")
        .agg(pl.col("hourly").quantile(q, interpolation="linear").alias("reference_level"))
        .filter(pl.col("reference_level") > 0)
    )


def band_expr(score: pl.Expr, bands: tuple[tuple[float, str], ...]) -> pl.Expr:
    expr = pl.lit("very_busy")
    for upper, name in reversed(bands):
        expr = pl.when(score < upper).then(pl.lit(name)).otherwise(expr)
    return expr


def typical_week(
    days: pl.DataFrame,
    station_days: pl.DataFrame,
    station_prof: pl.DataFrame,
    members: pl.DataFrame,
    s: ScoreSettings,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Returns (hourly, levels, references). hourly: place_id, day_type, hour, share,
    expected_entries, score, band. `days` are Place days, `station_days` station days."""
    levels = daily_levels(days, "place_id", s.min_days)
    st_levels = daily_levels(station_days, "station_id", 1)
    prof = place_profiles(station_prof, st_levels, members)
    refs = reference_levels(days, prof, s.reference_quantile)
    score = 100 * pl.col("expected_entries") / pl.col("reference_level")
    hourly = (
        levels.join(prof, on=["place_id", "day_type"])
        .join(refs, on="place_id")
        .with_columns((pl.col("daily_entries") * pl.col("share")).alias("expected_entries"))
        .with_columns(score.alias("score"))
        .with_columns(band_expr(pl.col("score"), s.bands).alias("band"))
        .select("place_id", "day_type", "hour", "share", "expected_entries", "score", "band")
        .sort("place_id", "day_type", "hour")
    )
    return hourly, levels, refs


def best_slots(expected: dict[int, float], s: ScoreSettings) -> dict[str, Any]:
    """3 quietest hours within the slot window, and the quietest hour within ±radius of
    each peak (peak = busiest hour of each peak window)."""
    lo, hi = s.slot_hours
    day = [h for h in range(lo, hi) if h in expected]
    quietest = sorted(day, key=lambda h: (expected[h], h))[: s.n_best]
    around = []
    for a, b in s.peak_windows:
        cand = [h for h in range(a, b) if h in expected]
        if not cand:
            continue
        peak = max(cand, key=lambda h: (expected[h], -h))
        near = [
            h
            for h in range(peak - s.peak_radius, peak + s.peak_radius + 1)
            if h != peak and lo <= h < hi and h in expected
        ]
        if not near:
            continue
        alt = min(near, key=lambda h: (expected[h], abs(h - peak), h))
        around.append({"peak": peak, "alternative": alt})
    return {"quietest": quietest, "around_peaks": around}
