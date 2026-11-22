"""P(busy day): seasonal threshold and logistic recalibration (models/intervals.py, busy.py)."""

from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from idf_crowding.models import busy, intervals


def daily(start: date, end: date, level, seed=0, station=1) -> pl.DataFrame:
    """One station, every day in [start, end), working days only (day type JOHV);
    n_entries = level(date) × lognormal noise."""
    rng = np.random.default_rng(seed)
    days = [start + timedelta(days=i) for i in range((end - start).days)]
    return pl.DataFrame(
        {
            "station_id": [station] * len(days),
            "date": days,
            "day_type": ["JOHV"] * len(days),
            "n_entries": [level(d) * float(np.exp(rng.normal(0, 0.1))) for d in days],
        }
    )


def seasonal(d: date) -> float:
    return 1000 * (1 + 0.4 * np.sin(2 * np.pi * d.timetuple().tm_yday / 365.25))


def test_seasonal_threshold_ignores_rows_on_or_after_the_cutoff():
    c = date(2025, 1, 1)
    h = daily(date(2022, 1, 1), date(2026, 1, 1), seasonal)
    targets = daily(c, date(2025, 7, 1), seasonal).select("station_id", "date", "day_type")
    a = intervals.busy_threshold(h.filter(pl.col("date") < c), targets, c, method="seasonal")
    spoiled = h.with_columns(
        pl.when(pl.col("date") >= c).then(10**9).otherwise(pl.col("n_entries")).alias("n_entries")
    )
    b = intervals.busy_threshold(spoiled, targets, c, method="seasonal")
    assert a.is_not_null().all()
    assert a.equals(b)
    rates = pl.DataFrame({"cls": ["wk", "sat", "sun"], "g": [1.1, 1.1, 1.1]})
    a = intervals.busy_threshold(
        h.filter(pl.col("date") < c), targets, c, method="seasonal", rates=rates
    )
    b = intervals.busy_threshold(spoiled, targets, c, method="seasonal", rates=rates)
    assert a.equals(b)


def monthly_busy(future: pl.DataFrame, thr: pl.Series) -> pl.Series:
    return (
        future.with_columns(thr.alias("t"))
        .group_by(pl.col("date").dt.month().alias("m"))
        .agg((pl.col("n_entries") > pl.col("t")).mean().alias("busy"))["busy"]
    )


def test_seasonal_threshold_gives_about_ten_percent_every_month():
    c = date(2025, 1, 1)
    h = pl.concat([daily(date(2022, 1, 1), c, seasonal, seed=s, station=s) for s in range(20)])
    future = pl.concat([daily(c, date(2026, 1, 1), seasonal, 100 + s, s) for s in range(20)])
    rate = monthly_busy(future, intervals.busy_threshold(h, future, c, method="seasonal"))
    assert rate.is_between(0.07, 0.15).all()
    # without the local level, the ± 45-day window mixes the season's slopes in
    plain = intervals.busy_threshold(h, future, c, method="seasonal", local_days=0)
    assert monthly_busy(future, plain).min() < 0.02
    # and the yearly threshold does not follow the season at all
    ry = monthly_busy(future, intervals.busy_threshold(h, future, c))
    assert ry.max() > 0.3 and ry.min() < 0.02


def test_seasonal_threshold_follows_growth():
    c = date(2025, 1, 1)

    def growing(d):  # +10 % a year, no season
        return 1000 * 1.1 ** ((d - c).days / 364)

    h = daily(date(2022, 1, 1), c, growing, seed=3)
    future = daily(c + timedelta(days=120), c + timedelta(days=300), growing, seed=4)
    rates = pl.DataFrame({"cls": ["wk", "sat", "sun"], "g": [1.1, 1.1, 1.1]})
    grown = intervals.busy_threshold(h, future, c, method="seasonal", rates=rates)
    flat = intervals.busy_threshold(h, future, c, method="seasonal")
    b_grown = (future["n_entries"] > grown).mean()
    b_flat = (future["n_entries"] > flat).mean()
    assert 0.05 <= b_grown <= 0.15
    assert b_flat > 0.3


