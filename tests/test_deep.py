"""Option C: deep-model inputs (no leakage) and scoring (models/deep.py)."""

from datetime import date, timedelta

import numpy as np
import polars as pl
from test_models import features, profiles, small_cfg, with_random_weather

from idf_crowding.models import backtest as bt
from idf_crowding.models import deep


def inputs(df=None, origin=date(2025, 7, 1)):
    cfg = small_cfg()
    data = bt.prepare(df if df is not None else features(), cfg)
    return deep.origin_inputs(data, profiles(), origin, cfg, deep.DeepConfig(min_history=100))


def test_inputs_grid_mask_and_future():
    o = date(2025, 7, 1)
    t, s, info = inputs(origin=o)
    assert info["n_series"] == 6 and s.height == 6
    assert set(t.columns) >= {"unique_id", "ds", "y", "available_mask", *deep.FUTR}
    fut = t.filter(pl.col("is_future"))
    assert fut["ds"].min() == o and fut["ds"].max() == o + timedelta(days=29)
    assert fut["y"].null_count() == fut.height and fut["available_mask"].sum() == 0
    past = t.filter(~pl.col("is_future"))
    assert past["y"].null_count() == 0
    # one row per station per day: a complete grid
    assert past.group_by("unique_id").len()["len"].n_unique() == 1
    assert set(s.columns) == {"unique_id", *deep.STATIC}


def test_excluded_days_are_masked_not_dropped():
    o = date(2025, 7, 1)
    bad = o - timedelta(days=10)
    df = features().with_columns(
        pl.when(pl.col("date") == bad)
        .then(pl.lit("low"))
        .otherwise(pl.col("quality_flag"))
        .alias("quality_flag")
    )
    t, _, _ = inputs(df, o)
    row = t.filter(pl.col("ds") == bad)
    assert row.height == 6 and row["available_mask"].sum() == 0
    assert row["y"].null_count() == 0  # filled so input windows are complete


def test_inputs_ignore_targets_after_origin():
    o = date(2025, 7, 1)
    a, sa, _ = inputs(origin=o)
    future = features().with_columns(
        pl.when(pl.col("date") >= o).then(pl.col("n_entries") * 10).otherwise(pl.col("n_entries"))
    )
    b, sb, _ = inputs(future, o)
    assert a.equals(b) and sa.equals(sb)


def test_short_pass_share_frozen_in_future_rows():
    t, _, _ = inputs(origin=date(2025, 7, 1))
    fut = t.filter(pl.col("is_future"))["short_pass_share"].unique().to_list()
    assert len(fut) == 1


def test_score_against_lgbm(tmp_path):
    o = date(2025, 7, 1)
    pred = pl.DataFrame(
        {
            "origin": [o] * 4,
            "station_id": [1, 1, 2, 2],
            "date": [o, o + timedelta(days=1)] * 2,
            "horizon": [1, 2, 1, 2],
            "horizon_bucket": ["1-7"] * 4,
            "station_type": ["mixed"] * 4,
            "day_type": ["JOHV"] * 4,
            "y": [100.0, 100.0, 200.0, 200.0],
            "naive_4w": [90.0] * 4,
            "daytype_12m": [90.0] * 4,
            "lgbm": [110.0, 110.0, 180.0, 180.0],
            "scored": [True, True, True, False],
        }
    )
    (tmp_path / "backtest").mkdir()
    pred.write_parquet(tmp_path / "backtest/predictions.parquet")
    fc_dir = tmp_path / "fc"
    fc_dir.mkdir()
    pl.DataFrame(
        {
            "station_id": [1, 1, 2, 2],
            "date": [o, o + timedelta(days=1)] * 2,
            "origin": [o] * 4,
            "model": ["nhits"] * 4,
            "q10": [80.0] * 4,
            "q50": [100.0, 100.0, 200.0, 999.0],
            "q90": [120.0] * 4,
        }
    ).write_parquet(fc_dir / "nhits_2025-07-01.parquet")
    t = deep.score(bt.Paths(tmp_path), fc_dir, log=lambda _: None)
    w = dict(t["overall"].select("model", "wape").iter_rows())
    assert w["nhits"] == 0.0  # the unscored row (999) is not counted
    assert w["lgbm"] == np.float64(40 / 400)
    assert w["ens_lgbm_nhits"] == np.float64(20 / 400)
    assert (tmp_path / "backtest/deep/report.md").exists()


def test_export_plan_warmup_before_scored():
    cfg = small_cfg()
    last = date(2026, 6, 30)
    warm, scored = bt.all_origins(last, cfg)
    plan = deep.export_plan(last, cfg, warmup=True)
    assert [o for o, _ in plan] == warm + scored
    assert [r for _, r in plan] == ["warmup"] * len(warm) + ["scored"] * len(scored)
    assert all(w < scored[0] for w in warm)
    assert deep.export_plan(last, cfg, warmup=False) == [(o, "scored") for o in scored]


def test_seed_models():
    ms = ["nhits", "tft", "tft_s2", "tft_s10", "tftx", "ens_lgbm_tft"]
    assert deep.seed_models(ms) == ["tft", "tft_s10", "tft_s2"]


