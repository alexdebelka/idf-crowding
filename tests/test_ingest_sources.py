from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

from idf_crowding.config import REPO_ROOT, load_config
from idf_crowding.ingest import calendar, weather
from idf_crowding.ingest.idfm import download


def test_calendar_plan_dated_snapshots(tmp_path):
    s = calendar.Settings(tmp_path, "https://h.test/metropole.json", "x", "https://s.test/e", "y")
    items = calendar.plan(s, date(2026, 11, 11))
    assert [i.dest.as_posix() for i in items] == [
        "calendar/jours-feries-metropole/2026-11-11.json",
        "calendar/calendrier-scolaire/2026-11-11.csv",
    ]


def test_weather_plan_url_and_end_lag(tmp_path):
    s = weather.Settings(
        tmp_path,
        "https://archive.test/v1/archive",
        48.8566,
        2.3522,
        date(2015, 1, 1),
        2,
        ["precipitation_sum", "temperature_2m_max"],
        "Europe/Paris",
        "CC BY 4.0",
    )
    (item,) = weather.plan(s, date(2026, 11, 11))
    q = parse_qs(urlsplit(item.url).query)
    assert q["start_date"] == ["2015-01-01"] and q["end_date"] == ["2026-11-09"]
    assert q["daily"] == ["precipitation_sum,temperature_2m_max"]
    assert q["timezone"] == ["Europe/Paris"]
    assert item.dest == Path("weather/open-meteo-paris/2015-01-01_2026-11-09.json")


def test_new_sources_download_with_manifest(tmp_path):
    s = calendar.Settings(
        tmp_path, "https://h.test/m.json", "x", "https://s.test/e", "y", backoff_seconds=0
    )
    item = calendar.plan(s, date(2026, 11, 11))[0]
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, content=b'{"2026-01-01": "1er janvier"}')
        )
    )
    entry = download(client, item, s)
    assert entry["dataset_id"] == "jours-feries-metropole"
    assert (tmp_path / "manifest.jsonl").exists()


def test_repo_config_has_new_sections():
    c = load_config(REPO_ROOT)
    assert calendar.Settings.from_config(c).holidays_url.startswith(
        "https://calendrier.api.gouv.fr"
    )
    w = weather.Settings.from_config(c)
    assert w.url.startswith("https://archive-api.open-meteo.com") and w.end_lag_days >= 1
