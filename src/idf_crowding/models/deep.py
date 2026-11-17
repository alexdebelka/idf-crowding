"""Option C: inputs for deep global models trained elsewhere (e.g. a Colab GPU), and the
scoring of their forecasts on the backtest harness.

    idf-deep export [--out DIR] [--warmup]
                                    one input file per scored origin (+ static, meta.json);
                                    --warmup also exports the warm-up origins (forecast log
                                    for calibrated intervals of the ensemble)
    idf-deep score  [--dir DIR]     score deep forecasts against lgbm on the same rows;
                                    seed average when several TFT seeds exist; calibrated
                                    80 % band and P(busy) for mean(lgbm, tft) when TFT has
                                    the warm-up origins

The leakage rules live here, not in the notebook that trains the models:
- per origin, history = station-days from `train_start` to the day before the origin on a
  complete daily grid; `available_mask` = 0 for any non-clean day (missing, closure,
  network disruption, flags) and for grid days with no row. Masked targets are filled
  by interpolation (log scale) only so input windows are complete; they never count
  in a loss or a score;
- future rows = origin .. origin + horizon - 1, exogenous only, with `short_pass_share`
  frozen at the origin; static features (station type, morning share, size) are
  computed from data before the origin (models/frozen.py);
- weather is the observed weather (same caveat as LightGBM), standardised with
  statistics from before the origin;
- stations with fewer than `min_history` days of clean history before the origin are
  left out (cold start: scored with LightGBM only, counted in the report).
Target y = log1p(entries); forecasts are returned as entries (expm1 of the quantiles).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from idf_crowding.models import backtest as bt
from idf_crowding.models import intervals
from idf_crowding.models.frozen import apply_frozen
from idf_crowding.models.gbm import DAY_TYPES, STATION_TYPES, WEATHER
from idf_crowding.models.metrics import summarize

WEEKDAYS = [f"wd_{i}" for i in range(1, 8)]
DAY_TYPE_COLS = [f"dt_{d}" for d in DAY_TYPES]
FUTR = [
    *WEEKDAYS,
    "doy_sin",
    "doy_cos",
    "is_public_holiday",
    "is_bridge",
    "is_school_holiday",
    *DAY_TYPE_COLS,
    "short_pass_share",
    *WEATHER,
]
STATIC = [*[f"st_{s}" for s in STATION_TYPES], "am_share_7_10", "log_size"]


@dataclass(frozen=True)
class DeepConfig:
    min_history: int = 365
    active_days: int = 28  # a station must have a clean day in the last `active_days`


def _exog(df: pl.DataFrame) -> list[pl.Expr]:
    doy = 2 * np.pi * pl.col("day_of_year").cast(pl.Float64) / 365.25
    return [
        *[(pl.col("weekday") == i).cast(pl.Float32).alias(f"wd_{i}") for i in range(1, 8)],
        doy.sin().cast(pl.Float32).alias("doy_sin"),
        doy.cos().cast(pl.Float32).alias("doy_cos"),
        *[
            pl.col(c).fill_null(False).cast(pl.Float32).alias(c)
            for c in ["is_public_holiday", "is_bridge", "is_school_holiday"]
        ],
        *[
            (pl.col("day_type") == d).fill_null(False).cast(pl.Float32).alias(f"dt_{d}")
            for d in DAY_TYPES
        ],
        pl.col("short_pass_share").cast(pl.Float32),
    ]


def origin_inputs(
    data: pl.DataFrame,
    profiles: pl.DataFrame,
    origin: date,
    cfg: bt.BacktestConfig,
    dcfg: DeepConfig | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame, dict]:
    """(temporal frame, static frame, info) for one origin. `data` = bt.prepare output."""
    dcfg = dcfg or DeepConfig()
    end = origin + timedelta(days=cfg.horizon)
    w = apply_frozen(data.filter(pl.col("date") < end), origin, profiles)
    past = w.filter(pl.col("date") < origin)
    clean = past.filter(pl.col("exclude").is_null())

    # stations: enough clean history and active just before the origin
    hist_n = clean.group_by("station_id").agg(
        pl.len().alias("n_clean"),
        (pl.col("date") >= origin - timedelta(days=dcfg.active_days)).any().alias("active"),
        pl.col("date").min().alias("first"),
    )
    keep = hist_n.filter((pl.col("n_clean") >= dcfg.min_history) & pl.col("active"))
    ids = keep["station_id"]

    # complete daily grid per station: first clean day .. origin + horizon - 1
    days = pl.DataFrame(
        {"date": pl.date_range(cfg.train_start, end - timedelta(days=1), "1d", eager=True)}
    )
    grid = (
        keep.select("station_id", "first")
        .join(days, how="cross")
        .filter(pl.col("date") >= pl.col("first"))
    )
    cal = w.group_by("date").agg(
        pl.col(c).first()
        for c in [
            "weekday",
            "day_of_year",
            "is_public_holiday",
            "is_bridge",
            "is_school_holiday",
            "day_type",
            "short_pass_share",
            *WEATHER,
        ]
    )
    rows = w.filter(pl.col("station_id").is_in(ids.implode())).select(
        "station_id", "date", "n_entries", "exclude"
    )
    t = (
        grid.join(rows, on=["station_id", "date"], how="left")
        .join(cal, on="date", how="left")
        .sort("station_id", "date")
    )
    is_future = pl.col("date") >= origin
    ok = (~is_future) & pl.col("exclude").is_null() & pl.col("n_entries").is_not_null()
    wstats = past.group_by("date").agg(pl.col(c).first() for c in WEATHER)
    mu = {c: wstats[c].mean() for c in WEATHER}
    sd = {c: (wstats[c].std() or 1.0) for c in WEATHER}
    t = t.with_columns(
        pl.when(ok).then(pl.col("n_entries").cast(pl.Float64).log1p()).alias("y_obs"),
        ok.cast(pl.Float32).alias("available_mask"),
        is_future.alias("is_future"),
    ).with_columns(
        pl.col("y_obs")
        .interpolate()
        .forward_fill()
        .backward_fill()
        .over("station_id")
        .alias("y_fill"),
    )
    temporal = t.select(
        pl.col("station_id").cast(pl.String).alias("unique_id"),
        pl.col("date").alias("ds"),
        pl.when(is_future).then(None).otherwise(pl.col("y_fill")).cast(pl.Float32).alias("y"),
        "available_mask",
        "is_future",
        *_exog(t),
        *[((pl.col(c) - mu[c]) / sd[c]).fill_null(0).cast(pl.Float32).alias(c) for c in WEATHER],
    )

    size = (
        clean.filter(pl.col("date") >= origin - timedelta(days=365))
        .group_by("station_id")
        .agg(pl.col("n_entries").mean().log1p().alias("log_size"))
    )
    st = (
        w.select("station_id", "station_type", "am_share_7_10")
        .unique("station_id")
        .join(size, on="station_id", how="left")
        .filter(pl.col("station_id").is_in(ids.implode()))
    )
    static = st.select(
        pl.col("station_id").cast(pl.String).alias("unique_id"),
        *[
            (pl.col("station_type") == s).fill_null(False).cast(pl.Float32).alias(f"st_{s}")
            for s in STATION_TYPES
        ],
        pl.col("am_share_7_10").fill_null(pl.col("am_share_7_10").mean()).cast(pl.Float32),
        pl.col("log_size").fill_null(pl.col("log_size").mean()).cast(pl.Float32),
    ).sort("unique_id")

    left_out = past["station_id"].n_unique() - len(ids)
    info = {
        "origin": origin.isoformat(),
        "n_series": len(ids),
        "n_left_out": int(left_out),
        "n_rows": temporal.height,
        "masked_share": float(1 - temporal.filter(~pl.col("is_future"))["available_mask"].mean()),
    }
    return temporal, static, info


def export_plan(last_date: date, cfg: bt.BacktestConfig, warmup: bool) -> list[tuple[date, str]]:
    """(origin, role) to export, in date order; role is "warmup" or "scored"."""
    warm, scored = bt.all_origins(last_date, cfg)
    return [(o, "warmup") for o in (warm if warmup else [])] + [(o, "scored") for o in scored]


def export(
    paths: bt.Paths, cfg: bt.BacktestConfig, out: Path, warmup: bool = False, log=print
) -> list[dict]:
    data, profiles = bt.load_data(paths, cfg)
    (out / "inputs").mkdir(parents=True, exist_ok=True)
    infos = []
    for o, role in export_plan(data["date"].max(), cfg, warmup):
        temporal, static, info = origin_inputs(data, profiles, o, cfg)
        info["role"] = role
        temporal.write_parquet(out / "inputs" / f"{o}.parquet", compression="zstd")
        static.write_parquet(out / "inputs" / f"{o}_static.parquet")
        infos.append(info)
        log(f"export {o} ({role}): {info['n_series']} series, {info['n_rows']:,} rows")
    meta = {
        "horizon": cfg.horizon,
        "freq": "D",
        "target": "log1p(entries)",
        "futr_exog": FUTR,
        "stat_exog": STATIC,
        "quantiles": [0.1, 0.5, 0.9],
        "origins": infos,
    }
    (out / "inputs" / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return infos


# --- scoring ---------------------------------------------------------------------------


def load_forecasts(folder: Path) -> pl.DataFrame:
    """Colab outputs: one parquet per model x origin with station_id, date, origin, model,
    q10, q50, q90 (entries)."""
    files = sorted(folder.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no forecast files in {folder}")
    return pl.concat([pl.read_parquet(f) for f in files], how="diagonal").with_columns(
        pl.col("station_id").cast(pl.Int64),
        pl.col("date").cast(pl.Date),
        pl.col("origin").cast(pl.Date),
    )


def seed_models(models: list[str], base: str = "tft") -> list[str]:
    """`base` (seed 1) and its other seeds `base_s2`, `base_s3`, ..."""
    return sorted(m for m in models if re.fullmatch(rf"{base}(_s\d+)?", m))


def ensemble_log(
    paths: bt.Paths, fc: pl.DataFrame, origins: list[date], deep: str = "tft"
) -> pl.DataFrame:
    """Forecast log for the ensemble: LightGBM backtest rows of `origins` (warm-up and
    scored) that also have a `deep` forecast; ens = mean(lgbm, deep)."""
    lg = pl.concat(
        [pl.read_parquet(bt.origin_dir(paths, o) / "predictions.parquet") for o in origins],
        how="diagonal",
    )
    d = fc.filter(pl.col("model") == deep).select(
        "origin",
        "station_id",
        "date",
        pl.col("q10").cast(pl.Float64).alias(f"{deep}_q10"),
        pl.col("q50").cast(pl.Float64).alias(deep),
        pl.col("q90").cast(pl.Float64).alias(f"{deep}_q90"),
    )
    return lg.join(d, on=["origin", "station_id", "date"], how="inner").with_columns(
        ((pl.col("lgbm") + pl.col(deep)) / 2).alias("ens")
    )


BAND_DIMS = [[], ["horizon_bucket"], ["day_type"], ["station_type"]]


def calibrate(
    log: pl.DataFrame, warm: list[date], scored: list[date], deep: str = "tft"
) -> tuple[pl.DataFrame, dict[str, pl.DataFrame]]:
    """Bands and P(busy) for lgbm and the ensemble, both calibrated on the same forecast
    log (rows with a deep forecast), so the comparison is like for like."""
    every = warm + scored
    out = log.select("origin", "station_id", "date")
    for name, point, q10, q90 in [
        ("lgbm", "lgbm", "lgbm_q10", "lgbm_q90"),
        ("ens", "ens", f"{deep}_q10", f"{deep}_q90"),
    ]:
        b = intervals.conformalize(log, every, point, q10, q90)
        b = b.rename(
            {c: f"{name}_{c}" for c in b.columns if c not in ("origin", "station_id", "date")}
        )
        out = out.join(b, on=["origin", "station_id", "date"], how="left")
        with_p = log.join(b, on=["origin", "station_id", "date"]).with_columns(
            pl.col(f"{name}_p_busy").alias("p_busy")
        )
        iso = intervals.recalibrate_busy(with_p, scored).rename(
            {"p_busy_iso": f"{name}_p_busy_iso"}
        )
        out = out.join(iso, on=["origin", "station_id", "date"], how="left")
    rows = log.join(out, on=["origin", "station_id", "date"]).filter(
        pl.col("origin").is_in(scored) & pl.col("scored")
    )
    methods = [
        ("lgbm conformal", "lgbm_conf_lo", "lgbm_conf_hi"),
        ("lgbm cqr", "lgbm_cqr_lo", "lgbm_cqr_hi"),
        (f"{deep} raw quantiles", f"{deep}_q10", f"{deep}_q90"),
        ("ens conformal", "ens_conf_lo", "ens_conf_hi"),
        (f"ens cqr ({deep} band)", "ens_cqr_lo", "ens_cqr_hi"),
    ]
    parts = []
    for by in BAND_DIMS:
        for m, lo, hi in methods:
            g = rows.group_by(by) if by else rows.group_by(pl.lit("all").alias("group"))
            t = g.agg(intervals.interval_aggs(lo, hi)).with_columns(
                pl.lit(m).alias("method"),
                pl.lit("+".join(by) or "overall").alias("dimension"),
            )
            if by:
                t = t.with_columns(pl.col(by[0]).cast(pl.String).alias("group")).drop(by)
            parts.append(t)
    bands = pl.concat(parts, how="diagonal").select(
        "dimension", "group", "method", "n", "coverage", "rel_width", "interval_score"
    )
    busy_rows, rel = [], {}
    for name in ["lgbm", "ens"]:
        for kind, col in [("raw", f"{name}_p_busy"), ("isotonic", f"{name}_p_busy_iso")]:
            d = rows.with_columns(pl.col(col).alias("p_busy"))
            busy_rows.append({"model": name, "p_busy": kind, **intervals.busy_scores(d)})
            rel[f"{name} {kind}"] = intervals.reliability(d)
    tables = {"bands": bands, "busy": pl.DataFrame(busy_rows)}
    rel_tab = None
    for k, t in rel.items():
        t = t.select("p_from", pl.col("n").alias(f"n ({k})"), pl.col("observed").alias(k))
        rel_tab = t if rel_tab is None else rel_tab.join(t, on="p_from", how="full", coalesce=True)
    tables["reliability"] = rel_tab.sort("p_from")
    return out, tables


def score(
    paths: bt.Paths, folder: Path, cfg: bt.BacktestConfig | None = None, log=print
) -> dict[str, pl.DataFrame]:
    fc = load_forecasts(folder)
    pred = pl.read_parquet(paths.processed / "backtest" / "predictions.parquet").filter(
        pl.col("scored") & pl.col("origin").is_in(fc["origin"].unique().implode())
    )
    deep_models = sorted(fc["model"].unique())
    seeds = seed_models(deep_models)
    wide = fc.pivot(on="model", index=["origin", "station_id", "date"], values="q50")
    bands = fc.select("origin", "station_id", "date", "model", "q10", "q90")
    j = pred.join(wide, on=["origin", "station_id", "date"], how="left")
    have = pl.all_horizontal([pl.col(m).is_not_null() for m in deep_models])
    common = j.filter(have)
    ens = {f"ens_lgbm_{m}": (pl.col("lgbm") + pl.col(m)) / 2 for m in deep_models}
    extra = []
    if len(seeds) > 1:
        common = common.with_columns(pl.mean_horizontal(seeds).alias("tft_seedavg"))
        ens["ens_lgbm_tft_seedavg"] = (pl.col("lgbm") + pl.col("tft_seedavg")) / 2
        extra = ["tft_seedavg"]
    common = common.with_columns(**ens)
    models = ["daytype_12m", "lgbm", *deep_models, *extra, *ens]
    long = bt.to_long(common, models)
    tables = {
        "overall": summarize(long, []),
        "type_x_horizon": summarize(long, ["station_type", "horizon_bucket"]),
        "day_type": summarize(long, ["day_type"]),
        "origin": summarize(long, ["origin"]),
        "network": bt.network_level(long),
    }
    cov = (
        common.select("origin", "station_id", "date", "y")
        .join(bands, on=["origin", "station_id", "date"])
        .group_by("model")
        .agg(
            ((pl.col("y") >= pl.col("q10")) & (pl.col("y") <= pl.col("q90")))
            .mean()
            .alias("coverage_raw"),
            ((pl.col("q90") - pl.col("q10")).sum() / pl.col("y").sum()).alias("rel_width"),
        )
        .sort("model")
    )
    tables["bands"] = cov
    if len(seeds) > 1:
        tables["seeds"] = seed_spread(tables, seeds)
    target = paths.processed / "backtest" / "deep"
    target.mkdir(parents=True, exist_ok=True)
    common.write_parquet(target / "predictions.parquet")
    calib = None
    feats = paths.processed / "features_daily.parquet"
    warm, scored = [], []
    if feats.exists():
        cfg = cfg or bt.BacktestConfig.from_config()
        last = pl.scan_parquet(feats).select(pl.col("date").max()).collect().item()
        warm, scored = bt.all_origins(last, cfg)
    have = set(fc.filter(pl.col("model") == "tft")["origin"].unique().to_list())
    if warm and set(warm + scored) <= have:
        elog = ensemble_log(paths, fc, warm + scored)
        bands_out, calib = calibrate(elog, warm, scored)
        bands_out.filter(pl.col("origin").is_in(scored)).write_parquet(
            target / "ensemble_bands.parquet"
        )
        tables.update({f"calib_{k}": v for k, v in calib.items()})
        log(f"deep score: ensemble bands calibrated on {elog.height:,} forecast-log rows")
    else:
        log("deep score: no calibrated bands (tft has no forecasts for the warm-up origins)")
    n_lgbm_only = pred.height - common.height
    (target / "report.md").write_text(
        _report(tables, models, deep_models, common.height, n_lgbm_only, calib), encoding="utf-8"
    )
    log(f"deep score: {common.height:,} common rows ({n_lgbm_only:,} lgbm only) -> {target}")
    return tables


def seed_spread(tables: dict[str, pl.DataFrame], seeds: list[str]) -> pl.DataFrame:
    """WAPE per seed (alone and in the ensemble), overall and per origin, with the spread."""
    keep = [*seeds, *[f"ens_lgbm_{s}" for s in seeds]]
    o = (
        tables["origin"]
        .filter(pl.col("model").is_in(keep))
        .select(pl.col("origin").cast(pl.String).alias("group"), "model", "wape")
    )
    a = (
        tables["overall"]
        .filter(pl.col("model").is_in(keep))
        .select(pl.lit("overall").alias("group"), "model", "wape")
    )
    w = pl.concat([a, o]).pivot(on="model", index="group", values="wape")
    cols = [c for c in w.columns if c in seeds]
    return w.with_columns(
        (pl.max_horizontal(cols) - pl.min_horizontal(cols)).alias("spread (tft seeds)")
    )


def _report(tables, models, deep_models, n_common, n_lgbm_only, calib=None) -> str:
    md = bt._md
    o = tables["overall"]
    base = o.filter(pl.col("model") == "lgbm")["wape"][0]
    gain = o.select("model", "wape", (1 - pl.col("wape") / base).alias("gain_vs_lgbm")).sort("wape")

    def wide(name, by):
        return (
            tables[name]
            .with_columns(
                pl.concat_str([pl.col(c).cast(pl.String) for c in by], separator=" × ").alias(
                    "group"
                )
            )
            .pivot(on="model", index="group", values="wape")
            .select("group", *models)
            .sort(bt._natural("group"))
        )

    return "\n".join(
        [
            "# Deep models vs LightGBM (option C)",
            "",
            f"Rows: {n_common:,} station-days scored by every model (same clean rows as the "
            f"LightGBM backtest, origins with deep forecasts); {n_lgbm_only:,} scored rows of "
            "those origins have no deep forecast (stations with < 365 days of clean history or "
            "inactive before the origin, or a model missing for that origin).",
            "Deep forecasts = median of the quantile output; ensembles = mean of the point "
            "forecasts. Acceptance: ≥ 3 % WAPE gain vs lgbm.",
            "",
            "## Overall (station level)",
            md(o.select("model", "n", "wape", "mae", "mape")),
            "",
            md(gain),
            "",
            "## Network daily totals",
            md(tables["network"].select("model", "wape")),
            "",
            "## WAPE by station type × horizon bucket",
            md(wide("type_x_horizon", ["station_type", "horizon_bucket"])),
            "",
            "## WAPE by day type",
            md(wide("day_type", ["day_type"])),
            "",
            "## WAPE by origin",
            md(wide("origin", ["origin"])),
            "",
            "## Raw 80 % bands of the deep models (not calibrated)",
            md(tables["bands"]),
            "",
            *_seed_section(tables),
            *_calib_section(calib),
        ]
    )


def _seed_section(tables) -> list[str]:
    if "seeds" not in tables:
        return []
    return [
        "## Seed robustness (TFT)",
        "WAPE per TFT seed, alone and averaged with lgbm; `spread` = max − min over seeds "
        "(acceptance: every seed's ensemble ≥ 3 % better than lgbm, spread < 0.003). "
        "`tft_seedavg` = mean of the seeds' medians.",
        "",
        bt._md(tables["seeds"]),
        "",
    ]


def _calib_section(calib) -> list[str]:
    if calib is None:
        return []
    b = calib["bands"]

    def pick(dim):
        return (
            b.filter(pl.col("dimension") == dim)
            .pivot(on="method", index="group", values="coverage")
            .sort("group")
        )

    return [
        "## Calibrated 80 % bands and P(busy): mean(lgbm, tft) vs lgbm",
        "Both calibrated on the same forecast log (12 warm-up + scored origins, rows with a TFT "
        "forecast; residuals of the 365 days before each origin), scored on the same rows. "
        "`ens conformal` = ensemble point + residual quantiles; `ens cqr` = TFT's own 10/90 band "
        "conformalized. Acceptance: coverage 0.78–0.82 overall and per group, interval score "
        "below lgbm conformal.",
        "",
        bt._md(b.filter(pl.col("dimension") == "overall").drop("dimension", "group")),
        "",
        "### Coverage by horizon bucket",
        bt._md(pick("horizon_bucket")),
        "",
        "### Coverage by day type",
        bt._md(pick("day_type")),
        "",
        "### Coverage by station type",
        bt._md(pick("station_type")),
        "",
        "### P(busy day): raw vs isotonic (fitted on the forecast log before each origin)",
        bt._md(calib["busy"]),
        "",
        "Reliability (observed busy rate per bin of predicted probability):",
        bt._md(calib["reliability"]),
        "",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="idf-deep", description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["export", "score"])
    parser.add_argument("--out", type=Path, help="export folder (default data/deep_colab)")
    parser.add_argument("--warmup", action="store_true", help="export: also the warm-up origins")
    parser.add_argument(
        "--dir", type=Path, help="forecast folder (default data/deep_colab/outputs)"
    )
    a = parser.parse_args(argv)
    paths = bt.Paths.from_config()
    default = paths.processed.parent / "deep_colab"
    cfg = bt.BacktestConfig.from_config()
    if a.command == "export":
        export(paths, cfg, a.out or default, warmup=a.warmup)
    else:
        score(paths, a.dir or default / "outputs", cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
