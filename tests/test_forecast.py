"""Step 4c: production forecast (models/forecast.py) and its TFT export."""

import json
from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest
from test_models import features, log_rows, profiles, small_cfg, with_random_weather

from idf_crowding.models import deep, intervals
from idf_crowding.models import forecast as fx
from idf_crowding.models.gbm import WEATHER

C = date(2025, 10, 1)  # day after the last data day of the `features` fixture


def weather_table(last=date(2025, 10, 20)):
    days = pl.date_range(date(2024, 1, 1), last, "1d", eager=True)
    return pl.DataFrame({"date": days}).with_columns(
        pl.col("date").dt.ordinal_day().cast(pl.Float64).alias("tmax_c"),
        *[pl.lit(1.0).alias(c) for c in WEATHER if c != "tmax_c"],
    )


def test_cutoff_is_the_day_after_the_last_target():
    df = features().with_columns(
        pl.when(pl.col("date") > date(2025, 9, 20))
        .then(None)
        .otherwise(pl.col("n_entries"))
        .alias("n_entries")
    )
    assert fx.cutoff_of(df) == date(2025, 9, 21)


def test_future_weather_observed_then_climatology():
    dates = pl.date_range(C, C + timedelta(days=29), "1d", eager=True)
    w = fx.future_weather(weather_table(), dates)
    src = w["weather_source"].to_list()
    assert src == ["observed"] * 20 + ["climatology"] * 10
    later = w.filter(pl.col("weather_source") == "climatology")
    # climatology of tmax = day of year: about the day of year (the last observed year
    # only covers days before the cutoff of the window, so the mean is a bit lower)
    doy = later["date"].dt.ordinal_day().cast(pl.Float64)
    assert np.allclose(later["tmax_c"].to_numpy(), doy.to_numpy(), atol=2)
    assert fx.future_weather(None, dates)["weather_source"].unique().to_list() == ["none"]


def test_future_frame_active_stations_calendar_and_schema():
    df = features().with_columns(  # station 6 stopped reporting 6 weeks before the cutoff
        pl.when((pl.col("station_id") == 6) & (pl.col("date") >= C - timedelta(days=42)))
        .then(None)
        .otherwise(pl.col("n_entries"))
        .alias("n_entries")
    )
    hol = pl.DataFrame({"date": [date(2025, 11, 11)], "holiday_name": ["Armistice"]})
    end = C + timedelta(days=60)
    f = fx.future_frame(df, C, end, hol, None, weather_table(), active_days=28)
    assert sorted(f["station_id"].unique()) == [1, 2, 3, 4, 5]
    assert f["date"].min() == C and f["date"].max() == end - timedelta(days=1)
    assert f.height == 5 * 60
    assert f.columns == [*df.columns, "weather_source"]
    assert (
        f.schema["n_entries"] == df.schema["n_entries"] and f["n_entries"].null_count() == f.height
    )
    nov11 = f.filter(pl.col("date") == date(2025, 11, 11))
    assert nov11["is_public_holiday"].all()
    # short_pass_share frozen at its last value before the cutoff
    assert f["short_pass_share"].unique().to_list() == [0.17]


def ext_frame():
    df = with_random_weather(features())
    end = C + timedelta(days=60)
    fut = fx.future_frame(df, C, end, None, None, weather_table(), 28)
    hist = df.with_columns(pl.lit("observed").alias("weather_source"))
    return pl.concat([hist, fut], how="vertical_relaxed"), end


def test_lgbm_forecast_window_and_horizons():
    ext, end = ext_frame()
    issue = C + timedelta(days=10)
    fc = fx.lgbm_forecast(ext, profiles(), C, issue, end, small_cfg())
    assert fc["date"].min() == issue and fc["date"].max() == end - timedelta(days=1)
    assert fc["horizon"].min() == 1 and fc["days_since_data"].min() == 11
    assert fc.height == 6 * 50 and (fc["lgbm"] > 0).all()
    assert set(fc["weather_source"]) == {"observed", "climatology"}
    with pytest.raises(ValueError):  # data too old for this issue date
        fx.lgbm_forecast(ext, profiles(), C, end, end, small_cfg())


def test_combine_mean_of_models_fallback_and_band_before_cutoff(monkeypatch):
    monkeypatch.setattr(intervals, "MIN_CAL", 50)
    c = date(2025, 3, 1)
    lg = pl.DataFrame(
        {
            "station_id": [1, 2],
            "date": [c + timedelta(days=5)] * 2,
            "lgbm": [100.0, 100.0],
            "horizon": [1, 1],
            "horizon_bucket": ["1-7", "1-7"],
            "days_since_data": [6, 6],
            "day_type": ["JOHV", "JOHV"],
            "station_type": ["mixed", "mixed"],
            "weather_source": ["observed"] * 2,
        }
    )
    tft = pl.DataFrame({"station_id": [1], "date": [c + timedelta(days=5)], "tft": [120.0]})
    log = log_rows(date(2025, 1, 1), 400, 0.1).with_columns(pl.col("lgbm").alias("ens"))
    out = fx.combine_frames(lg, tft, log, log, c)
    r1, r2 = out.row(0, named=True), out.row(1, named=True)
    assert r1["model"] == "lgbm+tft" and r1["point"] == 110.0
    assert r2["model"] == "lgbm" and r2["point"] == 100.0 and r2["tft"] is None
    assert r1["lo"] < r1["point"] < r1["hi"]
    # residuals dated on or after the cutoff are not known yet: the band ignores them
    late = log_rows(date(2025, 3, 1), 400, 2.0).with_columns(
        pl.col("lgbm").alias("ens"), pl.col("station_id") + 1000
    )
    both = pl.concat([log, late])
    again = fx.combine_frames(lg, tft, both, both, c)
    assert again.select("lo", "hi").equals(out.select("lo", "hi"))
    # without TFT, every row is lgbm alone
    assert fx.combine_frames(lg, None, log, None, c)["model"].unique().to_list() == ["lgbm"]


