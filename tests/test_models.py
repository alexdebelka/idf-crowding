"""One test per Phase 5 rule (models/: frozen features, baselines, metrics, backtest)."""

from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from idf_crowding.models import backtest as bt
from idf_crowding.models import baselines, gbm, intervals
from idf_crowding.models import weather as wx
from idf_crowding.models.closures import is_closure
from idf_crowding.models.frozen import (
    apply_frozen,
    freeze_short_pass_share,
    frozen_station_types,
    period_bounds,
    periods_before,
)
from idf_crowding.models.metrics import gains, horizon_bucket, summarize

# station id -> (peak hour of its JOHV profile, mean daily entries)
STATIONS = {1: (7, 1000), 2: (7, 1200), 3: (12, 3000), 4: (12, 2500), 5: (18, 8000), 6: (18, 9000)}
PERIODS = ["2023S2", "2024Q1", "2024Q2", "2024Q3", "2024Q4", "2025Q1", "2025Q2", "2025Q3"]


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


def profiles(stations=STATIONS, periods=PERIODS):
    rows = []
    for sid, (peak, _) in stations.items():
        rows += profile_rows(sid, peak, periods)
    return pl.DataFrame(rows)


def day_type(d):
    return "DIJFP" if d.weekday() == 6 else ("SAHV" if d.weekday() == 5 else "JOHV")


def features(start=date(2024, 1, 1), end=date(2025, 9, 30), seed=0):
    """Synthetic features_daily: level x weekday factor x noise, no holidays."""
    rng = np.random.default_rng(seed)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    wk = [1.0, 1.0, 1.0, 1.0, 0.95, 0.6, 0.4]
    rows = []
    for sid, (_, level) in STATIONS.items():
        for d in days:
            rows.append(
                {
                    "station_id": sid,
                    "date": d,
                    "n_entries": int(level * wk[d.weekday()] * rng.uniform(0.95, 1.05)),
                    "quality_flag": None,
                    "network_ratio": 1.0,
                    "weekday": d.weekday() + 1,
                    "month": d.month,
                    "day_of_year": d.timetuple().tm_yday,
                    "year": d.year,
                    "is_covid": False,
                    "is_strike_2019": False,
                    "is_public_holiday": False,
                    "is_bridge": False,
                    "is_school_holiday": False,
                    "day_type": day_type(d),
                    "precip_mm": 0.0,
                    "snow_cm": 0.0,
                    "precip_hours": 0.0,
                    "tmax_c": 15.0,
                    "tmin_c": 8.0,
                    "short_pass_share": 0.01 if d < date(2025, 1, 1) else 0.17,
                    "station_type": "leaky",
                    "am_share_7_10": -1.0,
                }
            )
    return pl.DataFrame(rows, schema_overrides={"quality_flag": pl.String})


def small_cfg(**kw):
    g = replace(
        gbm.GBMConfig(),
        num_boost_round=30,
        params={**gbm.GBMConfig().params, "num_threads": 1, "min_data_in_leaf": 5},
    )
    base = bt.BacktestConfig(
        train_start=date(2024, 1, 1),
        n_origins=2,
        horizon=30,
        warmup_origins=2,
        quantile_rounds=20,
        gbm=g,
    )
    return replace(base, **kw)


# --- frozen features ---------------------------------------------------------------


def test_period_bounds_quarters_and_semesters():
    assert period_bounds("2025Q3") == (date(2025, 7, 1), date(2025, 10, 1))
    assert period_bounds("2024Q4") == (date(2024, 10, 1), date(2025, 1, 1))
    assert period_bounds("2024S1") == (date(2024, 1, 1), date(2024, 7, 1))
    with pytest.raises(ValueError):
        period_bounds("2024")


