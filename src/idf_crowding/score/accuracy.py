"""Per-station accuracy for the app: the error of the daily total in the production-like
backtest, per Place (place.v2 `accuracy`) and summarised for the method page
(accuracy.json, schemas/accuracy.v1.schema.json).

Rules (public: docs/data-quality.md "Per-station accuracy"):
1. Source = the forecast log of backtest variant `lag120_prod` (data cutoff = origin - 120
   days, production weather): `deep/predictions.parquet`, rows = origin x station x date,
   scored rows only, model `ens_lgbm_tft_seedavg` = mean(LightGBM, mean of the TFT seeds).
2. WAPE = sum |y - forecast| / sum y over every scored row of the Place (a date covered by
   two origins counts twice, as in the backtest report).
3. Scored days = distinct dates with at least one scored row. Fewer than MIN_DAYS -> null.
4. A Place with several Counting points: y and forecast are summed per origin x date, only
   where every member has a scored row; WAPE and days are taken on those sums.
5. No cap and no outlier removal: a large error is published as it is.
6. Summary tiles cover the Counting points of the app's Places only (stations outside the
   app's scope, such as the T12 tram-train, are left out). They come from the same log
   (station level, network total), its calibrated
   80 % band (`deep/ensemble_bands.parquet`, ensemble conformal band) and the leave-one-year-out
   check of the special-day rule (LightGBM x factor, models/special_days.py) on the variant's
   LightGBM forecast log (`origins/*/predictions.parquet`, growth-corrected as in
   production). A figure whose files are missing is left out.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl

SCHEMA_VERSION = 1
LAG_DAYS = 120  # same variant as the production bands (`[forecast] calib_lag`)
MODEL = "ens_lgbm_tft_seedavg"
MODEL_LABEL = "mean(LightGBM, TFT mean of 3 seeds)"
MIN_DAYS = 180  # owner rule (2026-11-19): fewer scored days -> no per-station figure
BAND_LEVEL = 0.8
DAY_DEFINITION = "distinct dates with at least one scored forecast"
KEYS = ["origin", "station_id", "date"]


def variant_dir(processed: Path, lag: int = LAG_DAYS) -> Path:
    return processed / "backtest" / "variants" / f"lag{lag}_prod"


def load_log_frame(df: pl.DataFrame, model: str = MODEL) -> pl.DataFrame:
    """Scored rows of a deep log: origin, station_id, date, y, pred (+ days_since_data)."""
    keep = [*KEYS, "y", pl.col(model).alias("pred")]
    if "days_since_data" in df.columns:
        keep.append("days_since_data")
    return df.filter(
        pl.col("scored") & pl.col("y").is_not_null() & pl.col(model).is_not_null()
    ).select(keep)


def load_log(vdir: Path, model: str = MODEL) -> pl.DataFrame | None:
    """The variant's deep log (load_log_frame), or None if it or the model column is absent."""
    path = vdir / "deep" / "predictions.parquet"
    if not path.is_file():
        return None
    df = pl.read_parquet(path)
    return load_log_frame(df, model) if model in df.columns else None


def _errors(rows: pl.DataFrame, by: str) -> pl.DataFrame:
    return rows.group_by(by).agg(
        ((pl.col("y") - pl.col("pred")).abs().sum() / pl.col("y").sum()).alias("wape"),
        pl.col("date").n_unique().alias("n_days"),
        pl.len().alias("n_rows"),
    )


def station_table(log: pl.DataFrame) -> pl.DataFrame:
    """station_id, wape (fraction), n_days (distinct scored dates), n_rows."""
    return _errors(log, "station_id").sort("station_id")


def place_table(log: pl.DataFrame, members: pl.DataFrame) -> pl.DataFrame:
    """place_id, wape, n_days, n_rows, n_members, on summed forecasts (rule 4)."""
    size = members.group_by("place_id").agg(pl.len().alias("n_members"))
    summed = (
        log.join(members, on="station_id")
        .group_by("place_id", "origin", "date")
        .agg(pl.col("y").sum(), pl.col("pred").sum(), pl.len().alias("n"))
        .join(size, on="place_id")
        .filter(pl.col("n") == pl.col("n_members"))
    )
    return _errors(summed, "place_id").join(size, on="place_id").sort("place_id")


