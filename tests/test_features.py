"""One test per feature rule (see docs/data-quality.md, "Features")."""

import json
from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from idf_crowding.features import calendar as cal
from idf_crowding.features.build import Paths, build
from idf_crowding.features.stations import station_types
from idf_crowding.features.tickets import monthly_share, ramp_for_dates
from idf_crowding.features.weather import load_weather, parse_open_meteo

HOLIDAYS = {
    "2025-05-01": "1er mai",
    "2025-05-08": "8 mai",
    "2025-05-29": "Ascension",
    "2025-07-14": "14 juillet",
    "2025-12-25": "Jour de Noël",
}

Z = "+00:00"
SCHOOL_ROWS = [
    ("Vacances de Printemps", "-", "2025-04-11T22:00:00", "2025-04-27T22:00:00", "Paris", "Zone C"),
    ("Pont de l'Ascension", "-", "2025-05-28T22:00:00", "2025-06-01T22:00:00", "Paris", "Zone C"),
    ("Vacances d'Été", "Élèves", "2025-07-04T22:00:00", "2025-08-31T22:00:00", "Paris", "Zone C"),
    (
        "Vacances d'Été",
        "Enseignants",
        "2025-07-04T22:00:00",
        "2025-08-28T22:00:00",
        "Paris",
        "Zone C",
    ),
    ("Vacances de Printemps", "-", "2025-04-04T22:00:00", "2025-04-20T22:00:00", "Lyon", "Zone A"),
]
SCHOOL_CSV = "description;population;start_date;end_date;location;zones;annee_scolaire\n" + "".join(
    f"{d};{p};{a}{Z};{b}{Z};{loc};{z};2024-2025\n" for d, p, a, b, loc, z in SCHOOL_ROWS
)


def write_raw(raw):
    h = raw / "calendar/jours-feries-metropole"
    h.mkdir(parents=True)
    (h / "2026-11-11.json").write_text(json.dumps(HOLIDAYS), encoding="utf-8")
    sc = raw / "calendar/calendrier-scolaire"
    sc.mkdir(parents=True)
    (sc / "2026-11-11.csv").write_text(SCHOOL_CSV, encoding="utf-8")


def days(start, n):
    return [start + timedelta(days=i) for i in range(n)]


def test_public_holidays_loaded_from_latest_snapshot(tmp_path):
    write_raw(tmp_path)
    h = cal.load_public_holidays(tmp_path)
    assert date(2025, 5, 1) in h["date"].to_list()
    assert cal.load_public_holidays(tmp_path / "nothing") is None


def test_school_intervals_paris_zone_c_pupils_local_dates(tmp_path):
    write_raw(tmp_path)
    s = cal.load_school_holidays(tmp_path)
    # Zone A and the teachers' summer row are excluded; UTC instants -> Paris dates
    assert s.select("start", "end").rows() == [
        (date(2025, 4, 12), date(2025, 4, 28)),
        (date(2025, 5, 29), date(2025, 6, 2)),
        (date(2025, 7, 5), date(2025, 9, 1)),
    ]


def test_school_flag_end_is_exclusive_and_null_outside_coverage(tmp_path):
    write_raw(tmp_path)
    s = cal.load_school_holidays(tmp_path)
    d = pl.DataFrame(
        {
            "date": [
                date(2025, 4, 11),
                date(2025, 4, 12),
                date(2025, 4, 27),
                date(2025, 4, 28),
                date(2024, 1, 1),
                date(2026, 1, 1),
            ]
        }
    )
    assert cal.school_flag(d, s).to_list() == [False, True, True, False, None, None]


def test_bridge_days_monday_before_tuesday_and_friday_after_thursday():
    hol = pl.Series([date(2025, 5, 29), date(2024, 1, 2), date(2025, 7, 14)])  # Thu, Tue, Mon
    assert cal.bridge_days(hol) == {date(2025, 5, 30), date(2024, 1, 1)}


def test_bridge_is_not_a_bridge_when_itself_a_holiday():
    # Tue 2024-01-02 holiday and Mon 2024-01-01 also a holiday
    hol = pl.Series([date(2024, 1, 1), date(2024, 1, 2)])
    assert date(2024, 1, 1) not in cal.bridge_days(hol)


