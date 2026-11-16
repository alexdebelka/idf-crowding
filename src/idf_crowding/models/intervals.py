"""Option B: 80 % prediction intervals and busy-day probabilities.

Calibration uses a forecast log, as a deployed forecaster would: at origin o, the
calibration set is every earlier forecast (origins before o, `warmup_origins` extra ones
before the first scored origin) for clean station-days dated in [o - 365 days, o). Those
forecasts are out-of-sample and their outcomes are known at o; a full year covers every
season and day type.

Methods (all on log1p entries, 10 % / 90 %):
  quantile   LightGBM quantile objective (raw, not calibrated)
  conformal  point forecast + empirical quantiles of the log residuals
             r = log1p(y) - log1p(pred)
  cqr        conformalized quantile regression: quantile band widened (or narrowed) by
             the 80 % quantile of s = max(log1p(q10) - log1p(y), log1p(y) - log1p(q90))
Residual quantiles are taken per day type x station type x horizon bucket, falling back
to day type x horizon bucket, then horizon bucket, when a group has < MIN_CAL rows.

Busy day: entries above the station's 90th percentile of clean days of the same day
group over the 365 days before the origin. P(busy) = 1 - CDF of the residuals at
log1p(threshold) - log1p(pred) (grid 5 % .. 95 %, linear, tails clamped 2.5 / 97.5 %).
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import polars as pl

from idf_crowding.models.closures import DAY_GROUP

GRID = [round(0.05 * i, 2) for i in range(1, 20)]  # 0.05 .. 0.95
LO, HI = 0.1, 0.9
COV = 0.8  # HI - LO
MIN_CAL = 500
LEVELS = [
    ["day_type", "station_type", "horizon_bucket"],
    ["day_type", "horizon_bucket"],
    ["horizon_bucket"],
]


def conformal_level(n: int, q: float) -> float:
    """Finite-sample split-conformal level (conservative on both tails)."""
    if q >= 0.5:
        return min(1.0, np.ceil((n + 1) * q) / n)
    return max(0.0, np.floor((n + 1) * q) / n)


def score_quantiles(
    cal: pl.DataFrame, score: str, qs: list[float], keys: list[str]
) -> pl.DataFrame:
    """keys x q -> value of the empirical (conformal) quantile of `score`."""
    rows = []
    for k, g in cal.group_by(keys):
        v = g[score].drop_nulls().to_numpy()
        if len(v) < MIN_CAL:
            continue
        row = dict(zip(keys, k, strict=True))
        for q in qs:
            rows.append({**row, "q": q, "v": float(np.quantile(v, conformal_level(len(v), q)))})
    schema = {**{c: cal.schema[c] for c in keys}, "q": pl.Float64, "v": pl.Float64}
    return pl.DataFrame(rows, schema=schema)


def lookup(rows: pl.DataFrame, cal: pl.DataFrame, score: str, qs: list[float]) -> pl.DataFrame:
    """For each row: the score quantiles of its most specific group with enough data.
    Returns one column per q (named q0.05 ...), in the row order of `rows`."""
    names = [f"q{q}" for q in qs]
    name_of = dict(zip(qs, names, strict=True))
    out = rows.select(*LEVELS[0]).with_row_index("_i")
    filled = None
    for keys in LEVELS:
        sq = score_quantiles(cal, score, qs, keys)
        if sq.height == 0:
            continue
        wide = sq.with_columns(pl.col("q").replace_strict(name_of).alias("qn")).pivot(
            on="qn", index=keys, values="v"
        )
        j = out.join(wide, on=keys, how="left").sort("_i").select(names)
        filled = (
            j if filled is None else filled.with_columns([pl.col(c).fill_null(j[c]) for c in names])
        )
    if filled is None:
        return pl.DataFrame(
            {c: [None] * rows.height for c in names}, schema=dict.fromkeys(names, pl.Float64)
        )
    return filled


def calibration_rows(log: pl.DataFrame, origin: date) -> pl.DataFrame:
    """Earlier out-of-sample forecasts of clean days dated in [origin - 365 d, origin)."""
    return log.filter(
        (pl.col("origin") < origin)
        & pl.col("scored")
        & pl.col("date").is_between(origin - timedelta(days=365), origin, closed="left")
    )


def with_scores(df: pl.DataFrame, point: str = "lgbm") -> pl.DataFrame:
    ly = pl.col("y").log1p()
    return df.with_columns(
        (ly - pl.col(point).log1p()).alias("r"),
        pl.max_horizontal(pl.col("lgbm_q10").log1p() - ly, ly - pl.col("lgbm_q90").log1p()).alias(
            "s_cqr"
        ),
    )


def conformalize(pred: pl.DataFrame, origins: list[date], point: str = "lgbm") -> pl.DataFrame:
    """conf_lo/hi, cqr_lo/hi and p_busy for the rows of `origins`, calibrated on the
    forecast log `pred` (all origins, warm-up included)."""
    log = with_scores(pred, point)
    parts = []
    for o in origins:
        cal = calibration_rows(log, o)
        rows = pred.filter(pl.col("origin") == o)
        r = lookup(rows, cal, "r", GRID)
        s = lookup(rows, cal, "s_cqr", [COV])[f"q{COV}"].to_numpy()
        lp = np.log1p(rows[point].to_numpy())
        lo = np.expm1(lp + r[f"q{LO}"].to_numpy())
        hi = np.expm1(lp + r[f"q{HI}"].to_numpy())
        q10 = np.log1p(rows["lgbm_q10"].to_numpy())
        q90 = np.log1p(rows["lgbm_q90"].to_numpy())
        grid = r.select([f"q{q}" for q in GRID]).to_numpy()
        x = np.log1p(rows["busy_threshold"].to_numpy()) - lp
        parts.append(
            rows.select("origin", "station_id", "date").with_columns(
                pl.Series("conf_lo", np.clip(lo, 0, None)),
                pl.Series("conf_hi", hi),
                pl.Series("cqr_lo", np.clip(np.expm1(q10 - s), 0, None)),
                pl.Series("cqr_hi", np.expm1(q90 + s)),
                pl.Series("p_busy", exceed_prob(x, grid)),
                pl.lit(cal.height).alias("n_cal"),
            )
        )
    return pl.concat(parts)


def exceed_prob(x: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """1 - CDF at x (rows of `grid` = residual quantiles at GRID levels)."""
    qs = np.array(GRID)
    out = np.full(len(x), np.nan)
    for i in range(len(x)):
        g = grid[i]
        if np.isnan(x[i]) or np.isnan(g).any():
            continue
        out[i] = 1 - np.interp(x[i], g, qs, left=0.025, right=0.975)
    return out


def busy_threshold(
    history: pl.DataFrame, targets: pl.DataFrame, origin: date, q: float = 0.9
) -> pl.Series:
    """Station's q-quantile of clean daily entries on the same day group, last 365 days."""
    ref = (
        history.filter(
            pl.col("date").is_between(origin - timedelta(days=365), origin, closed="left")
        )
        .with_columns(DAY_GROUP.alias("_g"))
        .group_by("station_id", "_g")
        .agg(pl.col("n_entries").quantile(q).alias("busy_threshold"))
    )
    t = targets.select("station_id", DAY_GROUP.alias("_g")).with_row_index("_i")
    return t.join(ref, on=["station_id", "_g"], how="left").sort("_i")["busy_threshold"]