def test_periods_before_origin_cover_12_months():
    ps = ["2023S2", "2024S1", "2024Q3", "2024Q4", "2025Q1", "2025Q2", "2025Q3"]
    # 2025Q2 ends on 2025-07-01: usable from that origin on, not before
    assert periods_before(ps, date(2025, 7, 1)) == ["2024Q3", "2024Q4", "2025Q1", "2025Q2"]
    assert periods_before(ps, date(2025, 10, 1)) == ["2024Q4", "2025Q1", "2025Q2", "2025Q3"]
    # only 3 quarters ended: a semester completes the 12 months
    assert periods_before(ps, date(2025, 6, 1)) == ["2024S1", "2024Q3", "2024Q4", "2025Q1"]
    # semesters only (profiles before mid-2024)
    assert periods_before(ps, date(2024, 7, 1)) == ["2023S2", "2024S1"]
    assert periods_before(["2024S1", "2024Q1"], date(2024, 7, 1)) == ["2024S1"]  # no overlap


def test_short_pass_share_frozen_at_last_value_before_origin():
    df = pl.DataFrame(
        {
            "date": [date(2025, 5, 31), date(2025, 6, 1), date(2025, 7, 15)],
            "short_pass_share": [0.10, 0.15, 0.20],
        }
    )
    out = freeze_short_pass_share(df, date(2025, 6, 1))
    assert out["short_pass_share"].to_list() == [0.10, 0.10, 0.10]


def test_station_types_ignore_profiles_after_origin():
    prof = profiles()
    # after the origin, station 1 switches to an evening profile: must not be seen
    late = pl.DataFrame(profile_rows(1, 18, ["2025Q3"]))
    prof = pl.concat(
        [prof.filter(~((pl.col("station_id") == 1) & (pl.col("period") == "2025Q3"))), late]
    )
    before = frozen_station_types(prof, date(2025, 7, 1))
    am = dict(before.select("station_id", "am_share_7_10").iter_rows())
    assert am[1] == pytest.approx(0.6 + 2 * 0.4 / 23)  # only the morning-peak quarters
    assert dict(before.select("station_id", "station_type").iter_rows())[1] == "origin"
    after = frozen_station_types(prof, date(2025, 10, 1))  # 2025Q3 now usable
    assert dict(after.select("station_id", "am_share_7_10").iter_rows())[1] < am[1]


def test_station_types_need_enough_periods():
    with pytest.raises(ValueError):
        frozen_station_types(profiles(periods=["2025Q2"]), date(2025, 7, 1))


def test_apply_frozen_replaces_leaky_columns():
    df = features(start=date(2025, 5, 1), end=date(2025, 7, 31))
    out = apply_frozen(df, date(2025, 7, 1), profiles())
    assert set(out["station_type"].unique()) == {"origin", "mixed", "destination"}
    assert out["am_share_7_10"].min() > 0
    assert out.filter(pl.col("date") >= date(2025, 7, 1))[
        "short_pass_share"
    ].unique().to_list() == [0.17]


# --- baselines -----------------------------------------------------------------------


def hist(rows):
    return pl.DataFrame(
        rows, schema=["station_id", "date", "weekday", "day_type", "n_entries"], orient="row"
    )


def test_seasonal_naive_same_weekday_last_4_weeks():
    o = date(2025, 6, 2)  # a Monday
    rows = [(1, o - timedelta(weeks=w), 1, "JOHV", 100 * w) for w in range(1, 6)]  # 5 Mondays
    rows.append((1, o - timedelta(days=1), 7, "DIJFP", 5))  # a Sunday: other weekday
    targets = pl.DataFrame({"station_id": [1, 1, 2], "weekday": [1, 7, 1]})
    p = baselines.seasonal_naive(hist(rows), targets, o, weeks=4)
    assert p.to_list() == [250.0, 5.0, None]  # mean of 100..400; week 5 is outside


def test_day_type_mean_last_12_months():
    o = date(2025, 6, 1)
    rows = [
        (1, o - timedelta(days=10), 2, "JOHV", 100),
        (1, o - timedelta(days=300), 2, "JOHV", 200),
        (1, o - timedelta(days=400), 2, "JOHV", 9999),  # older than 365 days
        (1, o - timedelta(days=5), 6, "SAHV", 50),
    ]
    targets = pl.DataFrame({"station_id": [1, 1, 1], "day_type": ["JOHV", "SAHV", "DIJFP"]})
    assert baselines.day_type_mean(hist(rows), targets, o).to_list() == [150.0, 50.0, None]


# --- metrics -------------------------------------------------------------------------


