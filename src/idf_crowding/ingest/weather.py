"""Download daily weather for Paris from the Open-Meteo historical archive.

Source (DATA_SOURCES.md #7), checked 2026-11-11:
    GET https://archive-api.open-meteo.com/v1/archive
        ?latitude&longitude&start_date&end_date&daily=<vars>&timezone=Europe/Paris
    -> {"daily": {"time": [...], "<var>": [...]}, "daily_units": {...}}
    end_date may not be later than today; the most recent days come from forecast
    models and can be revised, so we stop `end_lag_days` before the download date.

Each download is a new file raw/weather/open-meteo-paris/<start>_<end>.json; features
use the file with the latest end date. Data CC BY 4.0 ("Weather data by Open-Meteo.com");
the free API is for non-commercial use.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from idf_crowding.config import load_config
from idf_crowding.ingest.idfm import Item

WEATHER_DIR = Path("weather/open-meteo-paris")


@dataclass(frozen=True)
class Settings:
    raw_dir: Path
    url: str
    latitude: float
    longitude: float
    start_date: date
    end_lag_days: int
    daily: list[str]
    timezone: str
    license: str
    timeout_seconds: float = 120
    max_attempts: int = 3
    backoff_seconds: float = 5

    @classmethod
    def from_config(cls, config: dict[str, Any] | None = None) -> Settings:
        config = config or load_config()
        s = config["ingest"]["weather"]
        return cls(
            raw_dir=Path(config["paths"]["data_dir"]) / "raw",
            url=s["url"],
            latitude=s["latitude"],
            longitude=s["longitude"],
            start_date=date.fromisoformat(s["start_date"]),
            end_lag_days=s["end_lag_days"],
            daily=list(s["daily"]),
            timezone=s["timezone"],
            license=s["license"],
        )


def plan(s: Settings, today: date) -> list[Item]:
    end = today - timedelta(days=s.end_lag_days)
    params = {
        "latitude": s.latitude,
        "longitude": s.longitude,
        "start_date": s.start_date.isoformat(),
        "end_date": end.isoformat(),
        "daily": ",".join(s.daily),
        "timezone": s.timezone,
    }
    return [
        Item(
            url=f"{s.url}?{urlencode(params)}",
            dest=WEATHER_DIR / f"{s.start_date.isoformat()}_{end.isoformat()}.json",
            dataset_id="open-meteo-archive-paris",
            period=f"{s.start_date.isoformat()} to {end.isoformat()}",
            license=s.license,
            dataset_modified="",
        )
    ]