def place_accuracy(
    table: pl.DataFrame, place_ids: list[str], min_days: int = MIN_DAYS
) -> dict[str, dict[str, Any] | None]:
    """place_id -> {wape_pct, n_days} or None (no scored rows, or fewer than min_days)."""
    rows = {r["place_id"]: r for r in table.iter_rows(named=True)}
    out: dict[str, dict[str, Any] | None] = {}
    for pid in place_ids:
        r = rows.get(pid)
        ok = r is not None and r["n_days"] >= min_days and r["wape"] is not None
        out[pid] = (
            {"wape_pct": round(100 * float(r["wape"]), 1), "n_days": int(r["n_days"])}
            if ok
            else None
        )
    return out


def _pct(x: float | None) -> float | None:
    return None if x is None else round(100 * float(x), 1)


def network_wape(log: pl.DataFrame) -> float | None:
    """Error of the daily network total (sum over scored stations per origin x date)."""
    d = log.group_by("origin", "date").agg(pl.col("y").sum(), pl.col("pred").sum())
    return _pct((d["y"] - d["pred"]).abs().sum() / d["y"].sum()) if d.height else None


def band_coverage(vdir: Path, log: pl.DataFrame) -> float | None:
    """Share of scored station-days inside the calibrated 80 % ensemble band."""
    path = vdir / "deep" / "ensemble_bands.parquet"
    if not path.is_file():
        return None
    b = pl.read_parquet(path, columns=[*KEYS, "ens_conf_lo", "ens_conf_hi"])
    j = log.join(b, on=KEYS).filter(pl.col("ens_conf_lo").is_not_null())
    if j.height == 0:
        return None
    inside = (pl.col("y") >= pl.col("ens_conf_lo")) & (pl.col("y") <= pl.col("ens_conf_hi"))
    return round(float(j.select(inside.mean()).item()), 3)


def special_day_check(
    vdir: Path, features: Path, stations: list[int] | None = None
) -> dict[str, Any] | None:
    """Leave-one-year-out check of the special-day rule (docs/data-quality.md "Special
    days"): factors from outcomes dated before 1 July of the latest Christmas season in the
    LightGBM log, applied to that season's forecasts; station-level WAPE of LightGBM x f."""
    from idf_crowding.models import growth
    from idf_crowding.models import special_days as sd

    files = sorted((vdir / "origins").glob("*/predictions.parquet"))
    if not files or not features.is_file():
        return None
    lg = pl.concat([pl.read_parquet(f) for f in files], how="diagonal")
    need = {"cutoff", "lgbm", "y", "exclude", "station_type"}
    if not need <= set(lg.columns):
        return None
    lg = growth.apply_log(lg, pl.scan_parquet(features))
    clean = lg.filter(
        pl.col("exclude").is_null() & pl.col("y").is_not_null() & pl.col("lgbm").is_not_null()
    ).with_columns(sd.special_day().alias("special_day"))
    seasons = (
        clean.filter(pl.col("special_day").is_not_null())
        .select(pl.col("date").dt.year() - (pl.col("date").dt.month() == 1).cast(pl.Int32))
        .to_series()
        .unique()
        .sort()
        .to_list()
    )
    if len(seasons) < 2:
        return None  # nothing to learn the factors from
    season = seasons[-1]
    cutoff = date(season, 7, 1)
    first_seen = (
        pl.scan_parquet(features)
        .group_by("station_id")
        .agg(pl.col("date").min().alias("first_date"))
        .collect()
    )
    f = sd.factors(lg, "lgbm", cutoff, first_seen=first_seen)
    test = clean.filter(
        pl.col("special_day").is_not_null()
        & (pl.col("date") >= cutoff)
        & (pl.col("date") < date(season + 1, 7, 1))
    ).drop("special_day")
    if test.height == 0 or f.height == 0:
        return None
    out = sd.apply(test, f, cols=("lgbm",))
    if stations is not None:
        out = out.filter(pl.col("station_id").is_in(stations))
        if out.height == 0:
            return None
    w = (out["y"] - out["lgbm"]).abs().sum() / out["y"].sum()
    return {
        "wape_pct": _pct(w),
        "season": season,
        "n_rows": out.height,
        "method": "LightGBM x special-day factor",
    }


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    return round(float(pl.Series(values).quantile(q, interpolation="linear")), 1)