def test_metrics_wape_mae_and_mape_floor():
    long = pl.DataFrame(
        {"model": ["m"] * 3, "y": [1000.0, 3000.0, 3.0], "pred": [1100.0, 2700.0, 9.0]}
    )
    r = summarize(long, []).row(0, named=True)
    assert r["wape"] == pytest.approx((100 + 300 + 6) / 4003)
    assert r["mae"] == pytest.approx(406 / 3)
    assert r["mape"] == pytest.approx((0.1 + 0.1) / 2)  # y = 3 is below the MAPE floor


def test_horizon_buckets():
    h = pl.DataFrame({"h": [1, 7, 8, 28, 29, 60, 61]})
    got = h.select(horizon_bucket(pl.col("h")).alias("b"))["b"].to_list()
    assert got == ["1-7", "1-7", "8-28", "8-28", "29-60", "29-60", None]


def test_gains_vs_baselines():
    t = pl.DataFrame({"model": ["lgbm", "naive"], "wape": [0.08, 0.10]})
    assert gains(t, "lgbm", ["naive"], [])["gain_vs_naive"][0] == pytest.approx(0.2)


def test_recency_weights_halve_each_half_life():
    t = pl.DataFrame({"date": [date(2025, 1, 1), date(2024, 1, 2)]})
    np.testing.assert_allclose(gbm.recency_weights(t, 365), [1.0, 0.5])
    assert gbm.recency_weights(t, None) is None


# --- backtest -----------------------------------------------------------------------


def test_origins_monthly_with_full_horizon():
    assert bt.origins(date(2026, 6, 30), 3, 60) == [
        date(2026, 3, 1),
        date(2026, 4, 1),
        date(2026, 5, 1),
    ]
    assert bt.origins(date(2026, 6, 30), 1, 30) == [date(2026, 6, 1)]


def test_exclude_reasons():
    df = pl.DataFrame(
        {
            "n_entries": [None, 10, 10, 10, 10, 10, 10, 10, 10],
            "quality_flag": ["missing", None, None, None, None, "low", "high", None, None],
            "is_covid": [False, True, False, False, False, False, False, False, False],
            "is_strike_2019": [False, False, True, False, False, False, False, False, False],
            "day_type": ["JOHV", "JOHV", "JOHV", "JOHV", "JOVS", "JOHV", "JOHV", "JOHV", "JOHV"],
            "network_ratio": [1.0, 1.0, 1.0, 0.5, 0.5, 1.0, 1.0, 1.0, 1.0],
            "is_closure": [False] * 8 + [True],
        }
    )
    got = df.select(bt.exclude_reason(df, 0.8))["exclude"].to_list()
    # a low network day in school holidays (JOVS) is a normal holiday dip, not a disruption
    assert got == [
        "missing",
        "covid",
        "strike_2019",
        "network_disruption",
        None,
        "flag_low",
        "flag_high",
        None,
        "closure",
    ]


def test_run_origin_has_no_leakage():
    cfg = small_cfg()
    data = bt.prepare(features(), cfg)
    o = date(2025, 7, 1)
    a = bt.run_origin(data, profiles(), o, cfg).predictions
    # change every target from the origin on: predictions must not move
    future = data.with_columns(
        pl.when(pl.col("date") >= o).then(pl.col("n_entries") * 10).otherwise(pl.col("n_entries"))
    )
    b = bt.run_origin(future, profiles(), o, cfg).predictions
    for m in ["naive_4w", "daytype_12m", "lgbm", "lgbm_q10", "lgbm_q90", "busy_threshold"]:
        np.testing.assert_allclose(a[m].to_numpy(), b[m].to_numpy())
    assert a["date"].min() == o and a["horizon"].max() == cfg.horizon
    assert set(a["station_type"].unique()) <= {"origin", "mixed", "destination"}


