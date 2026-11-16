"""Download the French calendar sources: public holidays and school holidays.

Sources (DATA_SOURCES.md #8, #9), checked 2026-11-11:
    calendrier.api.gouv.fr/jours-feries/metropole.json
        {"YYYY-MM-DD": "name"}, ~20 years back and 5 ahead (2006-2031 on 2026-11-11)
    data.education.gouv.fr dataset fr-en-calendrier-scolaire (CSV export, all zones)
        description, population, start_date, end_date, location, zones, annee_scolaire
        Zone C / Paris only from 2017-2018; parsing is in features/calendar.py

Both are saved as dated snapshots under raw/calendar/ (data/raw stays immutable).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from idf_crowding.config import load_config
from idf_crowding.ingest.idfm import Item


@dataclass(frozen=True)
class Settings:
    raw_dir: Path
    holidays_url: str
    holidays_license: str
    school_url: str
    school_license: str
    timeout_seconds: float = 60
    max_attempts: int = 3
    backoff_seconds: float = 5

    @classmethod
    def from_config(cls, config: dict[str, Any] | None = None) -> Settings:
        config = config or load_config()
        s = config["ingest"]["calendar"]
        return cls(
            raw_dir=Path(config["paths"]["data_dir"]) / "raw",
            holidays_url=s["holidays_url"],
            holidays_license=s["holidays_license"],
            school_url=s["school_url"],
            school_license=s["school_license"],
        )


HOLIDAYS_DIR = Path("calendar/jours-feries-metropole")
SCHOOL_DIR = Path("calendar/calendrier-scolaire")


def plan(s: Settings, today: date) -> list[Item]:
    snap = f"snapshot {today.isoformat()}"
    return [
        Item(
            url=s.holidays_url,
            dest=HOLIDAYS_DIR / f"{today.isoformat()}.json",
            dataset_id="jours-feries-metropole",
            period=snap,
            license=s.holidays_license,
            dataset_modified="",
        ),
        Item(
            url=s.school_url,
            dest=SCHOOL_DIR / f"{today.isoformat()}.csv",
            dataset_id="fr-en-calendrier-scolaire",
            period=snap,
            license=s.school_license,
            dataset_modified="",
        ),
    ]