def test_day_type_rules(tmp_path):
    write_raw(tmp_path)
    f = cal.calendar_features(
        [
            date(2025, 4, 15),
            date(2025, 4, 8),
            date(2025, 4, 19),
            date(2025, 4, 5),
            date(2025, 4, 6),
            date(2025, 5, 1),
            date(2025, 5, 30),
        ],
        cal.load_public_holidays(tmp_path),
        cal.load_school_holidays(tmp_path),
    ).sort("date")
    got = dict(zip(f["date"].to_list(), f["day_type"].to_list(), strict=True))
    assert got[date(2025, 4, 15)] == "JOVS"  # Tue in spring holidays
    assert got[date(2025, 4, 8)] == "JOHV"  # Tue outside
    assert got[date(2025, 4, 19)] == "SAVS"
    assert got[date(2025, 4, 5)] == "SAHV"
    assert got[date(2025, 4, 6)] == "DIJFP"  # Sunday
    assert got[date(2025, 5, 1)] == "DIJFP"  # public holiday on a Thursday
    assert got[date(2025, 5, 30)] == "DIJFP"  # bridge Friday after Ascension


def test_missing_sources_give_null_not_guesses():
    f = cal.calendar_features([date(2025, 5, 1)], None, None)
    assert f["is_public_holiday"].to_list() == [None]
    assert f["is_school_holiday"].to_list() == [None]
    assert f["day_type"].to_list() == [None]
    assert f["weekday"].to_list() == [4]


def test_era_flags():
    f = cal.calendar_features(
        [
            date(2019, 12, 4),
            date(2019, 12, 5),
            date(2020, 1, 19),
            date(2020, 3, 17),
            date(2021, 6, 30),
            date(2021, 7, 1),
        ],
        None,
        None,
    ).sort("date")
    assert f["is_strike_2019"].to_list() == [False, True, True, False, False, False]
    assert f["is_covid"].to_list() == [False, False, False, True, True, False]


def test_parse_open_meteo_renames_columns():
    data = {
        "daily": {
            "time": ["2025-01-01", "2025-01-02"],
            "precipitation_sum": [0.0, 3.9],
            "temperature_2m_max": [1.5, 10.0],
            "temperature_2m_min": [-3.2, -0.9],
            "snowfall_sum": [0.0, None],
            "precipitation_hours": [0.0, 10.0],
        }
    }
    w = parse_open_meteo(data)
    assert w.columns == ["date", "precip_mm", "snow_cm", "precip_hours", "tmax_c", "tmin_c"]
    assert w["precip_mm"].to_list() == [0.0, 3.9]
    assert w["snow_cm"].to_list() == [0.0, None]


def test_load_weather_takes_latest_end_date(tmp_path):
    folder = tmp_path / "weather/open-meteo-paris"
    folder.mkdir(parents=True)
    for end, v in [("2026-11-09", 1.0), ("2026-12-01", 2.0)]:
        (folder / f"2015-01-01_{end}.json").write_text(
            json.dumps({"daily": {"time": ["2025-01-01"], "precipitation_sum": [v]}})
        )
    assert load_weather(tmp_path)["precip_mm"].to_list() == [2.0]
    assert load_weather(tmp_path / "none") is None


def test_ticket_ramp_monthly_share_and_plateau():
    t = pl.LazyFrame(
        {
            "date": [date(2024, 12, 5), date(2024, 12, 5), date(2025, 1, 5), date(2025, 1, 5)],
            "ticket_group": ["navigo", "short_passes", "navigo", "short_passes"],
            "n_validations": [99, 1, 90, 10],
        }
    )
    shares = monthly_share(t)
    assert shares["short_pass_share"].to_list() == pytest.approx([0.01, 0.10])
    d = pl.DataFrame(
        {"date": [date(2024, 11, 1), date(2024, 12, 31), date(2025, 1, 15), date(2026, 6, 1)]}
    )
    assert ramp_for_dates(d, shares).to_list() == pytest.approx([0.01, 0.01, 0.10, 0.10])


def profile_rows(sid, peak, periods):
    return [
        {
            "period": p,
            "station_id": sid,
            "day_type": "JOHV",
            "hour": h,
            "share": 0.6 if h == peak else 0.4 / 23,
        }
        for p in periods
        for h in range(24)
    ]


def test_station_types_named_by_morning_share():
    periods = ["2025Q2", "2025Q3", "2025Q4", "2026Q1", "2026Q2"]
    rows = []
    for sid, peak in [(1, 7), (2, 7), (3, 12), (4, 12), (5, 18), (6, 18)]:
        rows += profile_rows(sid, peak, periods)
    rows += profile_rows(7, 7, ["2025Q2"])  # not in the last 4 quarters: its latest profile
    rows += profile_rows(8, 18, ["2026Q1", "2026Q2"])  # new station: the quarters it has
    rows += profile_rows(9, 12, ["2025Q4"]) + profile_rows(9, 18, ["2015S1"])  # most recent
    t = station_types(pl.DataFrame(rows))
    got = dict(zip(t["station_id"].to_list(), t["station_type"].to_list(), strict=True))
    assert got == {
        1: "origin",
        2: "origin",
        3: "mixed",
        4: "mixed",
        5: "destination",
        6: "destination",
        7: "origin",
        8: "destination",
        9: "mixed",
    }
    assert t["station_type_periods"][0] == "2025Q3,2025Q4,2026Q1,2026Q2"