def test_seasonal_threshold_falls_back_to_the_yearly_threshold():
    c = date(2025, 1, 1)
    h = daily(c - timedelta(days=15), c, lambda d: 100.0)  # 15 days only
    t = pl.DataFrame({"station_id": [1, 2], "date": [c, c], "day_type": ["JOHV", "JOHV"]})
    got = intervals.busy_threshold(h, t, c, method="seasonal", min_days=20).to_list()
    want = intervals.busy_threshold(h, t, c).to_list()
    assert got[0] == pytest.approx(want[0], rel=1e-6) and got[1] is None
    with pytest.raises(ValueError):
        intervals.busy_threshold(h, t, c, method="monthly")


def _busy_log(seed=0):
    """Three monthly origins, 60-day horizons, 5 stations; p_busy noisy but informative."""
    rng = np.random.default_rng(seed)
    rows = []
    for o in [date(2025, 1, 1), date(2025, 2, 1), date(2025, 3, 1)]:
        for st in range(5):
            for h in range(60):
                p = rng.uniform(0.01, 0.99)
                rows.append(
                    {
                        "origin": o,
                        "station_id": st,
                        "date": o + timedelta(days=h),
                        "horizon_bucket": "1-7" if h < 7 else ("8-28" if h < 28 else "29-60"),
                        "scored": True,
                        "p_busy": p,
                        "busy_threshold": 100.0,
                        "y": 150.0 if rng.uniform() < p**2 else 50.0,
                    }
                )
    return pl.DataFrame(rows)


@pytest.mark.parametrize("context", [("horizon_bucket",), ("horizon_bucket", "season")])
def test_logistic_recalibration_uses_only_earlier_outcomes(monkeypatch, context):
    monkeypatch.setattr(intervals, "MIN_CAL", 20)
    o = date(2025, 3, 1)
    log = _busy_log()
    a = intervals.recalibrate_busy_logistic(log, [o], context=context)
    assert a["p_busy_logit"].is_not_nan().all()
    assert a["p_busy_logit"].is_between(0, 1).all()
    flipped = log.with_columns(
        pl.when(pl.col("date") >= o).then(200.0 - pl.col("y")).otherwise(pl.col("y")).alias("y")
    )
    assert a.equals(intervals.recalibrate_busy_logistic(flipped, [o], context=context))
    c = intervals.recalibrate_busy_logistic(
        log.with_columns(pl.lit(150.0).alias("y")).with_columns(
            pl.when(pl.col("station_id") == 0).then(50.0).otherwise(150.0).alias("y")
        ),
        [o],
        context=context,
    )
    assert not a.equals(c)


def test_logistic_recalibration_learns_the_mapping(monkeypatch):
    monkeypatch.setattr(intervals, "MIN_CAL", 20)
    log = _busy_log(seed=1)
    o = date(2025, 3, 1)
    got = intervals.recalibrate_busy_logistic(log, [o]).join(
        log, on=["origin", "station_id", "date"]
    )
    # truth is p**2: the recalibrated p is closer to it than the raw p
    err_raw = ((got["p_busy"] - got["p_busy"] ** 2) ** 2).mean()
    err_new = ((got["p_busy_logit"] - got["p_busy"] ** 2) ** 2).mean()
    assert err_new < err_raw


def test_evaluate_and_acceptance():
    log = _busy_log(seed=2).filter(pl.col("origin") == date(2025, 3, 1))
    rows = log.with_columns(
        pl.col("p_busy").alias("p_raw"),
        (pl.col("p_busy") ** 2).alias("p_isotonic"),
        (pl.col("p_busy") ** 2).alias("p_logistic"),
    )
    ev = busy.evaluate(rows, {"model": "lgbm", "threshold": "seasonal"})
    assert set(ev) == {"scores", "reliability", "monthly"}
    sc = busy.accepted(ev["scores"], {"lgbm": -1.0})
    assert sc.height == 3 and sc["recal"].to_list() == busy.RECAL
    assert set(ev["reliability"]["season"].unique()) >= {"all", "MAM"}
