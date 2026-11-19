"""Per-station accuracy (docs/data-quality.md "Per-station accuracy")."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest
from jsonschema import Draft202012Validator

from idf_crowding.score import accuracy as acc
from idf_crowding.score.places import PlaceOverride, assign

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
NOW = datetime(2026, 11, 19, tzinfo=UTC)
O1, O2 = date(2025, 6, 1), date(2025, 7, 1)


def schema(name: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads((SCHEMAS / f"{name}.schema.json").read_text()))


def log_rows(rows):
    """rows = (origin, station_id, date, y, forecast, scored)."""
    cols = ["origin", "station_id", "date", "y", acc.MODEL, "scored"]
    return pl.DataFrame(rows, schema=cols, orient="row").with_columns(
        pl.col("y", acc.MODEL).cast(pl.Float64),
        ((pl.col("date") - pl.col("origin")).dt.total_days() + 121).alias("days_since_data"),
    )


def write_log(processed: Path, df: pl.DataFrame, bands: pl.DataFrame | None = None) -> Path:
    vdir = acc.variant_dir(processed)
    (vdir / "deep").mkdir(parents=True)
    df.write_parquet(vdir / "deep" / "predictions.parquet")
    (vdir / "variant.json").write_text('{"lag_days": 120, "weather_mode": "production"}')
    if bands is not None:
        bands.write_parquet(vdir / "deep" / "ensemble_bands.parquet")
    return vdir


def days(n, start=O1):
    return [start + timedelta(i) for i in range(n)]


def test_wape_is_sum_abs_error_over_sum_y_and_days_are_distinct_dates():
    d = date(2025, 7, 10)
    log = acc.load_log_frame(
        log_rows(
            [
                (O1, 1, d, 100, 110, True),  # same date, two origins: both rows count
                (O2, 1, d, 100, 70, True),
                (O2, 1, d + timedelta(1), 200, 200, True),
                (O2, 1, d + timedelta(2), 900, 0, False),  # not scored: ignored
            ]
        )
    )
    (row,) = acc.station_table(log).to_dicts()
    assert row["wape"] == pytest.approx((10 + 30 + 0) / 400)
    assert (row["n_days"], row["n_rows"]) == (2, 3)


def test_min_days_rule():
    rows = [(O1, 1, d, 100, 90, True) for d in days(180)]
    rows += [(O1, 2, d, 100, 90, True) for d in days(179)]
    log = acc.load_log_frame(log_rows(rows))
    members = assign([1, 2, 3], [])
    out = acc.place_accuracy(acc.place_table(log, members), ["1", "2", "3"])
    assert out["1"] == {"wape_pct": 10.0, "n_days": 180}
    assert out["2"] is None  # 179 scored days
    assert out["3"] is None  # not in the log


def test_merged_place_uses_summed_forecasts_where_every_member_is_scored():
    members = assign([1, 2], [PlaceOverride("hub", "Hub", (1, 2))])
    rows = []
    for d in days(200):
        rows += [(O1, 1, d, 100, 120, True), (O1, 2, d, 100, 80, True)]  # errors cancel
    rows.append((O1, 1, date(2026, 1, 1), 100, 500, True))  # member 2 missing that day
    log = acc.load_log_frame(log_rows(rows))
    out = acc.place_accuracy(acc.place_table(log, members), ["hub"])
    assert out["hub"] == {"wape_pct": 0.0, "n_days": 200}


def test_compute_without_log_is_none(tmp_path):
    assert acc.compute(tmp_path, assign([1], []), NOW) is None


def test_summary_tiles_and_schema(tmp_path):
    rows = [(O1, 1, d, 1000, 900, True) for d in days(200)]
    rows += [(O1, 2, d, 100, 150, True) for d in days(200)]
    df = log_rows(rows)
    bands = df.select(
        "origin",
        "station_id",
        "date",
        pl.when(pl.col("station_id") == 1).then(850.0).otherwise(120.0).alias("ens_conf_lo"),
        pl.when(pl.col("station_id") == 1).then(1100.0).otherwise(140.0).alias("ens_conf_hi"),
    )
    write_log(tmp_path, df, bands)
    places, rec = acc.compute(tmp_path, assign([1, 2], []), NOW)
    schema("accuracy.v1").validate(rec)
    assert places == {
        "1": {"wape_pct": 10.0, "n_days": 200},
        "2": {"wape_pct": 50.0, "n_days": 200},
    }
    assert rec["places"] == {"n_places": 2, "n_with_figure": 2, "median_pct": 30.0, "p90_pct": 46.0}
    t = rec["tiles"]
    assert t["station_wape_pct"] == pytest.approx(100 * (100 + 50) / 1100, abs=0.05)
    assert t["network_wape_pct"] == pytest.approx(100 * 50 / 1100, abs=0.05)  # +50 / -100
    assert t["band"] == {"level": 0.8, "coverage": 0.5}
    assert "special_days" not in t  # no LightGBM origin logs
    assert rec["log"]["n_origins"] == 1 and rec["log"]["days_since_data"]["min"] == 121
    assert rec["min_days"] == 180


def test_summary_without_bands_leaves_the_tile_out(tmp_path):
    write_log(tmp_path, log_rows([(O1, 1, d, 10, 9, True) for d in days(3)]))
    _, rec = acc.compute(tmp_path, assign([1], []), NOW)
    assert "band" not in rec["tiles"] and rec["places"]["median_pct"] is None
    schema("accuracy.v1").validate(rec)


def test_schema_rejects_unknown_tile_and_negative_error(tmp_path):
    write_log(tmp_path, log_rows([(O1, 1, d, 10, 9, True) for d in days(3)]))
    _, rec = acc.compute(tmp_path, assign([1], []), NOW)
    v = schema("accuracy.v1")
    assert v.is_valid(rec)
    assert not v.is_valid(rec | {"tiles": {"best_station": 1}})
    assert not v.is_valid(rec | {"tiles": {"station_wape_pct": -1}})
