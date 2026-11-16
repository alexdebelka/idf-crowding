from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from idf_crowding.viz import eda

START = date(2024, 1, 1)  # Monday


def synthetic_daily(weeks: int = 20) -> pl.DataFrame:
    level = {1: 800, 2: 1000, 3: 1000, 4: 1000, 5: 900, 6: 500, 7: 300}
    rows = []
    for i in range(weeks * 7):
        d = START + timedelta(days=i)
        for s in range(10):
            rows.append({"station_id": s, "date": d, "n_entries": level[d.isoweekday()]})
    return pl.DataFrame(rows)


def test_weekday_index_is_relative_to_midweek():
    idx = eda.weekday_index(synthetic_daily())
    got = dict(zip(idx["weekday"].to_list(), idx["index"].to_list(), strict=True))
    assert got[1] == pytest.approx(0.8)
    assert got[3] == pytest.approx(1.0)
    assert got[7] == pytest.approx(0.3)


def test_normal_days_drop_a_strike_day():
    daily = synthetic_daily()
    strike = START + timedelta(weeks=8, days=2)
    daily = daily.with_columns(
        pl.when(pl.col("date") == strike).then(50).otherwise("n_entries").alias("n_entries")
    )
    assert strike not in eda.normal_days(daily).to_list()


def profiles_frame():
    rows = []
    for sid, peak in [(1, 8), (2, 8), (3, 18), (4, 18)]:
        for h in eda.HOURS:
            rows.append(
                {
                    "period": "2025Q1",
                    "station_id": sid,
                    "day_type": "JOHV",
                    "hour": h,
                    "share": 0.5 if h == peak else 0.5 / 23,
                }
            )
    return pl.DataFrame(rows)


def test_profile_matrix_rows_sum_to_one():
    m, ids = eda.profile_matrix(profiles_frame(), ["2025Q1"], "JOHV")
    assert m.shape == (4, 24)
    assert ids == [1, 2, 3, 4]
    assert np.allclose(m.sum(axis=1), 1)


def test_cluster_profiles_orders_by_peak_hour():
    m, ids = eda.profile_matrix(profiles_frame(), ["2025Q1"], "JOHV")
    labels, centers = eda.cluster_profiles(m, 2)
    assert labels.tolist() == [0, 0, 1, 1]
    assert centers[0].argmax() == 8 and centers[1].argmax() == 18


def test_weighted_profile():
    m, ids = eda.profile_matrix(profiles_frame(), ["2025Q1"], "JOHV")
    p = eda.weighted_profile(m, ids, {1: 3.0, 3: 1.0})
    assert p.sum() == pytest.approx(1)
    assert p[8] == pytest.approx(0.75 * 0.5 + 0.25 * 0.5 / 23)