def summary(
    vdir: Path,
    log: pl.DataFrame,
    places: dict[str, dict[str, Any] | None],
    generated_at: datetime,
    features: Path | None = None,
    min_days: int = MIN_DAYS,
    stations: list[int] | None = None,
) -> dict[str, Any]:
    """The accuracy.json record (schemas/accuracy.v1.schema.json). Tiles use the rows of
    `stations` only (default: every station in the log)."""
    meta: dict[str, Any] = {}
    vfile = vdir / "variant.json"
    if vfile.is_file():
        meta = json.loads(vfile.read_text(encoding="utf-8"))
    origins = sorted(log["origin"].unique().to_list())
    rec: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "log": {
            "variant": vdir.name,
            "lag_days": int(meta.get("lag_days", LAG_DAYS)),
            "weather": meta.get("weather_mode", "production"),
            "model": MODEL,
            "model_label": MODEL_LABEL,
            "n_origins": len(origins),
            "origins": {"first": origins[0].isoformat(), "last": origins[-1].isoformat()},
            "period": {
                "start": log["date"].min().isoformat(),
                "end": log["date"].max().isoformat(),
            },
        },
        "min_days": min_days,
        "day_definition": DAY_DEFINITION,
    }
    if "days_since_data" in log.columns:
        rec["log"]["days_since_data"] = {
            "min": int(log["days_since_data"].min()),
            "max": int(log["days_since_data"].max()),
        }
    vals = sorted(v["wape_pct"] for v in places.values() if v is not None)
    rec["places"] = {
        "n_places": len(places),
        "n_with_figure": len(vals),
        "median_pct": _quantile(vals, 0.5),
        "p90_pct": _quantile(vals, 0.9),
    }
    tiles: dict[str, Any] = {}
    if stations is not None:
        log = log.filter(pl.col("station_id").is_in(stations))
    if log.height == 0:
        rec["tiles"] = tiles
        return rec
    tiles["station_wape_pct"] = _pct((log["y"] - log["pred"]).abs().sum() / log["y"].sum())
    net = network_wape(log)
    if net is not None:
        tiles["network_wape_pct"] = net
    cov = band_coverage(vdir, log)
    if cov is not None:
        tiles["band"] = {"level": BAND_LEVEL, "coverage": cov}
    if features is not None:
        sdc = special_day_check(vdir, features, stations)
        if sdc is not None:
            tiles["special_days"] = sdc
    rec["tiles"] = tiles
    return rec


def compute(
    processed: Path,
    members: pl.DataFrame,
    generated_at: datetime,
    lag: int = LAG_DAYS,
    min_days: int = MIN_DAYS,
) -> tuple[dict[str, dict[str, Any] | None], dict[str, Any]] | None:
    """(place_id -> accuracy or None, accuracy.json record), or None without the log."""
    vdir = variant_dir(processed, lag)
    log = load_log(vdir)
    if log is None or log.height == 0:
        return None
    table = place_table(log, members)
    places = place_accuracy(table, sorted(members["place_id"].unique().to_list()), min_days)
    rec = summary(
        vdir,
        log,
        places,
        generated_at,
        processed / "features_daily.parquet",
        min_days,
        stations=sorted(members["station_id"].unique().to_list()),
    )
    return places, rec
