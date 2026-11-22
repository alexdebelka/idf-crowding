"""P(busy day) on the production-like forecast log.

    idf-busy run [--lag 120] [--weather production] [--context horizon_bucket,...]
    idf-busy report                     rewrite report.md from the saved tables

Busy day = a station's daily entries above a threshold known at the data cutoff c
(intervals.busy_threshold):
  yearly    p90 of the station's clean days of the same day group in [c - 365 d, c)
  seasonal  p90 of the station's clean days of the same day group within ± 45 days of the
            target's day of year, all years before c (yearly p90 below 20 such days); every
            reference day brought to the target date's level with the LightGBM growth
            factor of c (growth.py); within the window, values are taken relative to the
            local level (median of ± 10 days of year), so the window's own seasonal slope
            does not leak into the threshold

P(busy) = 1 - CDF of the conformal log residuals at log1p(threshold) - log1p(point)
(intervals.conformalize), then recalibrated on earlier origins only:
  isotonic  isotonic regression on p (intervals.recalibrate_busy)
  logistic  logistic regression on logit(p) + horizon bucket (+ context columns)

Log: the backtest variant (default lag 120, production weather; warm-up + scored origins),
LightGBM growth-corrected as in production (forecast.calibration_log), and the ensemble
mean(lgbm, mean of TFT seeds) on rows with a TFT forecast.
Writes data/processed/backtest/variants/<variant>/busy/: report.md, scores.parquet,
reliability.parquet, monthly.parquet, p_busy.parquet (scored origins).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import replace
from datetime import date

import numpy as np
import polars as pl

from idf_crowding.models import backtest as bt
from idf_crowding.models import growth, intervals

KEYS = ["origin", "station_id", "date"]
METHODS = ["yearly", "seasonal"]
RECAL = ["raw", "isotonic", "logistic"]
TABLES = ["scores", "reliability", "monthly"]
MIN_BIN = 500  # reliability bins with fewer rows are not judged
TOLERANCE = 0.03  # acceptance: |observed - mean p| per judged bin


def clean_history(features: pl.DataFrame, cfg: bt.BacktestConfig) -> pl.DataFrame:
    """Clean station-days (backtest `exclude` rules) from train_start: the reference days of
    the thresholds, as in run_origin's training rows."""
    return (
        bt.prepare(features, cfg)
        .filter(pl.col("exclude").is_null())
        .select("station_id", "date", "day_type", "n_entries")
    )


def log_thresholds(
    log: pl.DataFrame,
    history: pl.DataFrame,
    features: pl.DataFrame | pl.LazyFrame,
    method: str,
    growth_window: int = growth.WINDOW_DAYS,
) -> pl.DataFrame:
    """`log` with `busy_threshold` recomputed by `method`, each origin from history dated
    before its own cutoff (and growth rates of that cutoff for "seasonal")."""
    parts = []
    for (c,), part in log.group_by("cutoff", maintain_order=True):
        hist = history.filter(pl.col("date") < c)
        rates = growth.growth_rates(features, c, growth_window) if method == "seasonal" else None
        thr = intervals.busy_threshold(hist, part, c, method=method, rates=rates)
        parts.append(part.with_columns(thr.alias("busy_threshold")))
    return pl.concat(parts, how="diagonal")


def busy_probs(
    log: pl.DataFrame,
    warm: list[date],
    scored: list[date],
    point: str,
    context: tuple[str, ...] = ("horizon_bucket",),
) -> pl.DataFrame:
    """KEYS + p_raw / p_isotonic / p_logistic for the rows of the scored origins."""
    every = warm + scored
    b = intervals.conformalize(log, every, point, f"{point}_q10", f"{point}_q90")
    with_p = log.join(b.select(*KEYS, "p_busy"), on=KEYS)
    iso = intervals.recalibrate_busy(with_p, scored)
    lgt = intervals.recalibrate_busy_logistic(with_p, scored, context=context)
    return (
        with_p.filter(pl.col("origin").is_in(scored))
        .select(*KEYS, pl.col("p_busy").alias("p_raw"))
        .join(iso.rename({"p_busy_iso": "p_isotonic"}), on=KEYS, how="left")
        .join(lgt.rename({"p_busy_logit": "p_logistic"}), on=KEYS, how="left")
    )