def test_flagged_days_left_out_of_training_and_scoring():
    cfg = small_cfg(weather_variant=False)
    o = date(2025, 7, 1)
    df = (
        features()
        .with_columns(
            pl.when(pl.col("date") == o + timedelta(days=2))
            .then(pl.lit("low"))
            .otherwise(pl.col("quality_flag"))
            .alias("quality_flag"),
            # an absurd value on a flagged training day must not reach the naive baseline
            pl.when((pl.col("date") == o - timedelta(days=7)) & (pl.col("station_id") == 1))
            .then(pl.lit(10**9))
            .otherwise(pl.col("n_entries"))
            .alias("n_entries"),
        )
        .with_columns(
            pl.when((pl.col("date") == o - timedelta(days=7)) & (pl.col("station_id") == 1))
            .then(pl.lit("high"))
            .otherwise(pl.col("quality_flag"))
            .alias("quality_flag")
        )
    )
    p = bt.run_origin(bt.prepare(df, cfg), profiles(), o, cfg).predictions
    flagged = p.filter(pl.col("date") == o + timedelta(days=2))
    assert flagged["exclude"].unique().to_list() == ["flag_low"]
    assert not flagged["scored"].any()
    assert p.filter(pl.col("station_id") == 1)["naive_4w"].max() < 2000


def test_run_and_report_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(intervals, "MIN_CAL", 20)
    proc = tmp_path / "processed"
    proc.mkdir()
    features().write_parquet(proc / "features_daily.parquet")
    profiles().write_parquet(proc / "station_profiles.parquet")
    paths = bt.Paths(proc)
    cfg = small_cfg()
    done = bt.run_origins(paths, cfg, [date(2025, 8, 1)], log=lambda _: None)
    assert done == [date(2025, 8, 1)]
    with pytest.raises(FileNotFoundError):  # the other origins are not run yet
        bt.build_report(paths, cfg, log=lambda _: None)
    bt.run_origins(paths, cfg, log=lambda _: None)
    out = bt.build_report(paths, cfg, log=lambda _: None)
    report = (proc / "backtest/report.md").read_text(encoding="utf-8")
    assert "WAPE by station type × horizon bucket" in report
    assert "80 % intervals" in report
    m = out["metrics"].filter((pl.col("dimension") == "overall") & (pl.col("level") == "station"))
    assert set(m["model"]) == {"naive_4w", "daytype_12m", "lgbm"}
    # warm-up origins (2025-06, 2025-07) only calibrate: not in any output table
    assert sorted(out["predictions"]["origin"].unique()) == [date(2025, 8, 1), date(2025, 9, 1)]
    cov = out["intervals"].filter(pl.col("dimension") == "overall")
    assert set(cov["method"]) == {"quantile", "conformal", "cqr"}
    with pytest.raises(ValueError):  # results from another configuration are refused
        bt.build_report(paths, replace(cfg, naive_weeks=3), log=lambda _: None)


# --- closures ------------------------------------------------------------------------


def test_closure_uses_past_same_day_group_only():
    df = features(start=date(2024, 1, 1), end=date(2025, 3, 31)).with_columns(
        # station 1 closed for works in March 2025: a few entries remain
        pl.when((pl.col("station_id") == 1) & (pl.col("date") >= date(2025, 3, 1)))
        .then(pl.lit(30))
        .otherwise(pl.col("n_entries"))
        .alias("n_entries"),
    )
    c = df.with_columns(is_closure(df, 0.4)).filter(pl.col("is_closure"))
    assert set(c["station_id"]) == {1}
    assert c["date"].min() == date(2025, 3, 1)  # nothing before: only past days are used
    # the whole month is caught (a centred median would stop flagging a long closure)
    assert c.height == 31
    # Sundays are compared with Sundays: a weekend dip is not a closure
    normal = features(start=date(2024, 1, 1), end=date(2024, 12, 31))
    assert not normal.select(is_closure(normal, 0.4))["is_closure"].any()


# --- intervals -----------------------------------------------------------------------


def test_conformal_level_is_conservative():
    assert intervals.conformal_level(9, 0.9) == 1.0  # ceil(10 * 0.9) / 9
    assert intervals.conformal_level(99, 0.9) == pytest.approx(90 / 99)
    assert intervals.conformal_level(99, 0.1) == pytest.approx(10 / 99)


