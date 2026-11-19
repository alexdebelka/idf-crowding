"""Date forecasts per Place for the app: the `forecast` block of place.v2 files.

Rules (public: docs/data-quality.md "Date forecasts in the app"):
1. Source = forecast.parquet of the latest data cutoff (ADR 0002); none -> v1 files.
2. Place x date: daily = sum of `point` over member stations, only on dates where every
   member has a forecast and a day type.
3. Band (lo, hi): the station's band for single-station Places. Null for merged Places:
   summing member bands overstates the width (the band must come from the summed forecast).
4. Hourly = daily x the Place's typical-week profile of the date's day type; Crowding
   score = round(100 x hourly / Reference level), same Reference level and bands as v1.
   A date whose day type has no profile for the Place is left out.
5. delta_pct = daily vs the typical-week daily level of the same day type, in percent.
   Hours share one profile, so the hourly delta equals the daily one.
6. Reasons: the forecast's special day, then public holiday, bridge day, school holidays
   (calendar sources; unknown -> not listed).
7. Dates before the build day (Europe/Paris) are dropped. Days since the last data day
   are not stored per date: the app derives them from `data_end`.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import polars as pl

from idf_crowding.features.calendar import calendar_features
from idf_crowding.score.typical import OPERATING_HOURS

CALENDAR_REASONS = (
    ("is_public_holiday", "public_holiday"),
    ("is_bridge", "bridge"),
    ("is_school_holiday", "school_holidays"),
)


def latest_forecast(processed: Path, cutoff: date) -> Path | None:
    """forecast.parquet of the cutoff's folder, if the production forecast was combined."""
    path = processed / "forecast" / cutoff.isoformat() / "forecast.parquet"
    return path if path.is_file() else None


def place_daily(forecast: pl.DataFrame, members: pl.DataFrame) -> pl.DataFrame:
    """place_id, date, point, lo, hi, day_type, special_day."""
    size = members.group_by("place_id").agg(pl.len().alias("n_members"))
    single = pl.col("n_members") == 1
    return (
        forecast.filter(pl.col("day_type").is_not_null(), pl.col("point").is_not_null())
        .join(members, on="station_id")
        .group_by("place_id", "date")
        .agg(
            pl.col("point").sum(),
            pl.col("lo").first(),
            pl.col("hi").first(),
            pl.len().alias("n"),
            pl.col("day_type").first(),
            pl.col("special_day").first(),
        )
        .join(size, on="place_id")
        .filter(pl.col("n") == pl.col("n_members"))
        .with_columns(
            pl.when(single).then(pl.col("lo")).otherwise(None).alias("lo"),
            pl.when(single).then(pl.col("hi")).otherwise(None).alias("hi"),
        )
        .drop("n", "n_members")
        .sort("place_id", "date")
    )


def calendar_reasons(
    dates: pl.Series, holidays: pl.DataFrame | None, school: pl.DataFrame | None
) -> dict[date, list[str]]:
    cal = calendar_features(dates, holidays, school)
    return {
        r["date"]: [name for col, name in CALENDAR_REASONS if r[col]]
        for r in cal.iter_rows(named=True)
    }


def _int(x: float | None) -> int | None:
    return None if x is None else round(max(x, 0.0))


def date_records(
    daily: pl.DataFrame,
    hourly: pl.DataFrame,
    levels: pl.DataFrame,
    refs: pl.DataFrame,
    reasons: dict[date, list[str]],
    today: date,
) -> dict[str, list[dict[str, Any]]]:
    """Per place_id, the `forecast.dates` entries from `today` on, in date order."""
    shares: dict[tuple[str, str], dict[int, float]] = {}
    for r in hourly.iter_rows(named=True):
        shares.setdefault((r["place_id"], r["day_type"]), {})[int(r["hour"])] = r["share"]
    typical = {(r["place_id"], r["day_type"]): r["daily_entries"] for r in levels.to_dicts()}
    ref = dict(zip(refs["place_id"], refs["reference_level"], strict=True))
    out: dict[str, list[dict[str, Any]]] = {}
    for r in daily.filter(pl.col("date") >= today).sort("place_id", "date").to_dicts():
        key = (r["place_id"], r["day_type"])
        prof, level = shares.get(key), ref.get(r["place_id"])
        if prof is None or not level:
            continue
        point = max(float(r["point"]), 0.0)
        base = typical.get(key)
        special = [r["special_day"]] if r["special_day"] else []
        out.setdefault(r["place_id"], []).append(
            {
                "d": r["date"].isoformat(),
                "day_type": r["day_type"],
                "daily": round(point),
                "lo": _int(r["lo"]),
                "hi": _int(r["hi"]),
                "delta_pct": round(100 * (point / base - 1)) if base else None,
                "scores": [round(100 * point * prof.get(h, 0.0) / level) for h in OPERATING_HOURS],
                "reasons": special + reasons.get(r["date"], []),
            }
        )
    return out
