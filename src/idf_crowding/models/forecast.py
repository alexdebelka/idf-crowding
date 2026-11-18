"""Production forecast (step 4c): one-shot, resumable steps, no scheduler in code.

    idf-forecast lgbm    [--issue DATE]   LightGBM fitted on all clean data before the
                                          cutoff; forecasts issue date .. cutoff + days_max - 1
    idf-deep export --production          TFT inputs for the same cutoff (run on a GPU,
                                          notebooks/03_deep_colab.ipynb, 3 seeds)
    idf-forecast combine [--deep DIR] [--issue DATE]
                                          mean(lgbm, mean of TFT seeds) + 80 % conformal band
                                          (lgbm alone, with its own band, without --deep or
                                          for stations TFT does not cover)
    idf-forecast status                   what exists for the current cutoff

Terms: the data cutoff c is the day after the last published data day; the issue date T
(default: today) is the first forecast date; days since data = date - c + 1. One fit per
IDFM release: the forecast runs to c + days_max - 1 (default 225 days: ~75 days of
publication delay + ~90 days to the next release + 60), so a quarterly fit covers the
time until the next release. Each step writes to data/processed/forecast/CUTOFF/.

Future rows (dates >= c) get the calendar of the ingested holiday / school-holiday
sources, the observed weather where it is already downloaded, then the day-of-year
climatology (models/weather.py); `short_pass_share` and station types are frozen at c.
Bands: conformal, from the residuals of the production-like backtest (lag 120, production
weather) dated in the 365 days before c, by day type x station type x horizon bucket
(horizon = days since the issue date). No P(busy) (not calibrated well enough).
Special days (Dec 24, 25, 31, Jan 1; models/special_days.py): lgbm x a per-station factor
learned from the same forecast log (outcomes before c), point and band; columns
`special_day` and `adjust`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from idf_crowding.config import load_config
from idf_crowding.features.calendar import (
    calendar_features,
    load_public_holidays,
    load_school_holidays,
)
from idf_crowding.features.weather import load_weather
from idf_crowding.models import backtest as bt
from idf_crowding.models import gbm, intervals
from idf_crowding.models import special_days as sd
from idf_crowding.models import weather as wx
from idf_crowding.models.frozen import apply_frozen
from idf_crowding.models.gbm import WEATHER
from idf_crowding.models.metrics import horizon_bucket


@dataclass(frozen=True)
class ForecastConfig:
    days_max: int = 225  # forecast up to cutoff + days_max - 1
    active_days: int = 28  # forecast stations with a clean day in the last active_days
    calib_lag: int = 120  # backtest variant whose forecast log calibrates the bands
    calib_deep_dir: str = "deep_colab/lag120_prod/outputs"  # TFT outputs of that variant

    @classmethod
    def from_config(cls) -> ForecastConfig:
        c = load_config().get("forecast", {})
        return cls(**{k: c[k] for k in cls.__dataclass_fields__ if k in c})


@dataclass(frozen=True)
class Paths:
    raw: Path
    processed: Path

    @classmethod
    def from_config(cls) -> Paths:
        d = Path(load_config()["paths"]["data_dir"])
        return cls(d / "raw", d / "processed")

    @property
    def backtest(self) -> bt.Paths:
        return bt.Paths(self.processed)


def cutoff_of(features: pl.DataFrame | pl.LazyFrame) -> date:
    """Day after the last day with published validations."""
    lf = features.lazy() if isinstance(features, pl.DataFrame) else features
    last = lf.filter(pl.col("n_entries").is_not_null()).select(pl.col("date").max()).collect()
    return last.item() + timedelta(days=1)


def forecast_dir(paths: Paths, cutoff: date) -> Path:
    return paths.processed / "forecast" / cutoff.isoformat()


def future_weather(
    observed: pl.DataFrame | None, dates: pl.Series, window: int = 7
) -> pl.DataFrame:
    """date, weather columns, weather_source for `dates`: observed where downloaded,
    day-of-year climatology of all observed days after that."""
    d = pl.DataFrame({"date": dates}).unique().sort("date")
    if observed is None or observed.height == 0:
        return d.with_columns(
            *[pl.lit(None, pl.Float64).alias(c) for c in WEATHER],
            pl.lit("none").alias("weather_source"),
        )
    obs = observed.select("date", *WEATHER).drop_nulls()
    last = obs["date"].max()
    clim = wx.climatology(obs, last + timedelta(days=1), window).rename(
        {c: f"_c_{c}" for c in WEATHER}
    )
    out = (
        d.join(obs, on="date", how="left")
        .with_columns(pl.col("date").dt.ordinal_day().cast(pl.Int32).alias("_doy"))
        .join(clim, left_on="_doy", right_on="doy", how="left")
        .sort("date")
    )
    seen = pl.col("date") <= last
    return out.select(
        "date",
        *[pl.when(seen).then(pl.col(c)).otherwise(pl.col(f"_c_{c}")).alias(c) for c in WEATHER],
        pl.when(seen)
        .then(pl.lit("observed"))
        .otherwise(pl.lit("climatology"))
        .alias("weather_source"),
    )


def future_frame(
    features: pl.DataFrame,
    cutoff: date,
    end: date,
    holidays: pl.DataFrame | None,
    school: pl.DataFrame | None,
    weather: pl.DataFrame | None,
    active_days: int = 28,
) -> pl.DataFrame:
    """Rows with the features_daily columns for every active station x date in
    [cutoff, end): no target, calendar from the holiday sources, weather from
    `future_weather`. Active = a clean day (target present, no quality flag) in the
    `active_days` before the cutoff."""
    recent = features.filter(
        pl.col("date").is_between(cutoff - timedelta(days=active_days), cutoff, closed="left")
        & pl.col("n_entries").is_not_null()
        & pl.col("quality_flag").is_null()
    )
    ids = recent.select("station_id").unique().sort("station_id")
    dates = pl.date_range(cutoff, end - timedelta(days=1), "1d", eager=True)
    cal = calendar_features(dates, holidays, school).join(
        future_weather(weather, dates), on="date", how="left"
    )
    last_share = features.filter(pl.col("date") < cutoff).sort("date")["short_pass_share"][-1]
    rows = ids.join(cal, how="cross").with_columns(pl.lit(last_share).alias("short_pass_share"))
    missing = {c: t for c, t in features.schema.items() if c not in rows.columns}
    rows = rows.with_columns([pl.lit(None, t).alias(c) for c, t in missing.items()])
    return rows.select(*features.columns, "weather_source").with_columns(
        [pl.col(c).cast(t) for c, t in features.schema.items()]
    )


def extended(paths: Paths, fcfg: ForecastConfig) -> tuple[pl.DataFrame, date, date]:
    """features_daily + future rows up to cutoff + days_max; (frame, cutoff, end)."""
    features = pl.read_parquet(paths.processed / "features_daily.parquet")
    c = cutoff_of(features)
    end = c + timedelta(days=fcfg.days_max)
    fut = future_frame(
        features,
        c,
        end,
        load_public_holidays(paths.raw),
        load_school_holidays(paths.raw),
        load_weather(paths.raw),
        fcfg.active_days,
    )
    hist = features.filter(pl.col("date") < c).with_columns(
        pl.lit("observed").alias("weather_source")
    )
    return pl.concat([hist, fut], how="vertical_relaxed"), c, end


def lgbm_forecast(
    ext: pl.DataFrame,
    profiles: pl.DataFrame,
    cutoff: date,
    issue: date,
    end: date,
    cfg: bt.BacktestConfig,
) -> pl.DataFrame:
    """Fit LightGBM on clean rows before the cutoff, predict future rows dated in
    [issue, end). `ext` = features + future rows (`extended`)."""
    if not cutoff <= issue < end:
        raise ValueError(f"issue date {issue} outside [{cutoff}, {end}): ingest a new quarter?")
    data = bt.prepare(ext, cfg)
    w = apply_frozen(data, cutoff, profiles)
    train = w.filter((pl.col("date") < cutoff) & pl.col("exclude").is_null())
    fut = w.filter(pl.col("date").is_between(issue, end, closed="left"))
    model = gbm.fit(train, cfg.gbm)
    h = ((pl.col("date") - pl.lit(issue)).dt.total_days() + 1).cast(pl.Int32)
    return (
        fut.select(
            "station_id",
            "date",
            pl.col("day_type"),
            pl.col("station_type").fill_null("none"),
            "weather_source",
        )
        .with_columns(
            pl.Series("lgbm", gbm.predict(model, fut, cfg.gbm)),
            h.alias("horizon"),
            ((pl.col("date") - pl.lit(cutoff)).dt.total_days() + 1)
            .cast(pl.Int32)
            .alias("days_since_data"),
        )
        .with_columns(
            horizon_bucket(pl.col("horizon").clip(upper_bound=60)).alias("horizon_bucket")
        )
        .sort("station_id", "date")
    )


def run_lgbm(
    paths: Paths,
    fcfg: ForecastConfig,
    cfg: bt.BacktestConfig,
    issue: date | None = None,
    log: Callable[[str], None] = print,
) -> Path:
    ext, c, end = extended(paths, fcfg)
    issue = issue or date.today()
    profiles = pl.read_parquet(paths.processed / "station_profiles.parquet")
    fc = lgbm_forecast(ext, profiles, c, issue, end, cfg)
    d = forecast_dir(paths, c)
    d.mkdir(parents=True, exist_ok=True)
    fc.write_parquet(d / "lgbm.parquet")
    meta = {
        "cutoff": c.isoformat(),
        "data_end": (c - timedelta(days=1)).isoformat(),
        "issue_date": issue.isoformat(),
        "end": (end - timedelta(days=1)).isoformat(),
        "days_max": fcfg.days_max,
        "lgbm_config_sha256": hashlib.sha256(bt.config_fingerprint(cfg).encode()).hexdigest()[:16],
        "n_stations": fc["station_id"].n_unique(),
        "weather": fc.group_by("weather_source")
        .agg(pl.col("date").min().cast(pl.String).alias("from"))
        .sort("from")
        .rows(),
    }
    (d / "lgbm_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    log(
        f"lgbm forecast: {fc['station_id'].n_unique()} stations, {issue} .. {meta['end']} "
        f"(data to {meta['data_end']}) -> {d / 'lgbm.parquet'}"
    )
    return d


# --- combine ------------------------------------------------------------------------


def calibration_log(
    paths: Paths, fcfg: ForecastConfig, with_deep: bool
) -> tuple[pl.DataFrame, pl.DataFrame | None]:
    """(lgbm log, ensemble log or None) of the production-like backtest variant: every
    origin's out-of-sample forecasts (warm-up + scored), point columns `lgbm` / `ens`."""
    from idf_crowding.models import deep

    vcfg = replace(
        bt.BacktestConfig.from_config(),
        lag_days=fcfg.calib_lag,
        weather_mode="production",
        quantile_models=False,
    )
    last = (
        pl.scan_parquet(paths.processed / "features_daily.parquet")
        .select(pl.col("date").max())
        .collect()
        .item()
    )
    warm, scored = bt.all_origins(last, vcfg)
    origins = warm + scored
    bp = paths.backtest
    for o in origins:
        if not (bt.origin_dir(bp, o, vcfg) / "predictions.parquet").exists():
            raise FileNotFoundError(
                f"backtest variant {vcfg.variant} origin {o} missing: "
                f"idf-backtest origin ... --lag {fcfg.calib_lag} --weather production "
                "--no-quantile-models"
            )
    lg = pl.concat(
        [pl.read_parquet(bt.origin_dir(bp, o, vcfg) / "predictions.parquet") for o in origins],
        how="diagonal",
    )
    if not with_deep:
        return lg, None
    fc = deep.load_forecasts(paths.processed.parent / fcfg.calib_deep_dir)
    seeds = deep.seed_models(sorted(fc["model"].unique()))
    fc = deep.seed_average(fc, seeds)
    return lg, deep.ensemble_log(bp, fc, origins, "tft_seedavg", vcfg)


