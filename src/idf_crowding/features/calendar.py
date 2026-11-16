"""Calendar features per date: weekday, holidays, school holidays, bridges, day type.

Rules (docs/data-quality.md, "Features"):
- Public holiday: date listed by calendrier.api.gouv.fr (metropole).
- School holiday: Zone C, location Paris, population "-" or "Élèves" (not "Enseignants");
  start_date/end_date are UTC instants of local midnights: the holiday covers local
  dates start <= d < end (end = day classes resume). Null outside the dataset's coverage
  (from 1 September of the first school year listed; Paris Zone C starts in 2017-2018).
- Bridge day ("pont"): a Monday before a Tuesday holiday or a Friday after a Thursday
  holiday, when it is not itself a holiday.
- Day type, as IDFM's profiles: DIJFP (Sunday, public holiday, bridge), SAVS/SAHV
  (Saturday in / outside school holidays), JOVS/JOHV (Mon-Fri in / outside).
- Era flags: COVID 2020-03-17 to 2021-06-30; pension-reform strike 2019-12-05 to
  2020-01-19.
Missing sources give null columns, never guessed values.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

COVID = (date(2020, 3, 17), date(2021, 6, 30))
STRIKE_2019 = (date(2019, 12, 5), date(2020, 1, 19))
SCHOOL_ZONE = "Zone C"
SCHOOL_LOCATION = "Paris"
SCHOOL_POPULATIONS = ("-", "Élèves")


def latest(folder: Path, pattern: str) -> Path | None:
    files = sorted(folder.glob(pattern)) if folder.is_dir() else []
    return files[-1] if files else None


def load_public_holidays(raw: Path) -> pl.DataFrame | None:
    path = latest(raw / "calendar/jours-feries-metropole", "*.json")
    if path is None:
        return None
    import json

    data = json.loads(path.read_text(encoding="utf-8"))
    return pl.DataFrame(
        {"date": list(data.keys()), "holiday_name": list(data.values())}
    ).with_columns(pl.col("date").str.to_date())


def school_intervals(df: pl.DataFrame) -> pl.DataFrame:
    """Raw calendrier-scolaire rows -> (start, end) local dates, end exclusive."""
    local = [
        pl.col(c)
        .str.to_datetime(time_zone="UTC")
        .dt.convert_time_zone("Europe/Paris")
        .dt.date()
        .alias(c)
        for c in ("start_date", "end_date")
    ]
    return (
        df.filter(
            (pl.col("zones") == SCHOOL_ZONE)
            & (pl.col("location") == SCHOOL_LOCATION)
            & pl.col("population").is_in(SCHOOL_POPULATIONS)
        )
        .with_columns(local)
        .select(
            pl.col("start_date").alias("start"),
            pl.col("end_date").alias("end"),
            "description",
            "annee_scolaire",
        )
        .unique()
        .sort("start")
    )


def load_school_holidays(raw: Path) -> pl.DataFrame | None:
    path = latest(raw / "calendar/calendrier-scolaire", "*.csv")
    if path is None:
        return None
    return school_intervals(pl.read_csv(path, separator=";", infer_schema_length=0))


def school_flag(dates: pl.DataFrame, intervals: pl.DataFrame | None) -> pl.Series:
    """True inside a holiday, False between holidays, null outside the coverage."""
    if intervals is None or intervals.height == 0:
        return pl.Series("is_school_holiday", [None] * dates.height, dtype=pl.Boolean)
    # covered: from 1 September of the first school year to the end of the last holiday
    first_year = int(min(intervals["annee_scolaire"].to_list())[:4])
    lo = date(first_year, 9, 1)
    hi = intervals["end"].max()
    hit = (
        dates.select("date")
        .join_where(intervals, pl.col("date") >= pl.col("start"), pl.col("date") < pl.col("end"))
        .select("date")
        .unique()
    )
    out = dates.select("date").with_columns(
        pl.col("date").is_in(hit["date"].implode()).alias("is_school_holiday")
    )
    inside = pl.col("date").is_between(lo, hi, closed="left")
    return out.select(
        pl.when(inside).then(pl.col("is_school_holiday")).otherwise(None).alias("is_school_holiday")
    )["is_school_holiday"]


def bridge_days(holidays: pl.Series) -> set[date]:
    """Mondays before a Tuesday holiday and Fridays after a Thursday holiday."""
    out = set()
    hol = set(holidays.to_list())
    for d in hol:
        wd = d.isoweekday()
        if wd == 2:
            out.add(date.fromordinal(d.toordinal() - 1))
        elif wd == 4:
            out.add(date.fromordinal(d.toordinal() + 1))
    return out - hol


def day_type(weekday: pl.Expr, holiday: pl.Expr, bridge: pl.Expr, school: pl.Expr) -> pl.Expr:
    """IDFM day type; null when a needed input is unknown."""
    sunday_like = (weekday == 7) | holiday | bridge
    return (
        pl.when(sunday_like)
        .then(pl.lit("DIJFP"))
        .when(weekday == 6)
        .then(pl.when(school).then(pl.lit("SAVS")).otherwise(pl.lit("SAHV")))
        .otherwise(pl.when(school).then(pl.lit("JOVS")).otherwise(pl.lit("JOHV")))
    )


def calendar_features(
    dates: list[date] | pl.Series,
    holidays: pl.DataFrame | None,
    school: pl.DataFrame | None,
) -> pl.DataFrame:
    """One row per date. Holiday-based columns are null when their source is missing."""
    df = pl.DataFrame({"date": pl.Series(dates, dtype=pl.Date)}).unique().sort("date")
    df = df.with_columns(
        pl.col("date").dt.weekday().alias("weekday"),
        pl.col("date").dt.month().alias("month"),
        pl.col("date").dt.ordinal_day().alias("day_of_year"),
        pl.col("date").dt.year().alias("year"),
        pl.col("date").is_between(*COVID).alias("is_covid"),
        pl.col("date").is_between(*STRIKE_2019).alias("is_strike_2019"),
    )
    if holidays is None:
        df = df.with_columns(
            pl.lit(None, pl.Boolean).alias("is_public_holiday"),
            pl.lit(None, pl.Boolean).alias("is_bridge"),
        )
    else:
        bridges = bridge_days(holidays["date"])
        df = df.with_columns(
            pl.col("date").is_in(holidays["date"].implode()).alias("is_public_holiday"),
            pl.col("date")
            .is_in(pl.Series(sorted(bridges), dtype=pl.Date).implode())
            .alias("is_bridge"),
        )
    df = df.with_columns(school_flag(df, school).alias("is_school_holiday"))
    dt = day_type(
        pl.col("weekday"),
        pl.col("is_public_holiday"),
        pl.col("is_bridge"),
        pl.col("is_school_holiday"),
    )
    known = pl.all_horizontal(
        pl.col("is_public_holiday").is_not_null(),
        pl.col("is_bridge").is_not_null(),
        pl.col("is_school_holiday").is_not_null(),
    )
    return df.with_columns(pl.when(known).then(dt).otherwise(None).alias("day_type"))
