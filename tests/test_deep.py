"""Option C: deep-model inputs (no leakage) and scoring (models/deep.py)."""

from datetime import date, timedelta

import numpy as np
import polars as pl
from test_models import features, profiles, small_cfg

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
