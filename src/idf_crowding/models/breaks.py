"""Counting breaks: a station whose recorded entries change level on one day for a reason
that is not demand (a change in what the gates count), so the history before the break is
on another scale.

Known break (docs/data-quality.md "Counting breaks"): on 2026-01-13 the SNCF stops of Gare du
Nord, Haussmann Saint-Lazare and Magenta jumped to about 1.8x, 1.8x and 2.5x their share of
network entries, in every ticket group, from one day to the next; 2026-01-12 is in between.

Rule, at a data cutoff c (only data dated < c is used, so no leakage):
- factor = median share of network entries on working days (JOHV, JOVS) in
  [settled, min(c, settled + window)) / the same in [start - window, start);
- known only with at least `min_days` such days after the break;
- when known: entries dated before `start` are multiplied by the factor (put on the new
  scale) and the days in [start, settled) are left out;
- when not known yet (cutoff before or just after the break): data unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import polars as pl

from idf_crowding.config import load_config

WORKING_DAYS = ["JOHV", "JOVS"]


@dataclass(frozen=True)
class Break:
    station_id: int
    start: date  # first day not on the old scale
    settled: date  # first day fully on the new scale


def from_config() -> list[Break]:
    rows = load_config().get("breaks", {}).get("stations", [])
    return [Break(int(s), date.fromisoformat(a), date.fromisoformat(b)) for s, a, b in rows]


def _shares(data: pl.DataFrame, ids: list[int], lo: date, hi: date) -> pl.DataFrame:
    d = data.filter(pl.col("date").is_between(lo, hi, closed="left"))
    net = d.group_by("date").agg(pl.col("n_entries").sum().alias("_net"))
    return (
        d.filter(pl.col("station_id").is_in(ids) & pl.col("day_type").is_in(WORKING_DAYS))
        .join(net, on="date")
        .select("station_id", "date", (pl.col("n_entries") / pl.col("_net")).alias("share"))
        .drop_nulls()
    )


def factors(
    data: pl.DataFrame,
    breaks: list[Break],
    cutoff: date,
    window_days: int = 91,
    min_days: int = 10,
) -> dict[int, float]:
    """station_id -> factor for the breaks whose new level is known at `cutoff`."""
    out: dict[int, float] = {}
    w = timedelta(days=window_days)
    for b in breaks:
        if cutoff <= b.settled:
            continue
        after = _shares(data, [b.station_id], b.settled, min(cutoff, b.settled + w))
        before = _shares(data, [b.station_id], b.start - w, b.start)
        if after.height < min_days or before.height < min_days:
            continue
        pre = before["share"].median()
        if pre and pre > 0:
            out[b.station_id] = float(after["share"].median() / pre)
    return out


def apply(
    data: pl.DataFrame,
    breaks: list[Break],
    cutoff: date,
    exclude_col: str | None = "exclude",
) -> tuple[pl.DataFrame, dict[int, float]]:
    """Data on the new scale for the breaks known at `cutoff` (see module rule). The days in
    [start, settled) get exclude = "count_break" when `exclude_col` is given, else a null
    n_entries. Returns (data, factors used)."""
    f = factors(data, breaks, cutoff)
    if not f:
        return data, f
    known = [b for b in breaks if b.station_id in f]
    factor = pl.lit(None, pl.Float64)
    ramp = pl.lit(False)
    for b in known:
        sid = pl.col("station_id") == b.station_id
        factor = (
            pl.when(sid & (pl.col("date") < b.start))
            .then(pl.lit(f[b.station_id]))
            .otherwise(factor)
        )
        ramp = ramp | (sid & pl.col("date").is_between(b.start, b.settled, closed="left"))
    dtype = data.schema["n_entries"]
    scaled = (
        pl.when(factor.is_not_null())
        .then((pl.col("n_entries") * factor).round(0))
        .otherwise(pl.col("n_entries"))
        .cast(dtype)
    )
    out = data.with_columns(scaled.alias("n_entries"))
    if exclude_col and exclude_col in out.columns:
        out = out.with_columns(
            pl.when(ramp & pl.col(exclude_col).is_null())
            .then(pl.lit("count_break"))
            .otherwise(pl.col(exclude_col))
            .alias(exclude_col)
        )
    else:
        out = out.with_columns(
            pl.when(ramp)
            .then(pl.lit(None, dtype))
            .otherwise(pl.col("n_entries"))
            .alias("n_entries")
        )
    return out, f
