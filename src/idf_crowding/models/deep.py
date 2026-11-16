"""Option C: inputs for deep global models trained elsewhere (e.g. a Colab GPU), and the
scoring of their forecasts on the backtest harness.

    idf-deep export [--out DIR]     one input file per scored origin (+ static, meta.json)
    idf-deep score  [--dir DIR]     score deep forecasts against lgbm on the same rows

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
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import polars as pl

from idf_crowding.models import backtest as bt
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


def export(paths: bt.Paths, cfg: bt.BacktestConfig, out: Path, log=print) -> list[dict]:
    data, profiles = bt.load_data(paths, cfg)
    _, scored = bt.all_origins(data["date"].max(), cfg)
    (out / "inputs").mkdir(parents=True, exist_ok=True)
    infos = []
    for o in scored:
        temporal, static, info = origin_inputs(data, profiles, o, cfg)
        temporal.write_parquet(out / "inputs" / f"{o}.parquet", compression="zstd")
        static.write_parquet(out / "inputs" / f"{o}_static.parquet")
        infos.append(info)
        log(f"export {o}: {info['n_series']} series, {info['n_rows']:,} rows")
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


def score(paths: bt.Paths, folder: Path, log=print) -> dict[str, pl.DataFrame]:
    fc = load_forecasts(folder)
    pred = pl.read_parquet(paths.processed / "backtest" / "predictions.parquet").filter(
        pl.col("scored") & pl.col("origin").is_in(fc["origin"].unique().implode())
    )
    deep_models = sorted(fc["model"].unique())
    wide = fc.pivot(on="model", index=["origin", "station_id", "date"], values="q50")
    bands = fc.select("origin", "station_id", "date", "model", "q10", "q90")
    j = pred.join(wide, on=["origin", "station_id", "date"], how="left")
    have = pl.all_horizontal([pl.col(m).is_not_null() for m in deep_models])
    common = j.filter(have)
    ens = {f"ens_lgbm_{m}": (pl.col("lgbm") + pl.col(m)) / 2 for m in deep_models}
    if len(deep_models) > 1:
        ens["ens_all"] = (pl.col("lgbm") + sum(pl.col(m) for m in deep_models)) / (
            1 + len(deep_models)
        )
    common = common.with_columns(**ens)
    models = ["daytype_12m", "lgbm", *deep_models, *ens]
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
    target = paths.processed / "backtest" / "deep"
    target.mkdir(parents=True, exist_ok=True)
    common.write_parquet(target / "predictions.parquet")
    n_lgbm_only = pred.height - common.height
    (target / "report.md").write_text(
        _report(tables, models, deep_models, common.height, n_lgbm_only), encoding="utf-8"
    )
    log(f"deep score: {common.height:,} common rows ({n_lgbm_only:,} lgbm only) -> {target}")
    return tables


def _report(tables, models, deep_models, n_common, n_lgbm_only) -> str:
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
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="idf-deep", description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["export", "score"])
    parser.add_argument("--out", type=Path, help="export folder (default data/deep_colab)")
    parser.add_argument(
        "--dir", type=Path, help="forecast folder (default data/deep_colab/outputs)"
    )
    a = parser.parse_args(argv)
    paths = bt.Paths.from_config()
    default = paths.processed.parent / "deep_colab"
    cfg = bt.BacktestConfig.from_config()
    if a.command == "export":
        export(paths, cfg, a.out or default)
    else:
        score(paths, a.dir or default / "outputs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