def _busy_log(seed=0):
    """Three monthly origins, 60-day horizons, 5 stations; p_busy noisy but informative."""
    rng = np.random.default_rng(seed)
    rows = []
    for o in [date(2025, 1, 1), date(2025, 2, 1), date(2025, 3, 1)]:
        for st in range(5):
            for h in range(60):
                p = rng.uniform()
                rows.append(
                    {
                        "origin": o,
                        "station_id": st,
                        "date": o + timedelta(days=h),
                        "scored": True,
                        "p_busy": p,
                        "busy_threshold": 100.0,
                        "y": 150.0 if rng.uniform() < p**2 else 50.0,
                    }
                )
    return pl.DataFrame(rows)


def test_recalibrate_busy_uses_only_earlier_outcomes(monkeypatch):
    from idf_crowding.models import intervals

    monkeypatch.setattr(intervals, "MIN_CAL", 20)
    o = date(2025, 3, 1)
    log = _busy_log()
    a = intervals.recalibrate_busy(log, [o])
    assert a["p_busy_iso"].is_not_nan().all()
    # flip every outcome dated on or after the origin (its own rows and earlier origins')
    flipped = log.with_columns(
        pl.when(pl.col("date") >= o).then(200.0 - pl.col("y")).otherwise(pl.col("y")).alias("y")
    )
    b = intervals.recalibrate_busy(flipped, [o])
    assert a.equals(b)
    # but earlier outcomes do matter
    c = intervals.recalibrate_busy(log.with_columns(pl.lit(150.0).alias("y")), [o])
    assert not a.equals(c)


# --- step 4: publication lag and production weather ---------------------------------


def test_inputs_with_lag_end_history_at_the_cutoff():
    o = date(2025, 7, 1)
    cfg = small_cfg(lag_days=40, weather_mode="production")
    c = cfg.cutoff(o)
    df = with_random_weather(features())

    def run(d):
        data = bt.prepare(d, cfg)
        return deep.origin_inputs(data, profiles(), o, cfg, deep.DeepConfig(min_history=100))

    t, s, info = run(df)
    assert info["cutoff"] == c.isoformat()
    fut = t.filter(pl.col("is_future"))
    assert fut["ds"].min() == c and fut["ds"].max() == o + timedelta(days=cfg.horizon - 1)
    # model h = lag + horizon rows per station
    assert fut.group_by("unique_id").len()["len"].unique().to_list() == [40 + cfg.horizon]
    assert t.filter(~pl.col("is_future"))["ds"].max() == c - timedelta(days=1)
    # targets and short_pass_share from the cutoff on, weather after the forecast range:
    # unknown at issue time, inputs must not change
    later = df.with_columns(
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
    t2, s2, _ = run(later)
    assert t.equals(t2) and s.equals(s2)
    # observed weather on the gap and the first 16 days is used (known at issue time)
    gap = df.with_columns(
        pl.when(pl.col("date") == c + timedelta(days=3))
        .then(pl.lit(-40.0))
        .otherwise(pl.col("tmax_c"))
        .alias("tmax_c")
    )
    assert not run(gap)[0].equals(t)


def test_score_variant_ignores_gap_rows(tmp_path):
    o = date(2025, 7, 1)
    cfg = small_cfg(lag_days=10, weather_mode="production")
    pred = pl.DataFrame(
        {
            "origin": [o] * 2,
            "station_id": [1, 2],
            "date": [o, o],
            "horizon": [1, 1],
            "horizon_bucket": ["1-7"] * 2,
            "station_type": ["mixed"] * 2,
            "day_type": ["JOHV"] * 2,
            "y": [100.0, 200.0],
            "naive_4w": [90.0] * 2,
            "daytype_12m": [90.0] * 2,
            "lgbm": [110.0, 180.0],
            "scored": [True, True],
        }
    )
    vdir = tmp_path / "backtest/variants/lag10_prod"
    vdir.mkdir(parents=True)
    pred.write_parquet(vdir / "predictions.parquet")
    fc_dir = tmp_path / "fc"
    fc_dir.mkdir()
    gap_day = o - timedelta(days=3)
    pl.DataFrame(
        {
            "station_id": [1, 2, 1, 2],
            "date": [o, o, gap_day, gap_day],
            "origin": [o] * 4,
            "model": ["tft"] * 4,
            "q10": [80.0] * 4,
            "q50": [100.0, 200.0, 999.0, 999.0],
            "q90": [120.0] * 4,
        }
    ).write_parquet(fc_dir / "tft_2025-07-01.parquet")
    t = deep.score(bt.Paths(tmp_path), fc_dir, cfg, log=lambda _: None)
    w = dict(t["overall"].select("model", "wape").iter_rows())
    assert w["tft"] == 0.0 and t["overall"]["n"][0] == 2
    report = (vdir / "deep/report.md").read_text(encoding="utf-8")
    assert "Variant lag10_prod" in report


def test_seed_average_needs_every_seed():
    o = date(2025, 7, 1)
    fc = pl.DataFrame(
        {
            "origin": [o] * 5,
            "station_id": [1, 1, 1, 2, 2],
            "date": [o] * 5,
            "model": ["tft", "tft_s2", "tft_s3", "tft", "tft_s2"],
            "q10": [1.0, 2.0, 3.0, 1.0, 1.0],
            "q50": [10.0, 20.0, 30.0, 1.0, 1.0],
            "q90": [100.0, 200.0, 300.0, 1.0, 1.0],
        }
    )
    a = deep.seed_average(fc, ["tft", "tft_s2", "tft_s3"])
    assert a.height == 1 and a["station_id"][0] == 1  # station 2 lacks seed 3
    assert a.select("q10", "q50", "q90").row(0) == (2.0, 20.0, 200.0)
    assert a["model"][0] == "tft_seedavg"