def band(rows: pl.DataFrame, log: pl.DataFrame, point: str, cutoff: date) -> pl.DataFrame:
    """lo / hi (80 %) around `point` for `rows`, from log residuals dated in
    [cutoff - 365 d, cutoff)."""
    cal = intervals.with_scores(log, point).filter(
        pl.col("scored")
        & pl.col("date").is_between(cutoff - timedelta(days=365), cutoff, closed="left")
    )
    q = intervals.lookup(rows, cal, "r", [intervals.LO, intervals.HI])
    lp = np.log1p(rows[point].to_numpy())
    lo = np.expm1(lp + q[f"q{intervals.LO}"].to_numpy().astype(float))
    hi = np.expm1(lp + q[f"q{intervals.HI}"].to_numpy().astype(float))
    return rows.with_columns(
        pl.Series("lo", np.clip(lo, 0, None)),
        pl.Series("hi", hi),
        pl.lit(cal.height).alias("n_cal"),
    )


def combine_frames(
    lg: pl.DataFrame,
    tft: pl.DataFrame | None,
    lgbm_log: pl.DataFrame,
    ens_log: pl.DataFrame | None,
    cutoff: date,
    special: bool = True,
    first_seen: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Point + band per station-date. `tft` = station_id, date, tft (mean of seeds);
    rows without it use lgbm alone and lgbm's band. Special days (special_days.py) use
    lgbm x its special-day factor (point and band), from log outcomes dated before the
    cutoff: the ensemble's factor was not stable across years (TFT's error halved)."""
    rows = lg
    if tft is not None:
        rows = rows.join(tft, on=["station_id", "date"], how="left")
    else:
        rows = rows.with_columns(pl.lit(None, pl.Float64).alias("tft"))
    has = pl.col("tft").is_not_null()
    if special:
        has = has & sd.special_day().is_null()
    ens_rows = rows.filter(has).with_columns(((pl.col("lgbm") + pl.col("tft")) / 2).alias("ens"))
    parts = []
    if ens_rows.height and ens_log is not None:
        parts.append(
            band(ens_rows, ens_log, "ens", cutoff).with_columns(
                pl.col("ens").alias("point"), pl.lit("lgbm+tft").alias("model")
            )
        )
    lg_rows = rows.filter(~has) if ens_log is not None else rows
    if lg_rows.height:
        parts.append(
            band(lg_rows, lgbm_log, "lgbm", cutoff).with_columns(
                pl.col("lgbm").alias("point"), pl.lit("lgbm").alias("model")
            )
        )
    out = pl.concat(parts, how="diagonal")
    if special:
        f = sd.factors(lgbm_log, "lgbm", cutoff, first_seen=first_seen)
        lgbm_part = pl.col("model") == "lgbm"
        out = pl.concat(
            [
                sd.apply(out.filter(lgbm_part), f),
                sd.apply(out.filter(~lgbm_part), f.clear()),
            ],
            how="diagonal",
        )
    else:
        out = out.with_columns(sd.special_day().alias("special_day"), pl.lit(1.0).alias("adjust"))
    return out.select(
        "station_id",
        "date",
        "point",
        "lo",
        "hi",
        "model",
        "lgbm",
        "tft",
        "horizon",
        "days_since_data",
        "day_type",
        "station_type",
        "weather_source",
        "n_cal",
        "special_day",
        "adjust",
    ).sort("station_id", "date")


def run_combine(
    paths: Paths,
    fcfg: ForecastConfig,
    deep_dir: Path | None = None,
    issue: date | None = None,
    log: Callable[[str], None] = print,
) -> Path:
    from idf_crowding.models import deep

    c = cutoff_of(pl.scan_parquet(paths.processed / "features_daily.parquet"))
    d = forecast_dir(paths, c)
    if not (d / "lgbm.parquet").exists():
        raise FileNotFoundError(f"run `idf-forecast lgbm` first ({d})")
    lg = pl.read_parquet(d / "lgbm.parquet")
    meta = json.loads((d / "lgbm_meta.json").read_text(encoding="utf-8"))
    if issue:
        lg = lg.filter(pl.col("date") >= issue).with_columns(
            ((pl.col("date") - pl.lit(issue)).dt.total_days() + 1).cast(pl.Int32).alias("horizon")
        )
        lg = lg.with_columns(
            horizon_bucket(pl.col("horizon").clip(upper_bound=60)).alias("horizon_bucket")
        )
        meta["issue_date"] = issue.isoformat()
    tft, seeds = None, []
    if deep_dir is not None:
        fc = deep.load_forecasts(deep_dir).filter(pl.col("origin") == c)
        if fc.height == 0:
            raise ValueError(f"no TFT forecasts for cutoff {c} in {deep_dir}")
        seeds = deep.seed_models(sorted(fc["model"].unique()))
        tft = deep.seed_average(fc, seeds).select("station_id", "date", pl.col("q50").alias("tft"))
    lgbm_log, ens_log = calibration_log(paths, fcfg, tft is not None)
    first_seen = (
        pl.scan_parquet(paths.processed / "features_daily.parquet")
        .group_by("station_id")
        .agg(pl.col("date").min().alias("first_date"))
        .collect()
    )
    out = combine_frames(lg, tft, lgbm_log, ens_log, c, first_seen=first_seen)
    out = out.with_columns(
        pl.lit(date.fromisoformat(meta["issue_date"])).alias("issue_date"),
        pl.lit(c - timedelta(days=1)).alias("data_end"),
    )
    out.write_parquet(d / "forecast.parquet")
    meta.update(
        {
            "tft_seeds": seeds,
            "models": out.group_by("model").len().sort("model").rows(),
            "calibration": f"backtest variant lag{fcfg.calib_lag}_prod, residuals dated in the "
            "365 days before the cutoff",
        }
    )
    (d / "forecast_meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    log(
        f"forecast: {out.height:,} station-days ({dict(meta['models'])}) "
        f"-> {d / 'forecast.parquet'}"
    )
    return d


def status(paths: Paths, log: Callable[[str], None] = print) -> dict:
    c = cutoff_of(pl.scan_parquet(paths.processed / "features_daily.parquet"))
    d = forecast_dir(paths, c)
    s = {
        "cutoff": c.isoformat(),
        "lgbm": (d / "lgbm.parquet").exists(),
        "forecast": (d / "forecast.parquet").exists(),
    }
    log(json.dumps(s))
    return s


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="idf-forecast", description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["lgbm", "combine", "status"])
    parser.add_argument("--issue", help="issue date YYYY-MM-DD (default: today)")
    parser.add_argument("--deep", type=Path, help="combine: folder with the TFT outputs")
    a = parser.parse_args(argv)
    paths, fcfg = Paths.from_config(), ForecastConfig.from_config()
    issue = date.fromisoformat(a.issue) if a.issue else None
    if a.command == "lgbm":
        run_lgbm(paths, fcfg, bt.BacktestConfig.from_config(), issue)
    elif a.command == "combine":
        run_combine(paths, fcfg, a.deep, issue)
    else:
        status(paths)
    return 0


if __name__ == "__main__":
    sys.exit(main())