def test_partial_stations_do_not_move_the_clusters():
    periods = ["2025Q3", "2025Q4", "2026Q1", "2026Q2"]
    rows = []
    for sid, peak in [(1, 7), (2, 8), (3, 12), (4, 13), (5, 18), (6, 17)]:
        rows += profile_rows(sid, peak, periods)
    full = station_types(pl.DataFrame(rows))
    rows += profile_rows(7, 10, ["2026Q2"])
    more = station_types(pl.DataFrame(rows))
    assert more.filter(pl.col("station_id") != 7).equals(full)
    assert more.filter(pl.col("station_id") == 7)["station_type"].item() is not None


def test_station_without_any_profile_stays_untyped():
    periods = ["2025Q3", "2025Q4", "2026Q1", "2026Q2"]
    rows = []
    for sid, peak in [(1, 7), (2, 7), (3, 12), (4, 12), (5, 18), (6, 18)]:
        rows += profile_rows(sid, peak, periods)
    t = station_types(pl.DataFrame(rows), fallback_periods=["2025Q3"])
    assert 7 not in t["station_id"].to_list()


def test_build_end_to_end_without_and_with_downloads(tmp_path):
    paths = Paths(tmp_path / "raw", tmp_path / "interim", tmp_path / "processed")
    (paths.processed / "quality").mkdir(parents=True)
    paths.interim.mkdir()
    dates = days(date(2025, 4, 7), 70)
    rows = [
        {"station_id": s, "date": d, "n_entries": 1000 + s, "n_masked_rows": 0}
        for s in range(1, 7)
        for d in dates
        if not (s == 1 and d == dates[10])
    ]
    pl.DataFrame(rows).write_parquet(paths.processed / "station_daily.parquet")
    pl.DataFrame(
        {
            "station_id": [1],
            "date": [dates[10]],
            "flag": ["missing"],
            "n_entries": [None],
            "expected": [None],
            "ratio": [None],
            "network_ratio": [None],
        },
        schema_overrides={
            "n_entries": pl.Int64,
            "expected": pl.Float64,
            "ratio": pl.Float64,
            "network_ratio": pl.Float64,
        },
    ).write_parquet(paths.processed / "quality/station_day_flags.parquet")
    pl.DataFrame(
        {
            "date": [dates[0]] * 2,
            "ticket_group": ["navigo", "short_passes"],
            "n_validations": [80, 20],
        }
    ).write_parquet(paths.interim / "validations_daily_tickets.parquet")
    prof = []
    for sid, peak in [(1, 7), (2, 7), (3, 12), (4, 12), (5, 18), (6, 18)]:
        prof += profile_rows(sid, peak, ["2025Q3", "2025Q4", "2026Q1", "2026Q2"])
    pl.DataFrame(prof).write_parquet(paths.processed / "station_profiles.parquet")

    with pytest.warns(UserWarning) as caught:
        out = build(paths, log=lambda _: None)
    assert {str(w.message).split(":")[0] for w in caught} == {
        "public holidays",
        "school holidays",
        "weather",
    }
    assert out.height == 6 * 70  # the missing station-day is an explicit row
    gap = out.filter((pl.col("station_id") == 1) & (pl.col("date") == dates[10]))
    assert gap["n_entries"].to_list() == [None] and gap["quality_flag"].to_list() == ["missing"]
    assert out["day_type"].null_count() == out.height
    assert np.allclose(out["short_pass_share"].to_numpy(), 0.2)

    write_raw(paths.raw)
    w = paths.raw / "weather/open-meteo-paris"
    w.mkdir(parents=True)
    (w / "2015-01-01_2026-11-09.json").write_text(
        json.dumps(
            {"daily": {"time": [d.isoformat() for d in dates], "precipitation_sum": [1.0] * 70}}
        )
    )
    out = build(paths, log=lambda _: None)
    assert out.filter(pl.col("date") == date(2025, 5, 1))["day_type"].unique().to_list() == [
        "DIJFP"
    ]
    assert out["precip_mm"].null_count() == 0
    assert set(out["station_type"].unique().to_list()) == {"origin", "mixed", "destination"}
