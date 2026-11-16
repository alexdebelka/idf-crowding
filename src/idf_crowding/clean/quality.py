"""Data-quality flags for the harmonized validation tables (Phase 2).

Outputs in data/processed/quality/:
    period_summary.parquet     one row per raw source file kept or dropped
    station_day_flags.parquet  station-days that are missing or abnormal vs their own weekday
    level_shifts.parquet       station-months whose level jumps vs the network trend
    report.md                  human summary (numbers only, regenerated each run)

Flags never delete data: they are used later to exclude days from training and from the
Reference level. Thresholds are module constants, documented in docs/data-quality.md.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from idf_crowding.clean.build import Paths

ROLL_WEEKS = 9  # centred rolling median over the same weekday, in weeks
ROLL_MIN = 5
LOW_RATIO = 0.3  # station below 30 % of its usual level ...
HIGH_RATIO = 3.0  # ... or above 300 %
NETWORK_NORMAL = (0.7, 1.5)  # ... while the network as a whole is within this band
SHIFT_RATIO = 1.5  # station/network level change vs previous 3 months
SHIFT_SKIP = (date(2020, 3, 1), date(2021, 12, 31))  # COVID: too unstable to read shifts


def weekday_ratio(df: pl.DataFrame, value: str, by: list[str]) -> pl.DataFrame:
    """value / centred rolling median of the same weekday (per `by` group)."""
    keys = [*by, "weekday"]
    return (
        df.with_columns(pl.col("date").dt.weekday().alias("weekday"))
        .sort([*keys, "date"])
        .with_columns(
            pl.col(value)
            .cast(pl.Float64)
            .rolling_median(ROLL_WEEKS, min_samples=ROLL_MIN, center=True)
            .over(keys)
            .alias("expected")
        )
        .with_columns((pl.col(value) / pl.col("expected")).alias("ratio"))
        .drop("weekday")
    )


def network_daily(daily: pl.DataFrame) -> pl.DataFrame:
    net = daily.group_by("date").agg(pl.col("n_entries").sum())
    return weekday_ratio(net, "n_entries", []).select(
        "date", pl.col("ratio").alias("network_ratio")
    )


def station_day_flags(daily: pl.DataFrame) -> pl.DataFrame:
    """'missing': no row on a date inside the station's active span (network has data).
    'low' / 'high': far from the station's usual weekday level on a normal network day."""
    net = network_daily(daily)
    span = daily.group_by("station_id").agg(
        pl.col("date").min().alias("d0"), pl.col("date").max().alias("d1")
    )
    grid = (
        span.join(net.select("date"), how="cross")
        .filter(pl.col("date").is_between(pl.col("d0"), pl.col("d1")))
        .select("station_id", "date")
    )
    missing = grid.join(daily.select("station_id", "date"), on=["station_id", "date"], how="anti")
    missing = missing.with_columns(
        pl.lit("missing").alias("flag"),
        pl.lit(None, pl.Int64).alias("n_entries"),
        pl.lit(None, pl.Float64).alias("expected"),
        pl.lit(None, pl.Float64).alias("ratio"),
    )
    r = weekday_ratio(daily.select("station_id", "date", "n_entries"), "n_entries", ["station_id"])
    r = r.join(net, on="date", how="left")
    normal_net = pl.col("network_ratio").is_between(*NETWORK_NORMAL)
    odd = r.filter(
        normal_net & ((pl.col("ratio") < LOW_RATIO) | (pl.col("ratio") > HIGH_RATIO))
    ).with_columns(
        pl.when(pl.col("ratio") < LOW_RATIO)
        .then(pl.lit("low"))
        .otherwise(pl.lit("high"))
        .alias("flag")
    )
    cols = ["station_id", "date", "flag", "n_entries", "expected", "ratio"]
    return (
        pl.concat([missing.select(cols), odd.select(cols)])
        .join(net, on="date", how="left")
        .sort("station_id", "date")
    )


def level_shifts(daily: pl.DataFrame) -> pl.DataFrame:
    """Months where a station's mid-week level moves vs the network by more than SHIFT_RATIO
    compared with the mean of its previous 3 months (new lines, closures, ID changes)."""
    midweek = daily.filter(pl.col("date").dt.weekday().is_in([2, 3, 4]))
    month = pl.col("date").dt.truncate("1mo").alias("month")
    st = midweek.group_by("station_id", month).agg(pl.col("n_entries").mean().alias("level"))
    net = (
        midweek.group_by("date")
        .agg(pl.col("n_entries").sum())
        .group_by(month)
        .agg(pl.col("n_entries").mean().alias("net"))
    )
    rel = (
        st.join(net, on="month")
        .with_columns((pl.col("level") / pl.col("net")).alias("rel"))
        .sort("station_id", "month")
        .with_columns(
            pl.col("rel").shift(1).rolling_mean(3, min_samples=2).over("station_id").alias("prev")
        )
        .with_columns((pl.col("rel") / pl.col("prev")).alias("shift"))
    )
    skip = pl.col("month").is_between(*SHIFT_SKIP)
    big = (pl.col("shift") > SHIFT_RATIO) | (pl.col("shift") < 1 / SHIFT_RATIO)
    return (
        rel.filter(~skip & big)
        .select("station_id", "month", "level", "shift")
        .sort("station_id", "month")
    )