def log_rows(origin, n, resid, day_type="JOHV", hb="1-7"):
    """Fake forecast log rows: lgbm = 100, y = 100 * exp(resid) (log1p approx)."""
    rng = np.random.default_rng(0)
    r = rng.normal(0, resid, n)
    return pl.DataFrame(
        {
            "origin": [origin] * n,
            "station_id": list(range(n)),
            "date": [origin + timedelta(days=int(i % 20)) for i in range(n)],
            "day_type": [day_type] * n,
            "station_type": ["mixed"] * n,
            "horizon_bucket": [hb] * n,
            "scored": [True] * n,
            "y": np.expm1(np.log1p(100.0) + r),
            "lgbm": [100.0] * n,
            "lgbm_q10": [80.0] * n,
            "lgbm_q90": [120.0] * n,
            "busy_threshold": [150.0] * n,
        }
    )


def test_conformalize_uses_only_earlier_forecasts(monkeypatch):
    monkeypatch.setattr(intervals, "MIN_CAL", 50)
    past = log_rows(date(2025, 1, 1), 400, 0.1)
    target = log_rows(date(2025, 3, 1), 50, 0.1)
    future = log_rows(date(2025, 3, 1), 400, 2.0).with_columns(pl.col("station_id") + 1000)
    a = intervals.conformalize(pl.concat([past, target]), [date(2025, 3, 1)])
    b = intervals.conformalize(pl.concat([past, target, future]), [date(2025, 3, 1)])
    np.testing.assert_allclose(
        a.sort("station_id")["conf_hi"].to_numpy()[:50],
        b.sort("station_id")["conf_hi"].to_numpy()[:50],
    )
    # 80 % band of N(0, 0.1) log residuals: about exp(+-0.128)
    hi = a["conf_hi"][0]
    assert 100 * np.exp(0.10) < hi + 1 < 100 * np.exp(0.17)


def test_band_falls_back_to_coarser_group(monkeypatch):
    monkeypatch.setattr(intervals, "MIN_CAL", 50)
    cal = pl.concat(
        [log_rows(date(2025, 1, 1), 400, 0.1), log_rows(date(2025, 1, 1), 10, 1.0, "SAHV")]
    )
    rows = log_rows(date(2025, 3, 1), 3, 0.1, "SAHV")  # SAHV: too few rows -> horizon bucket
    q = intervals.lookup(rows, intervals.with_scores(cal), "r", [0.9])["q0.9"]
    assert q.null_count() == 0 and q[0] < 0.5


def test_exceed_prob_reads_the_residual_cdf():
    grid = np.array([np.linspace(-0.5, 0.5, len(intervals.GRID))])
    p = intervals.exceed_prob(np.array([0.0]), grid)
    assert p[0] == pytest.approx(0.5)
    assert intervals.exceed_prob(np.array([5.0]), grid)[0] == pytest.approx(0.025)


def test_interval_scores():
    d = pl.DataFrame({"y": [100.0, 100.0], "lo": [90.0, 110.0], "hi": [110.0, 120.0]})
    r = d.select(intervals.interval_aggs("lo", "hi")).row(0, named=True)
    assert r["coverage"] == 0.5
    assert r["rel_width"] == pytest.approx(30 / 200)
    assert r["interval_score"] == pytest.approx((20 + 10 + 10 * 10) / 200)


def test_busy_threshold_same_day_group_last_year():
    o = date(2025, 6, 2)
    rows = [(1, o - timedelta(days=i), 1, "JOHV", 100 + i) for i in range(1, 11)]
    rows += [(1, o - timedelta(days=400), 1, "JOHV", 10**6)]  # older than 365 days
    t = pl.DataFrame({"station_id": [1, 1], "day_type": ["JOVS", "DIJFP"]})
    got = intervals.busy_threshold(hist(rows), t, o).to_list()
    assert got[0] == pytest.approx(110.0, abs=1) and got[1] is None


# --- step 4: publication lag and production weather ---------------------------------


def with_random_weather(df, seed=1):
    """Weather that varies by date (one regional series, same for every station)."""
    dates = df.select("date").unique().sort("date")
    rng = np.random.default_rng(seed)
    w = dates.with_columns(
        pl.Series("tmax_c", rng.uniform(0, 30, dates.height)),
        pl.Series("precip_mm", rng.exponential(2, dates.height)),
    )
    return df.drop("tmax_c", "precip_mm").join(w, on="date", how="left")


