from datetime import date

import numpy as np
import polars as pl
import pytest

from idf_crowding.models import special_days as sd


def log(dates, station_ratio, station_type="mixed", stations=(1,), origins=1, point=100.0):
    """Forecast-log rows: point = 100, y = 100 * ratio for each (station, date, origin)."""
    rows = []
    for s in stations:
        for d in dates:
            for o in range(origins):
                rows.append(
                    {
                        "origin": date(d.year - 1, 9 + o, 1),
                        "station_id": s,
                        "date": d,
                        "station_type": station_type,
                        "y": point * station_ratio[s]
                        if isinstance(station_ratio, dict)
                        else point * station_ratio,
                        "lgbm": point,
                        "exclude": None,
                    }
                )
    return pl.DataFrame(rows, schema_overrides={"exclude": pl.String})


def test_special_day_names_and_season():
    df = pl.DataFrame({"date": [date(2025, 12, 24), date(2026, 1, 1), date(2026, 1, 2)]})
    names = df.select(sd.special_day())["date"].to_list()
    assert names == ["christmas_eve", "new_years_day", None]
    assert df.select(sd._season())["date"].to_list() == [2025, 2025, 2025]


def test_factors_use_only_outcomes_before_cutoff():
    past = log([date(2024, 12, 25)], 0.5)
    future = log([date(2025, 12, 25)], 2.0)
    cut = date(2025, 7, 1)
    f1 = sd.factors(past, "lgbm", cut)
    f2 = sd.factors(pl.concat([past, future]), "lgbm", cut)
    assert f1.equals(f2)
    assert f1["n_years"].to_list() == [1]


def test_shrinkage_limits():
    # station 1 ratio 0.5, station 2 ratio 1.0, same type, 2 years each
    d = [date(2023, 12, 24), date(2024, 12, 24)]
    lg = log(d, {1: 0.5, 2: 1.0}, stations=(1, 2))
    cut = date(2025, 7, 1)
    lr1 = np.log1p(50.0) - np.log1p(100.0)
    target = np.median([lr1, 0.0])
    # k = 0: the station's own median; k -> inf: the station-type target
    f0 = sd.factors(lg, "lgbm", cut, k=0).filter(pl.col("station_id") == 1)
    assert f0["log_f"][0] == pytest.approx(lr1)
    finf = sd.factors(lg, "lgbm", cut, k=1e12).filter(pl.col("station_id") == 1)
    assert finf["log_f"][0] == pytest.approx(target)
    # k = 2, n = 2: halfway
    f2 = sd.factors(lg, "lgbm", cut, k=2).filter(pl.col("station_id") == 1)
    assert f2["log_f"][0] == pytest.approx(0.5 * lr1 + 0.5 * target)


def test_origins_averaged_before_median():
    # two origins cover the date: their log ratios are averaged into one year
    lg = log([date(2024, 12, 31)], 0.5, origins=2)
    f = sd.factors(lg, "lgbm", date(2025, 7, 1), k=0)
    assert f["n_years"][0] == 1


def test_apply_keeps_ordinary_days_and_band_order():
    f = sd.factors(log([date(2024, 12, 25)], 0.5, stations=(1,)), "lgbm", date(2025, 7, 1))
    rows = pl.DataFrame(
        {
            "station_id": [1, 1, 9],
            "date": [date(2025, 12, 23), date(2025, 12, 25), date(2025, 12, 25)],
            "station_type": ["mixed", "mixed", "mixed"],
            "point": [100.0, 100.0, 100.0],
            "lo": [80.0, 80.0, 80.0],
            "hi": [130.0, 130.0, 130.0],
        }
    )
    out = sd.apply(rows, f).sort("station_id", "date")
    ordinary, special, unseen = out.rows(named=True)
    assert ordinary["adjust"] == 1.0 and ordinary["point"] == 100.0
    assert ordinary["special_day"] is None
    assert special["special_day"] == "christmas_day" and special["adjust"] < 1.0
    # a station without history gets its station type's factor
    assert unseen["adjust"] < 1.0
    for r in (special, unseen):
        assert r["lo"] <= r["point"] <= r["hi"]
        assert r["point"] == pytest.approx(100.0 * r["adjust"])


def test_apply_without_history_is_identity():
    rows = pl.DataFrame(
        {
            "station_id": [1],
            "date": [date(2025, 12, 25)],
            "station_type": ["mixed"],
            "point": [100.0],
            "lo": [80.0],
            "hi": [130.0],
        }
    )
    out = sd.apply(rows, sd.factors(log([date(2024, 6, 1)], 0.5), "lgbm", date(2025, 7, 1)))
    assert out["adjust"][0] == 1.0 and out["point"][0] == 100.0


def test_young_stations_fall_back_to_type_factor():
    # station 1: 2 years of history at the forecast's cutoff; station 2: opened 3 months before
    lg = log([date(2024, 12, 25)], {1: 0.5, 2: 0.1}, stations=(1, 2)).with_columns(
        pl.lit(date(2024, 8, 1)).alias("cutoff")
    )
    seen = pl.DataFrame({"station_id": [1, 2], "first_date": [date(2022, 1, 1), date(2024, 5, 1)]})
    f = sd.factors(lg, "lgbm", date(2025, 7, 1), first_seen=seen)
    assert f["station_id"].to_list() == [1]
    assert sd.factors(lg, "lgbm", date(2025, 7, 1))["station_id"].sort().to_list() == [1, 2]