def evaluate(rows: pl.DataFrame, label: dict) -> dict[str, pl.DataFrame]:
    """Scores, reliability (overall and per season) and observed busy rate per month for
    rows with `y`, `busy_threshold`, `date` and p_raw / p_isotonic / p_logistic."""
    scores, rel = [], []
    for r in RECAL:
        d = rows.with_columns(pl.col(f"p_{r}").alias("p_busy"))
        s = intervals.busy_scores(d)
        parts = [intervals.reliability(d).with_columns(pl.lit("all").alias("season"))]
        for (sn,), g in d.with_columns(intervals.season().alias("_s")).group_by(
            "_s", maintain_order=True
        ):
            parts.append(intervals.reliability(g).with_columns(pl.lit(sn).alias("season")))
        t = pl.concat(parts).with_columns(
            (pl.col("observed") - pl.col("mean_p")).alias("gap"), pl.lit(r).alias("recal")
        )
        judged = t.filter(pl.col("n") >= MIN_BIN)
        scores.append(
            {
                **label,
                "recal": r,
                **s,
                "max_gap_all": float(
                    judged.filter(pl.col("season") == "all")["gap"].abs().max() or np.nan
                ),
                "max_gap_season": float(judged["gap"].abs().max() or np.nan),
            }
        )
        rel.append(t.with_columns(*[pl.lit(v).alias(k) for k, v in label.items()]))
    monthly = (
        rows.filter(pl.col("busy_threshold").is_not_null())
        .group_by(pl.col("date").dt.month().alias("month"))
        .agg(
            pl.len().alias("n"),
            (pl.col("y") > pl.col("busy_threshold")).mean().alias("observed"),
            *[pl.col(f"p_{r}").mean().alias(f"mean_p_{r}") for r in RECAL],
        )
        .sort("month")
        .with_columns(*[pl.lit(v).alias(k) for k, v in label.items()])
    )
    return {
        "scores": pl.DataFrame(scores),
        "reliability": pl.concat(rel),
        "monthly": monthly,
    }


def _logs(cfg: bt.BacktestConfig) -> tuple[pl.DataFrame, pl.DataFrame | None]:
    from idf_crowding.models import forecast as fc

    fcfg = replace(fc.ForecastConfig.from_config(), calib_lag=cfg.lag_days)
    return fc.calibration_log(fc.Paths.from_config(), fcfg, with_deep=True)


def run(
    cfg: bt.BacktestConfig,
    context: tuple[str, ...] = ("horizon_bucket",),
    log: Callable[[str], None] = print,
) -> dict[str, pl.DataFrame]:
    paths = bt.Paths.from_config()
    feats = pl.read_parquet(paths.processed / "features_daily.parquet")
    last = feats.select(pl.col("date").max()).item()
    warm, scored = bt.all_origins(last, cfg)
    history = clean_history(feats, cfg)
    lg, ens = _logs(cfg)
    logs = {"lgbm": lg} if ens is None else {"lgbm": lg, "ens": ens}
    out: dict[str, list[pl.DataFrame]] = {"scores": [], "reliability": [], "monthly": []}
    keep = []
    for method in METHODS:
        # thresholds depend on the station, date and cutoff only: compute them on the lgbm
        # log (a superset of the ensemble's rows) once
        thr = log_thresholds(lg, history, feats, method).select(*KEYS, "busy_threshold")
        for name, lgx in logs.items():
            t = lgx.drop("busy_threshold").join(thr, on=KEYS, how="left")
            p = busy_probs(t, warm, scored, name, context)
            rows = t.filter(pl.col("origin").is_in(scored) & pl.col("scored")).join(p, on=KEYS)
            ev = evaluate(rows, {"model": name, "threshold": method})
            for k, v in ev.items():
                out[k].append(v)
            keep.append(
                rows.select(*KEYS, "y", "busy_threshold", *[f"p_{r}" for r in RECAL]).with_columns(
                    pl.lit(name).alias("model"), pl.lit(method).alias("threshold")
                )
            )
            log(f"busy: {name} / {method}: {rows.height:,} scored rows")
    tables = {k: pl.concat(v, how="diagonal") for k, v in out.items()}
    target = bt.backtest_dir(paths, cfg) / "busy"
    target.mkdir(parents=True, exist_ok=True)
    for k, v in tables.items():
        v.write_parquet(target / f"{k}.parquet")
    pl.concat(keep).write_parquet(target / "p_busy.parquet")
    (target / "report.md").write_text(report(tables, cfg, context), encoding="utf-8")
    log(f"busy: report -> {target / 'report.md'}")
    return tables