def period_summary(paths: Paths) -> pl.DataFrame:
    """One row per extracted source file, with whether its dates were kept."""
    kept = (
        pl.scan_parquet(paths.interim / "validations_daily_tickets.parquet")
        .select("source")
        .unique()
        .collect()["source"]
    )
    nb = pl.scan_parquet(paths.interim / "validations/nb/*.parquet")
    return (
        nb.group_by("period", "source")
        .agg(
            pl.len().alias("rows"),
            pl.col("mask_regime").first(),
            pl.col("is_masked").sum().alias("masked_rows"),
            pl.col("date").min().alias("first_date"),
            pl.col("date").max().alias("last_date"),
            pl.col("date").n_unique().alias("n_dates"),
            pl.col("zdc_id").is_null().sum().alias("rows_without_zdc"),
            pl.col("n_validations").sum().alias("n_validations"),
        )
        .collect()
        .with_columns(pl.col("source").is_in(kept.implode()).alias("kept"))
        .sort("period", "source")
    )


def _md_table(df: pl.DataFrame) -> str:
    head = "| " + " | ".join(df.columns) + " |"
    sep = "|" + "---|" * len(df.columns)
    rows = ["| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in df.rows()]
    return "\n".join([head, sep, *rows])


def run(paths: Paths) -> None:
    out = paths.processed / "quality"
    out.mkdir(parents=True, exist_ok=True)
    daily = pl.read_parquet(paths.processed / "station_daily.parquet")
    stations = pl.read_parquet(paths.processed / "stations.parquet")

    summary = period_summary(paths)
    flags = station_day_flags(daily)
    shifts = level_shifts(daily)
    for name, df in [
        ("period_summary", summary),
        ("station_day_flags", flags),
        ("level_shifts", shifts),
    ]:
        df.write_parquet(out / f"{name}.parquet")

    tickets = pl.scan_parquet(paths.interim / "validations_daily_tickets.parquet")
    total = tickets.select(pl.col("n_validations").sum()).collect().item()
    mapping = pl.read_parquet(paths.interim / "station_map.parquet").lazy()
    no_station = (
        tickets.join(mapping, on=["code_trns", "code_res", "code_arret"], how="left")
        .filter(pl.coalesce("station_id", "zdc_id").is_null())
        .select(pl.col("n_validations").sum())
        .collect()
        .item()
    )
    by_flag = flags.group_by("flag").agg(pl.len().alias("station_days")).sort("flag")
    worst = (
        flags.filter(pl.col("flag") != "missing")
        .group_by("station_id")
        .agg(pl.len().alias("odd_days"))
        .join(stations.select("station_id", "label"), on="station_id")
        .sort("odd_days", descending=True)
        .head(15)
    )
    lines = [
        "# Validation data quality report",
        "",
        "Generated by `idf-clean quality`. Numbers only; decisions are in docs/data-quality.md.",
        "",
        f"- Stations: {stations.height}; not in the current stop reference: "
        f"{stations.filter(~pl.col('in_reference')).height}",
        f"- Days: {daily['date'].min()} to {daily['date'].max()}, "
        f"{daily['date'].n_unique()} distinct",
        f"- Validations kept: {total:,}; without any station id (dropped): {no_station:,} "
        f"({no_station / total:.3%})",
        "",
        "## Source files",
        "",
        _md_table(
            summary.with_columns(pl.col("source").str.split("/").list.first().alias("origin")).drop(
                "source"
            )
        ),
        "",
        "## Station-day flags",
        "",
        _md_table(by_flag),
        "",
        "Stations with the most low/high days:",
        "",
        _md_table(worst),
        "",
        f"## Level shifts ({shifts.height} station-months, COVID months skipped)",
        "",
        _md_table(
            shifts.join(stations.select("station_id", "label"), on="station_id")
            .sort(pl.col("shift").log().abs(), descending=True)
            .head(25)
            .with_columns(pl.col("shift").round(2), pl.col("level").round(0))
        ),
        "",
    ]
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"quality: {flags.height} flagged station-days, {shifts.height} level shifts")
    print(f"report: {out / 'report.md'}")