METHODS = [
    ("quantile", "lgbm_q10", "lgbm_q90"),
    ("conformal", "conf_lo", "conf_hi"),
    ("cqr", "cqr_lo", "cqr_hi"),
]


def interval_aggs(lo: str, hi: str, alpha: float = 0.2) -> list[pl.Expr]:
    """coverage, relative width, interval (Winkler) score / sum y, rows without a band."""
    y, lo_, hi_ = pl.col("y"), pl.col(lo), pl.col(hi)
    score = (
        (hi_ - lo_)
        + (2 / alpha) * (lo_ - y).clip(lower_bound=0)
        + (2 / alpha) * (y - hi_).clip(lower_bound=0)
    )
    ok = lo_.is_not_null() & hi_.is_not_null() & lo_.is_not_nan() & hi_.is_not_nan()
    return [
        pl.len().alias("n"),
        (~ok).sum().alias("n_no_band"),
        ((y >= lo_) & (y <= hi_)).filter(ok).mean().alias("coverage"),
        ((hi_ - lo_).filter(ok).sum() / y.filter(ok).sum()).alias("rel_width"),
        (score.filter(ok).sum() / y.filter(ok).sum()).alias("interval_score"),
    ]


def interval_table(pred: pl.DataFrame, by: list[str]) -> pl.DataFrame:
    parts = []
    for method, lo, hi in METHODS:
        t = pred.group_by(by) if by else pred.group_by(pl.lit("all").alias("group"))
        parts.append(t.agg(interval_aggs(lo, hi)).with_columns(pl.lit(method).alias("method")))
    return pl.concat(parts, how="diagonal").sort(["method", *(by or ["group"])])


def _busy(pred: pl.DataFrame) -> pl.DataFrame:
    return pred.filter(
        pl.col("p_busy").is_not_null()
        & pl.col("p_busy").is_not_nan()
        & pl.col("busy_threshold").is_not_null()
    ).with_columns((pl.col("y") > pl.col("busy_threshold")).cast(pl.Float64).alias("busy"))


def busy_scores(pred: pl.DataFrame) -> dict[str, float]:
    """Brier score of p_busy vs two references: always 0.1 (the threshold is a 90th
    percentile) and the observed rate of the calibration year (climatology)."""
    d = _busy(pred)
    obs, p = d["busy"].to_numpy(), d["p_busy"].to_numpy()
    brier = float(np.mean((p - obs) ** 2))
    ref = float(np.mean((0.1 - obs) ** 2))
    return {
        "n": float(len(obs)),
        "observed_rate": float(obs.mean()),
        "mean_p": float(p.mean()),
        "brier": brier,
        "brier_always_0.1": ref,
        "skill": 1 - brier / ref,
    }


def reliability(pred: pl.DataFrame, bins: int = 10) -> pl.DataFrame:
    return (
        _busy(pred)
        .with_columns((pl.col("p_busy") * bins).floor().clip(0, bins - 1).alias("bin"))
        .group_by("bin")
        .agg(pl.len().alias("n"), pl.col("p_busy").mean().alias("mean_p"), pl.col("busy").mean())
        .sort("bin")
        .select(
            (pl.col("bin") / bins).alias("p_from"), "n", "mean_p", pl.col("busy").alias("observed")
        )
    )
