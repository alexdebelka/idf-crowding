"""Counting breaks (models/breaks.py, docs/data-quality.md "Counting breaks")."""

from datetime import date, timedelta

import polars as pl
import pytest

from idf_crowding.models import breaks as brk

START, SETTLED = date(2026, 1, 12), date(2026, 1, 13)
B = [brk.Break(1, START, SETTLED)]


def data(first=date(2025, 9, 1), last=date(2026, 6, 30), jump=2.0):
    """Station 1: 100 a day, `jump` x from SETTLED (150 on START); station 2: 1000 a day."""
    rows = []
    d = first
    while d <= last:
        dt = "JOHV" if d.weekday() < 5 else ("SAHV" if d.weekday() == 5 else "DIJFP")
        s1 = 100 if d < START else (150 if d < SETTLED else 100 * jump)
        rows += [
            {"station_id": 1, "date": d, "day_type": dt, "n_entries": int(s1), "exclude": None},
            {"station_id": 2, "date": d, "day_type": dt, "n_entries": 1000, "exclude": None},
        ]
        d += timedelta(days=1)
    return pl.DataFrame(rows, schema_overrides={"exclude": pl.String})


def test_factor_is_the_share_ratio_once_known():
    f = brk.factors(data(), B, date(2026, 3, 1))
    # share 100/1100 before, 200/1200 after
    assert f[1] == pytest.approx((200 / 1200) / (100 / 1100))


def test_no_factor_before_enough_days_after_the_break():
    assert brk.factors(data(), B, SETTLED) == {}
    assert brk.factors(data(), B, SETTLED + timedelta(days=7)) == {}  # 5 working days


def test_factor_ignores_data_from_the_cutoff_on():
    c = date(2026, 3, 1)
    later = data().with_columns(
        pl.when(pl.col("date") >= c).then(pl.col("n_entries") * 5).otherwise(pl.col("n_entries"))
    )
    assert brk.factors(later, B, c) == brk.factors(data(), B, c)


def test_apply_rescales_history_and_leaves_the_switch_day_out():
    out, f = brk.apply(data(), B, date(2026, 3, 1))
    s1 = out.filter(pl.col("station_id") == 1)
    before = s1.filter(pl.col("date") < START)["n_entries"].unique().to_list()
    assert before == [round(100 * f[1])]
    assert s1.filter(pl.col("date") == START)["exclude"].item() == "count_break"
    assert s1.filter(pl.col("date") >= SETTLED)["n_entries"].unique().to_list() == [200]
    assert out.filter(pl.col("station_id") == 2).equals(data().filter(pl.col("station_id") == 2))


def test_apply_without_exclude_column_nulls_the_switch_day():
    out, _ = brk.apply(data().drop("exclude"), B, date(2026, 3, 1), exclude_col=None)
    assert (
        out.filter((pl.col("station_id") == 1) & (pl.col("date") == START))["n_entries"].item()
        is None
    )


def test_apply_before_the_break_is_known_changes_nothing():
    d = data()
    out, f = brk.apply(d, B, date(2026, 1, 1))
    assert f == {} and out.equals(d)
