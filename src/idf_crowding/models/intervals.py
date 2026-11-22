"""Option B: 80 % prediction intervals and busy-day probabilities.

Calibration uses a forecast log, as a deployed forecaster would: at origin o with data
cutoff c (c = o, or o - lag with a publication lag; `cutoff` column of the log), the
calibration set is every earlier forecast (origins before o, `warmup_origins` extra ones
before the first scored origin) for clean station-days dated in [c - 365 days, c). Those
forecasts are out-of-sample and their outcomes are published at o; a full year covers every
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
group over the 365 days before the cutoff ("yearly", used by the backtest), or within
± 45 days of the date's day of year over all years before the cutoff, relative to the local
level and grown to the date's level ("seasonal", busy_threshold). P(busy) = 1 - CDF of the
residuals at log1p(threshold) - log1p(pred) (grid 5 % .. 95 %, linear, tails clamped
2.5 / 97.5 %). Recalibrated P(busy), fitted at each origin on the same forecast-log rows as
the intervals (earlier origins, dated in the last 365 days): isotonic regression on P(busy),
or logistic regression on logit(P(busy)) + context (recalibrate_busy_logistic). Comparison
on the production-like log: models/busy.py (`idf-busy`); none is accepted, P(busy) is not
produced.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import polars as pl

from idf_crowding.models.closures import DAY_GROUP
from idf_crowding.models.metrics import BUCKETS

GRID = [round(0.05 * i, 2) for i in range(1, 20)]  # 0.05 .. 0.95
LO, HI = 0.1, 0.9
COV = 0.8  # HI - LO
MIN_CAL = 500
SEASON_DAYS = 45  # seasonal busy threshold: ± days of the target's day of year
SEASON_MIN_DAYS = 20  # fewer clean days in the window -> yearly threshold
LOCAL_DAYS = 10  # seasonal threshold: local level = median of ± days (0 = off)
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


def calibration_rows(log: pl.DataFrame, origin: date, cutoff: date | None = None) -> pl.DataFrame:
    """Earlier out-of-sample forecasts of clean days dated in [cutoff - 365 d, cutoff)
    (cutoff = origin when there is no publication lag)."""
    c = cutoff or origin
    return log.filter(
        (pl.col("origin") < origin)
        & pl.col("scored")
        & pl.col("date").is_between(c - timedelta(days=365), c, closed="left")
    )


def cutoff_of(pred: pl.DataFrame, origin: date) -> date:
    """Data cutoff of an origin: its `cutoff` column when present, else the origin."""
    if "cutoff" not in pred.columns:
        return origin
    c = pred.filter(pl.col("origin") == origin)["cutoff"].drop_nulls()
    return c[0] if len(c) else origin


def with_scores(
    df: pl.DataFrame, point: str = "lgbm", q10: str = "lgbm_q10", q90: str = "lgbm_q90"
) -> pl.DataFrame:
    ly = pl.col("y").log1p()
    if q10 in df.columns and q90 in df.columns:
        s = pl.max_horizontal(pl.col(q10).log1p() - ly, ly - pl.col(q90).log1p())
    else:  # no quantile models (e.g. lag variants): conformal only
        s = pl.lit(None, pl.Float64)
    return df.with_columns((ly - pl.col(point).log1p()).alias("r"), s.alias("s_cqr"))


def conformalize(
    pred: pl.DataFrame,
    origins: list[date],
    point: str = "lgbm",
    q10: str = "lgbm_q10",
    q90: str = "lgbm_q90",
) -> pl.DataFrame:
    """conf_lo/hi (around `point`), cqr_lo/hi (around the `q10`/`q90` band) and p_busy for
    the rows of `origins`, calibrated on the forecast log `pred` (all origins, warm-up
    included). With a `cutoff` column, origin o is calibrated on rows dated before its cutoff.
    Without `q10`/`q90` columns the cqr band is null."""
    log = with_scores(pred, point, q10, q90)
    has_q = q10 in pred.columns and q90 in pred.columns
    parts = []
    for o in origins:
        cal = calibration_rows(log, o, cutoff_of(pred, o))
        rows = pred.filter(pl.col("origin") == o)
        r = lookup(rows, cal, "r", GRID)
        s = lookup(rows, cal, "s_cqr", [COV])[f"q{COV}"].to_numpy().astype(float)
        lp = np.log1p(rows[point].to_numpy())
        lo = np.expm1(lp + r[f"q{LO}"].to_numpy())
        hi = np.expm1(lp + r[f"q{HI}"].to_numpy())
        nan = np.full(rows.height, np.nan)
        lq10 = np.log1p(rows[q10].to_numpy()) if has_q else nan
        lq90 = np.log1p(rows[q90].to_numpy()) if has_q else nan
        grid = r.select([f"q{q}" for q in GRID]).to_numpy()
        x = np.log1p(rows["busy_threshold"].to_numpy()) - lp
        parts.append(
            rows.select("origin", "station_id", "date").with_columns(
                pl.Series("conf_lo", np.clip(lo, 0, None)),
                pl.Series("conf_hi", hi),
                pl.Series("cqr_lo", np.clip(np.expm1(lq10 - s), 0, None)),
                pl.Series("cqr_hi", np.expm1(lq90 + s)),
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
    history: pl.DataFrame,
    targets: pl.DataFrame,
    origin: date,
    q: float = 0.9,
    method: str = "yearly",
    rates: pl.DataFrame | None = None,
    window_days: int = SEASON_DAYS,
    min_days: int = SEASON_MIN_DAYS,
    local_days: int = LOCAL_DAYS,
) -> pl.Series:
    """Station's q-quantile of clean daily entries on the same day group, from rows dated
    before `origin` (pass the data cutoff when there is a publication lag).

    method "yearly": the 365 days before `origin` (targets need `station_id`, `day_type`).
    method "seasonal": days within ± `window_days` of the target's day of year, all years
    before `origin` (targets also need `date`); the yearly threshold when fewer than
    `min_days` such days. With `rates` (growth.growth_rates at `origin`) every reference day
    is brought to the target's level: × g ** ((target date − reference date) / 364), g of
    the weekday class (growth.py), so the threshold follows level growth over the lag."""
    if method == "seasonal":
        return seasonal_threshold(
            history, targets, origin, q, rates, window_days, min_days, local_days
        )
    if method != "yearly":
        raise ValueError(f"unknown busy threshold method: {method}")
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


def _growth_exp(rates: pl.DataFrame | None, cutoff: date) -> pl.Expr:
    """g ** ((date − cutoff) / 364) per weekday class (1 without rates)."""
    if rates is None:
        return pl.lit(1.0)
    from idf_crowding.models.growth import weekday_class

    g = dict(rates.iter_rows())
    days = (pl.col("date") - pl.lit(cutoff)).dt.total_days()
    lg = weekday_class().replace_strict({k: float(np.log(v)) for k, v in g.items()}, default=0.0)
    return (lg * days / 364).exp()


def _doy_dist(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """|a_i - b_j| in days of year, around the year end (len(a) x len(b))."""
    d = np.abs(a[:, None] - b[None, :])
    return np.minimum(d, 365 - d)


def _local_level(rd: np.ndarray, rv: np.ndarray, days: int, min_n: int = 3) -> np.ndarray | None:
    """Median of the values within ± `days` of each day of year 1..366 (None when `days`
    is 0 or a day of year has fewer than `min_n` values)."""
    if days <= 0:
        return None
    near = _doy_dist(np.arange(1, 367), rd) <= days
    if (near.sum(axis=1) < min_n).any():
        return None
    return np.nanmedian(np.where(near, rv[None, :], np.nan), axis=1)


def seasonal_threshold(
    history: pl.DataFrame,
    targets: pl.DataFrame,
    cutoff: date,
    q: float = 0.9,
    rates: pl.DataFrame | None = None,
    window_days: int = SEASON_DAYS,
    min_days: int = SEASON_MIN_DAYS,
    local_days: int = LOCAL_DAYS,
) -> pl.Series:
    """See busy_threshold(method="seasonal"). Computed at the cutoff's level (each reference
    day × g ** ((cutoff − day) / 364)), then × g ** ((target − cutoff) / 364); quantiles are
    scale-equivariant, so this equals scaling each day to the target date directly."""
    h = (
        history.filter(pl.col("date") < cutoff)
        .filter(pl.col("n_entries").is_not_null())
        .select(
            "station_id",
            DAY_GROUP.alias("_g"),
            pl.col("date").dt.ordinal_day().cast(pl.Int32).alias("_doy"),
            (pl.col("n_entries").cast(pl.Float64) / _growth_exp(rates, cutoff)).alias("_v"),
            (pl.col("date") >= cutoff - timedelta(days=365)).alias("_last_year"),
        )
    )
    yearly = (
        h.filter("_last_year")
        .group_by("station_id", "_g")
        .agg(pl.col("_v").quantile(q).alias("_yearly"))
    )
    t = targets.select(
        "station_id",
        DAY_GROUP.alias("_g"),
        "date",
        pl.col("date").dt.ordinal_day().cast(pl.Int32).alias("_doy"),
    ).with_row_index("_i")
    want = t.select("station_id", "_g", "_doy").unique()
    hist_by = h.partition_by(["station_id", "_g"], as_dict=True)
    rows_s, rows_g, rows_d, rows_v = [], [], [], []
    for (st, grp), w in want.partition_by(["station_id", "_g"], as_dict=True).items():
        ref = hist_by.get((st, grp))
        doys = w["_doy"].to_numpy()
        val = np.full(len(doys), np.nan)
        if ref is not None:
            rd, rv = ref["_doy"].to_numpy(), ref["_v"].to_numpy()
            near = _doy_dist(doys, rd) <= window_days
            enough = near.sum(axis=1) >= min_days
            if enough.any():
                level = _local_level(rd, rv, local_days)
                if level is None:  # too few days for a local level: plain quantile
                    m = np.where(near[enough], rv[None, :], np.nan)
                    val[enough] = np.nanquantile(m, q, axis=1)
                else:
                    ratio = rv / level[rd - 1]
                    m = np.where(near[enough], ratio[None, :], np.nan)
                    val[enough] = level[doys[enough] - 1] * np.nanquantile(m, q, axis=1)
        rows_s.append(np.full(len(doys), st))
        rows_g += [grp] * len(doys)
        rows_d.append(doys)
        rows_v.append(val)
    if rows_s:
        seas = pl.DataFrame(
            {
                "station_id": np.concatenate(rows_s),
                "_g": rows_g,
                "_doy": np.concatenate(rows_d).astype(np.int32),
                "_seasonal": np.concatenate(rows_v),
            },
            schema_overrides={"station_id": t.schema["station_id"]},
        ).with_columns(pl.col("_seasonal").fill_nan(None))
    else:
        seas = pl.DataFrame(
            schema={
                "station_id": t.schema["station_id"],
                "_g": pl.String,
                "_doy": pl.Int32,
                "_seasonal": pl.Float64,
            }
        )
    out = (
        t.join(seas, on=["station_id", "_g", "_doy"], how="left")
        .join(yearly, on=["station_id", "_g"], how="left")
        .sort("_i")
        .select(
            (pl.coalesce("_seasonal", "_yearly") * _growth_exp(rates, cutoff)).alias(
                "busy_threshold"
            )
        )
    )
    return out["busy_threshold"]


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
        if lo not in pred.columns or pred[lo].fill_nan(None).is_null().all():
            continue  # e.g. no quantile models in a lag variant
        t = pred.group_by(by) if by else pred.group_by(pl.lit("all").alias("group"))
        parts.append(t.agg(interval_aggs(lo, hi)).with_columns(pl.lit(method).alias("method")))
    return pl.concat(parts, how="diagonal").sort(["method", *(by or ["group"])])


def _busy(pred: pl.DataFrame, p: str = "p_busy") -> pl.DataFrame:
    return pred.filter(
        pl.col(p).is_not_null() & pl.col(p).is_not_nan() & pl.col("busy_threshold").is_not_null()
    ).with_columns(
        pl.col(p).alias("p_busy"),
        (pl.col("y") > pl.col("busy_threshold")).cast(pl.Float64).alias("busy"),
    )


def recalibrate_busy(pred: pl.DataFrame, origins: list[date], p: str = "p_busy") -> pl.DataFrame:
    """origin, station_id, date, p_busy_iso for the rows of `origins`. The isotonic mapping
    used at origin o is fitted on (p, outcome) of `calibration_rows(pred, o, cutoff)` only:
    earlier origins, clean days dated in [c - 365 d, c), whose outcomes are known at o."""
    from sklearn.isotonic import IsotonicRegression

    hist = _busy(pred, p)
    parts = []
    for o in origins:
        cal = calibration_rows(hist, o, cutoff_of(pred, o))
        rows = pred.filter(pl.col("origin") == o)
        x = rows[p].to_numpy().astype(float)
        out = np.full(len(x), np.nan)
        if cal.height >= MIN_CAL:
            iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
            iso.fit(cal["p_busy"].to_numpy(), cal["busy"].to_numpy())
            ok = ~np.isnan(x)
            out[ok] = iso.predict(x[ok])
        parts.append(
            rows.select("origin", "station_id", "date").with_columns(pl.Series("p_busy_iso", out))
        )
    return pl.concat(parts)


LOGIT_EPS = 1e-3


def season(col: str = "date") -> pl.Expr:
    """DJF / MAM / JJA / SON of a date column."""
    m = pl.col(col).dt.month()
    return (
        pl.when(m.is_in([12, 1, 2]))
        .then(pl.lit("DJF"))
        .when(m.is_in([3, 4, 5]))
        .then(pl.lit("MAM"))
        .when(m.is_in([6, 7, 8]))
        .then(pl.lit("JJA"))
        .otherwise(pl.lit("SON"))
    )


def _logistic_design(df: pl.DataFrame, p: str, context: list[str]) -> np.ndarray:
    """logit(p) and one indicator column per level of each context column (fixed level
    sets, so a level missing from the calibration rows gets a zero coefficient)."""
    levels = {
        "horizon_bucket": [b[2] for b in BUCKETS],
        "season": ["DJF", "MAM", "JJA", "SON"],
        "day_group": ["JO", "SA", "DI"],
    }
    x = np.clip(df[p].to_numpy().astype(float), LOGIT_EPS, 1 - LOGIT_EPS)
    cols = [np.log(x / (1 - x))]
    exprs = {"season": season(), "day_group": DAY_GROUP, "horizon_bucket": pl.col("horizon_bucket")}
    for c in context:
        v = df.select(exprs[c].alias("_c"))["_c"].to_numpy()
        cols += [(v == lv).astype(float) for lv in levels[c][1:]]  # first level = reference
    return np.column_stack(cols)


def recalibrate_busy_logistic(
    pred: pl.DataFrame,
    origins: list[date],
    p: str = "p_busy",
    context: tuple[str, ...] = ("horizon_bucket",),
) -> pl.DataFrame:
    """origin, station_id, date, p_busy_logit for the rows of `origins`: logistic regression
    of the outcome on logit(p) + indicators of `context` (horizon_bucket, season, day_group),
    fitted at origin o on `calibration_rows(pred, o, cutoff)` only (earlier origins, clean
    days dated in [c - 365 d, c)), like recalibrate_busy."""
    from sklearn.linear_model import LogisticRegression

    hist = _busy(pred, p)
    ctx = list(context)
    parts = []
    for o in origins:
        cal = calibration_rows(hist, o, cutoff_of(pred, o))
        rows = pred.filter(pl.col("origin") == o)
        x = rows[p].to_numpy().astype(float)
        out = np.full(len(x), np.nan)
        y = cal["busy"].to_numpy() if cal.height else np.array([])
        if cal.height >= MIN_CAL and 0 < y.sum() < len(y):
            m = LogisticRegression(C=1e4, max_iter=1000)
            m.fit(_logistic_design(cal, "p_busy", ctx), y)
            ok = ~np.isnan(x)
            if ok.any():
                out[ok] = m.predict_proba(_logistic_design(rows.filter(pl.Series(ok)), p, ctx))[
                    :, 1
                ]
        parts.append(
            rows.select("origin", "station_id", "date").with_columns(pl.Series("p_busy_logit", out))
        )
    return pl.concat(parts)


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
