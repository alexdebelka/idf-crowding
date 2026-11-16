"""Daily weather for Paris from the latest Open-Meteo archive download."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

COLUMNS = {
    "precipitation_sum": "precip_mm",
    "snowfall_sum": "snow_cm",
    "precipitation_hours": "precip_hours",
    "temperature_2m_max": "tmax_c",
    "temperature_2m_min": "tmin_c",
}


def parse_open_meteo(data: dict) -> pl.DataFrame:
    daily = data["daily"]
    cols = {"date": pl.Series(daily["time"]).str.to_date()}
    for raw, name in COLUMNS.items():
        if raw in daily:
            cols[name] = pl.Series(daily[raw], dtype=pl.Float64)
    return pl.DataFrame(cols)


def load_weather(raw: Path) -> pl.DataFrame | None:
    """Latest file by end date (names are <start>_<end>.json, so they sort by end)."""
    folder = raw / "weather/open-meteo-paris"
    files = (
        sorted(folder.glob("*.json"), key=lambda p: p.stem.split("_")[-1])
        if folder.is_dir()
        else []
    )
    if not files:
        return None
    return parse_open_meteo(json.loads(files[-1].read_text(encoding="utf-8")))


def empty_weather() -> list[pl.Expr]:
    return [pl.lit(None, pl.Float64).alias(c) for c in COLUMNS.values()]