def accepted(scores: pl.DataFrame, min_skill: dict[str, float]) -> pl.DataFrame:
    """Acceptance per model x threshold x recalibration: every judged reliability bin
    (overall and per season) within TOLERANCE, Brier skill >= min_skill[model]."""
    return scores.with_columns(
        (
            (pl.col("max_gap_season") <= TOLERANCE)
            & (pl.col("skill") >= pl.col("model").replace_strict(min_skill, default=1.0))
        ).alias("accepted")
    )


MIN_SKILL = {"lgbm": 0.23, "ens": 0.30}  # skill before this work (main log, lag 0)


def report(tables: dict[str, pl.DataFrame], cfg: bt.BacktestConfig, context) -> str:
    sc = accepted(tables["scores"], MIN_SKILL)
    rel = (
        tables["reliability"]
        .filter(pl.col("season") == "all")
        .with_columns(pl.concat_str("model", "threshold", "recal", separator=" ").alias("col"))
    )
    rel_w = rel.pivot(on="col", index="p_from", values="gap").sort("p_from")
    rel_n = (
        rel.filter(pl.col("recal") == "raw")
        .with_columns(pl.concat_str("model", "threshold", separator=" ").alias("col"))
        .pivot(on="col", index="p_from", values="n")
        .sort("p_from")
    )
    seas = (
        tables["reliability"]
        .filter((pl.col("season") != "all") & (pl.col("n") >= MIN_BIN))
        .group_by("model", "threshold", "recal", "season")
        .agg(pl.col("gap").abs().max().alias("max_gap"), pl.col("n").sum())
        .pivot(on="season", index=["model", "threshold", "recal"], values="max_gap")
        .sort("model", "threshold", "recal")
    )
    mon = (
        tables["monthly"]
        .filter(pl.col("model") == "lgbm")
        .pivot(on="threshold", index="month", values="observed")
        .sort("month")
    )
    return "\n".join(
        [
            f"# P(busy day) on the {cfg.variant or 'main'} forecast log",
            "",
            "Rows: scored origins, clean station-days; LightGBM growth-corrected as in "
            "production; `ens` = mean(lgbm, mean of TFT seeds) on rows with a TFT forecast. "
            "Thresholds: `yearly` = station p90 of the same day group over the 365 days before "
            "the cutoff; `seasonal` = ± 45 days of the date's day of year, all years before the "
            "cutoff, grown to the date's level (growth.py). Recalibration fitted per origin on "
            f"earlier origins only: isotonic on p; logistic on logit(p) + {' + '.join(context)}. "
            f"Acceptance: every reliability bin with n ≥ {MIN_BIN} within ± {TOLERANCE:.0%} "
            "overall and per season, Brier skill vs 'always 10 %' ≥ 0.23 (lgbm) / 0.30 (ens).",
            "",
            "## Scores",
            bt._md(
                sc.select(
                    "model",
                    "threshold",
                    "recal",
                    "n",
                    "observed_rate",
                    "mean_p",
                    "brier",
                    "brier_always_0.1",
                    "skill",
                    "max_gap_all",
                    "max_gap_season",
                    "accepted",
                )
            ),
            "",
            "## Observed busy rate per calendar month (lgbm rows; target 8–12 %)",
            bt._md(mon),
            "",
            "## Reliability gap (observed − mean p) per bin, all seasons",
            bt._md(rel_w),
            "",
            "Rows per bin (raw p):",
            bt._md(rel_n),
            "",
            f"## Largest |gap| per season (bins with n ≥ {MIN_BIN})",
            bt._md(seas),
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="idf-busy", description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["run", "report"])
    parser.add_argument("--lag", type=int, default=120, help="backtest variant: lag in days")
    parser.add_argument("--weather", choices=list(bt.WEATHER_MODES), default="production")
    parser.add_argument(
        "--context",
        default="horizon_bucket",
        help="logistic context columns, comma-separated (horizon_bucket, season, day_group)",
    )
    a = parser.parse_args(argv)
    cfg = replace(
        bt.BacktestConfig.from_config(),
        lag_days=a.lag,
        weather_mode=a.weather,
        quantile_models=False,
    )
    ctx = tuple(c for c in a.context.split(",") if c)
    if a.command == "report":  # rewrite report.md from the saved tables
        target = bt.backtest_dir(bt.Paths.from_config(), cfg) / "busy"
        tables = {k: pl.read_parquet(target / f"{k}.parquet") for k in TABLES}
        (target / "report.md").write_text(report(tables, cfg, ctx), encoding="utf-8")
    else:
        run(cfg, ctx)
    return 0


if __name__ == "__main__":
    sys.exit(main())