def test_default_config_keeps_the_main_fingerprint_and_folder(tmp_path):
    cfg = bt.BacktestConfig()
    fp = bt.config_fingerprint(cfg)
    for k in ["lag_days", "weather_mode", "forecast_days", "quantile_models"]:
        assert k not in fp  # results run before step 4 stay valid
    assert cfg.variant is None and cfg.cutoff(date(2025, 6, 1)) == date(2025, 6, 1)
    lag = replace(cfg, lag_days=120, weather_mode="production")
    assert "lag_days" in bt.config_fingerprint(lag)
    assert lag.variant == "lag120_prod" and replace(cfg, lag_days=75).variant == "lag75_obs"
    assert replace(cfg, weather_mode="production").variant == "lag0_prod"
    assert lag.cutoff(date(2025, 6, 1)) == date(2025, 2, 1)
    paths = bt.Paths(tmp_path)
    assert bt.origin_dir(paths, date(2025, 6, 1)) == tmp_path / "backtest/origins/2025-06-01"
    assert bt.origin_dir(paths, date(2025, 6, 1), lag) == (
        tmp_path / "backtest/variants/lag120_prod/origins/2025-06-01"
    )
    with pytest.raises(ValueError):
        replace(cfg, weather_mode="forecast")


def test_climatology_same_calendar_days_before_cutoff_only():
    days = [date(2023, 1, 1) + timedelta(days=i) for i in range(3 * 365)]
    w = pl.DataFrame({"date": days}).with_columns(
        pl.col("date").dt.year().cast(pl.Float64).alias("tmax_c"),
        *[pl.lit(0.0).alias(c) for c in gbm.WEATHER if c != "tmax_c"],
    )
    clim = wx.climatology(w, date(2025, 1, 1), window=7)
    by = dict(clim.select("doy", "tmax_c").iter_rows())
    assert by[180] == pytest.approx(2023.5)  # mean of 2023 and 2024 only
    # Jan 3 +- 7 days wraps to late December of the previous year
    near_new_year = w.filter(
        (pl.col("date") < date(2025, 1, 1))
        & (
            (pl.col("date").dt.ordinal_day() <= 10)
            | (pl.col("date").dt.ordinal_day() >= 362)  # doy 366 wraps to 3 - 7 = -4 -> 362
        )
    )
    assert by[3] == pytest.approx(near_new_year["tmax_c"].mean())


def test_production_weather_observed_then_climatology():
    o, c = date(2025, 7, 1), date(2025, 3, 1)
    w = pl.DataFrame(
        {"date": [date(2024, 1, 1) + timedelta(days=i) for i in range(700)]}
    ).with_columns(
        pl.col("date").dt.ordinal_day().cast(pl.Float64).alias("tmax_c"),
        *[pl.lit(1.0).alias(c) for c in gbm.WEATHER if c != "tmax_c"],
    )
    test = pl.DataFrame({"date": [o + timedelta(days=i) for i in range(30)]}).with_columns(
        *[pl.lit(-99.0).alias(c) for c in gbm.WEATHER]
    )
    out = wx.production_weather(test, w, o, c, forecast_days=16)
    assert out["weather_source"].to_list() == ["observed"] * 16 + ["climatology"] * 14
    assert (out["tmax_c"][:16] == -99.0).all()  # observed kept for the forecast range
    assert out["tmax_c"][16] == pytest.approx((o + timedelta(days=16)).timetuple().tm_yday)
    assert out.height == test.height and out["date"].to_list() == test["date"].to_list()