def test_export_production_inputs(tmp_path):
    proc, raw = tmp_path / "processed", tmp_path / "raw"
    proc.mkdir()
    raw.mkdir()
    features().write_parquet(proc / "features_daily.parquet")
    profiles().write_parquet(proc / "station_profiles.parquet")
    fcfg = fx.ForecastConfig(days_max=50)
    meta = deep.export_production(
        small_cfg(), tmp_path / "out", fcfg, fx.Paths(raw, proc), log=lambda _: None
    )
    assert meta["horizon"] == 50 and meta["production"] and meta["cutoff"] == C.isoformat()
    t = pl.read_parquet(tmp_path / "out/inputs" / f"{C}.parquet")
    fut = t.filter(pl.col("is_future"))
    assert fut["ds"].min() == C and fut["ds"].max() == C + timedelta(days=49)
    assert fut.group_by("unique_id").len()["len"].unique().to_list() == [50]
    saved = json.loads((tmp_path / "out/inputs/meta.json").read_text())
    assert saved["origins"][0]["role"] == "production"


def test_combine_special_days_use_lgbm_times_factor(monkeypatch):
    monkeypatch.setattr(intervals, "MIN_CAL", 50)
    c = date(2025, 7, 1)
    days = [date(2025, 12, 23), date(2025, 12, 25)]
    lg = pl.DataFrame(
        {
            "station_id": [0, 0],
            "date": days,
            "lgbm": [100.0, 100.0],
            "horizon": [1, 1],
            "horizon_bucket": ["1-7", "1-7"],
            "days_since_data": [6, 6],
            "day_type": ["JOHV", "JOHV"],
            "station_type": ["mixed", "mixed"],
            "weather_source": ["observed"] * 2,
        }
    )
    tft = pl.DataFrame({"station_id": [0, 0], "date": days, "tft": [120.0, 120.0]})
    log = log_rows(date(2025, 1, 1), 400, 0.1).with_columns(pl.col("lgbm").alias("ens"))
    # last Christmas: y = half the lgbm forecast at every station
    xmas = log_rows(date(2024, 12, 25), 400, 0.0).with_columns(
        pl.lit(date(2024, 12, 25)).alias("date"),
        pl.lit(49.5).alias("y"),
        pl.col("lgbm").alias("ens"),
    )
    both = pl.concat([log, xmas])
    out = fx.combine_frames(lg, tft, both, both, c).sort("date")
    ordinary, special = out.rows(named=True)
    assert ordinary["model"] == "lgbm+tft" and ordinary["adjust"] == 1.0
    assert ordinary["special_day"] is None
    assert special["model"] == "lgbm" and special["special_day"] == "christmas_day"
    assert special["point"] == pytest.approx(50.0, rel=0.02)
    assert special["tft"] == 120.0  # raw model columns kept
    assert special["lo"] <= special["point"] <= special["hi"]
    # switched off: the ensemble everywhere
    raw = fx.combine_frames(lg, tft, both, both, c, special=False)
    assert raw["model"].unique().to_list() == ["lgbm+tft"]


def test_combine_keeps_growth_columns(monkeypatch):
    from idf_crowding.models import growth

    monkeypatch.setattr(intervals, "MIN_CAL", 50)
    c = date(2025, 3, 1)
    lg = pl.DataFrame(
        {
            "station_id": [1],
            "date": [c + timedelta(days=5)],
            "lgbm": [100.0],
            "horizon": [1],
            "horizon_bucket": ["1-7"],
            "days_since_data": [6],
            "day_type": ["JOHV"],
            "station_type": ["mixed"],
            "weather_source": ["observed"],
        }
    )
    rates = pl.DataFrame({"cls": ["wk", "sat", "sun"], "g": [1.5, 1.5, 1.5]})
    lg = growth.apply(lg, rates, c)
    tft = pl.DataFrame({"station_id": [1], "date": [c + timedelta(days=5)], "tft": [120.0]})
    log = log_rows(date(2025, 1, 1), 400, 0.1).with_columns(pl.col("lgbm").alias("ens"))
    r = fx.combine_frames(lg, tft, log, log, c).row(0, named=True)
    assert r["lgbm_raw"] == 100.0 and r["growth"] == pytest.approx(1.5 ** (5 / 364))
    assert r["point"] == pytest.approx((r["lgbm"] + 120.0) / 2)