def test_run_origin_with_lag_uses_only_data_before_the_cutoff():
    cfg = small_cfg(lag_days=40, weather_mode="production")
    data = bt.prepare(with_random_weather(features()), cfg)
    o = date(2025, 7, 1)
    c = cfg.cutoff(o)
    a = bt.run_origin(data, profiles(), o, cfg).predictions
    # targets, short_pass_share from the cutoff on and weather after the forecast range
    # are unknown at issue time: predictions must not move
    later = data.with_columns(
        pl.when(pl.col("date") >= c).then(pl.col("n_entries") * 10).otherwise(pl.col("n_entries")),
        pl.when(pl.col("date") >= c)
        .then(pl.lit(0.5))
        .otherwise(pl.col("short_pass_share"))
        .alias("short_pass_share"),
        pl.when(pl.col("date") >= o + timedelta(days=16))
        .then(pl.lit(-40.0))
        .otherwise(pl.col("tmax_c"))
        .alias("tmax_c"),
    )
    b = bt.run_origin(later, profiles(), o, cfg).predictions
    for m in ["naive_4w", "daytype_12m", "lgbm", "lgbm_q10", "lgbm_q90", "busy_threshold"]:
        np.testing.assert_allclose(a[m].to_numpy(), b[m].to_numpy())
    assert a["date"].min() == o and a["horizon"].min() == 1  # the gap is not forecast
    assert a["cutoff"].unique().to_list() == [c]
    assert a["days_since_data"].min() == 41 and a["days_since_data"].max() == 40 + cfg.horizon
    assert a.filter(pl.col("horizon") <= 16)["weather_source"].unique().to_list() == ["observed"]
    # baselines read the 4 weeks / 12 months before the cutoff, not before the origin
    late = data.with_columns(
        pl.when(pl.col("date").is_between(c, o, closed="left"))
        .then(pl.col("n_entries") * 10)
        .otherwise(pl.col("n_entries"))
    )
    lag0 = bt.run_origin(late, profiles(), o, replace(cfg, lag_days=0)).predictions
    assert lag0["naive_4w"].mean() > 5 * a["naive_4w"].mean()


def test_calibration_rows_end_at_the_cutoff(monkeypatch):
    monkeypatch.setattr(intervals, "MIN_CAL", 5)
    past = log_rows(date(2025, 1, 1), 100, 0.1)  # dated 2025-01-01 .. 01-20
    rows = intervals.calibration_rows(past, date(2025, 3, 1), date(2025, 1, 11))
    assert rows["date"].max() == date(2025, 1, 10)
    assert intervals.calibration_rows(past, date(2025, 3, 1)).height == 100
    target = log_rows(date(2025, 3, 1), 10, 0.1)
    log = pl.concat([past, target]).with_columns(
        pl.when(pl.col("origin") == date(2025, 3, 1))
        .then(pl.lit(date(2025, 1, 11)))
        .otherwise(pl.lit(date(2024, 11, 22)))
        .alias("cutoff")
    )
    b = intervals.conformalize(log.drop("lgbm_q10", "lgbm_q90"), [date(2025, 3, 1)])
    assert b["n_cal"][0] == rows.height
    assert b["cqr_lo"].is_nan().all() and b["conf_hi"].is_not_nan().all()


def test_variant_run_report_and_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(intervals, "MIN_CAL", 20)
    proc = tmp_path / "processed"
    proc.mkdir()
    with_random_weather(features()).write_parquet(proc / "features_daily.parquet")
    profiles().write_parquet(proc / "station_profiles.parquet")
    paths = bt.Paths(proc)
    main_cfg = small_cfg(quantile_models=False)
    bt.run_origins(paths, main_cfg, log=lambda _: None)
    bt.build_report(paths, main_cfg, log=lambda _: None)
    cfg = small_cfg(lag_days=20, weather_mode="production", quantile_models=False)
    bt.run_origins(paths, cfg, log=lambda _: None)
    out = bt.build_report(paths, cfg, log=lambda _: None)
    vdir = proc / "backtest/variants/lag20_prod"
    report = (vdir / "report.md").read_text(encoding="utf-8")
    assert "Publication lag 20 days" in report and "production-like" in report
    assert set(out["intervals"]["method"]) == {"conformal"}
    s = bt.summary(paths, log=lambda _: None)
    assert s.select("lag", "weather").unique().sort("lag").rows() == [
        (0, "observed"),
        (20, "production"),
    ]
    lg = s.filter(pl.col("model") == "lgbm")
    assert lg["coverage"].is_not_null().all()
    assert (proc / "backtest/variants/summary.md").exists()
