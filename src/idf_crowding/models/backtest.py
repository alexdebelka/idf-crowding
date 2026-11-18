"""Rolling-origin backtest (Phase 5).

    idf-backtest run                    all origins, then the report
    idf-backtest origin 2025-06-01 ...  only these origins (resumable, one folder each)
    idf-backtest report                 combine the per-origin results
    idf-backtest summary                WAPE / coverage of every lag x weather variant run
    options: --origins N --objective tweedie|log1p --rounds N --no-weather-variant
             --lag DAYS --weather observed|production --no-quantile-models

Origins are the first day of each month; the last origin is the latest one whose full
horizon (default 60 days) is inside the data, the previous ones go back one month each.
At each origin:
    train  clean station-days from `train_start` to the day before the origin
    test   station-days origin .. origin + horizon - 1, scored only when clean
    clean  target present and not: quality flag (missing / low / high), COVID, the
           2019 strike, or a network disruption day (normal day type JOHV / SAHV with
           network_ratio < `disruption_ratio`: strikes, snow, ...)
`short_pass_share` and `station_type` are frozen at the origin (models/frozen.py).
Weather is the observed weather (real use would only have forecasts, <= 16 days ahead).

Production-like variants (step 4): `lag_days` > 0 sets a data cutoff c = origin - lag_days
(IDFM publishes a quarter ~75 days after it ends): training, frozen features, baselines,
busy thresholds and interval calibration only use data dated < c; the forecast still covers
origin .. origin + horizon - 1 (`horizon` = days since the origin, `days_since_data` =
lag + horizon). `weather_mode = "production"` replaces the weather after the first
`forecast_days` days by climatology (models/weather.py).

Writes data/processed/backtest/ (variants: backtest/variants/lagN_obs|prod/): origins/DATE/
(per origin), then predictions.parquet (one row per origin x station x date, all models),
metrics.parquet, exclusions.parquet, importance.parquet and report.md.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path

import polars as pl

from idf_crowding.config import load_config
from idf_crowding.models import baselines, gbm, intervals
from idf_crowding.models import weather as wx
from idf_crowding.models.closures import is_closure
from idf_crowding.models.frozen import add_months, apply_frozen
from idf_crowding.models.metrics import gains, horizon_bucket, network_level, summarize

BASELINES = ["naive_4w", "daytype_12m"]
MAIN = "lgbm"


@dataclass
class BacktestConfig:
    train_start: date = date(2022, 1, 1)
    n_origins: int = 12
    horizon: int = 60
    disruption_ratio: float = 0.8
    closure_ratio: float | None = 0.4  # models/closures.py; None = rule off
    naive_weeks: int = 4
    daytype_days: int = 365
    weather_variant: bool = False  # also fit LightGBM without weather (lgbm_noweather)
    intervals: bool = True  # option B: quantile / conformal / CQR bands, P(busy day)
    warmup_origins: int = 12  # extra earlier origins: forecast log for calibration only
    quantile_rounds: int = 300
    # step 4, production-like variants (defaults = the main backtest, unchanged)
    lag_days: int = 0  # data cutoff = origin - lag_days (publication lag)
    weather_mode: str = "observed"  # "observed" | "production" (climatology after forecast)
    forecast_days: int = 16  # days covered by a weather forecast at issue time
    quantile_models: bool = True  # LightGBM 10 % / 90 % fits (quantile and cqr bands)
    gbm: gbm.GBMConfig = field(default_factory=gbm.GBMConfig)

    def __post_init__(self):
        if self.weather_mode not in WEATHER_MODES:
            raise ValueError(f"weather_mode must be one of {WEATHER_MODES}")
        if self.lag_days < 0:
            raise ValueError("lag_days must be >= 0")

    @classmethod
    def from_config(cls) -> BacktestConfig:
        c = load_config().get("backtest", {})
        g = c.get("lightgbm", {})
        gcfg = gbm.GBMConfig()
        gcfg = replace(
            gcfg,
            objective=g.get("objective", gcfg.objective),
            trend=g.get("trend", gcfg.trend),
            half_life_days=g.get("half_life_days", gcfg.half_life_days),
            num_boost_round=g.get("num_boost_round", gcfg.num_boost_round),
            params={**gcfg.params, **g.get("params", {})},
        )
        return cls(
            train_start=date.fromisoformat(c.get("train_start", "2022-01-01")),
            n_origins=c.get("n_origins", cls.n_origins),
            horizon=c.get("horizon", cls.horizon),
            disruption_ratio=c.get("disruption_ratio", cls.disruption_ratio),
            closure_ratio=c.get("closure_ratio", cls.closure_ratio),
            naive_weeks=c.get("naive_weeks", cls.naive_weeks),
            daytype_days=c.get("daytype_days", cls.daytype_days),
            weather_variant=c.get("weather_variant", cls.weather_variant),
            intervals=c.get("intervals", cls.intervals),
            warmup_origins=c.get("warmup_origins", cls.warmup_origins),
            quantile_rounds=c.get("quantile_rounds", cls.quantile_rounds),
            lag_days=c.get("lag_days", cls.lag_days),
            weather_mode=c.get("weather_mode", cls.weather_mode),
            forecast_days=c.get("forecast_days", cls.forecast_days),
            quantile_models=c.get("quantile_models", cls.quantile_models),
            gbm=gcfg,
        )

    def cutoff(self, origin: date) -> date:
        """First day without data at issue date `origin`: data dated < cutoff is usable."""
        return origin - timedelta(days=self.lag_days)

    @property
    def variant(self) -> str | None:
        """Folder name of a production-like variant (None = the main backtest)."""
        if self.lag_days == 0 and self.weather_mode == "observed":
            return None
        return f"lag{self.lag_days}_{'prod' if self.weather_mode == 'production' else 'obs'}"


WEATHER_MODES = ("observed", "production")
# step-4 fields left out of the fingerprint at their default value, so results run before
# they existed stay valid
_NEW_DEFAULTS = {
    "lag_days": 0,
    "weather_mode": "observed",
    "forecast_days": 16,
    "quantile_models": True,
}


def all_origins(last_date: date, cfg: BacktestConfig) -> tuple[list[date], list[date]]:
    """(warm-up origins, scored origins). Warm-up origins precede the scored ones and only
    feed the forecast log used to calibrate the intervals."""
    n_warm = cfg.warmup_origins if cfg.intervals else 0
    both = origins(last_date, cfg.n_origins + n_warm, cfg.horizon)
    return both[:n_warm], both[n_warm:]


def origins(last_date: date, n: int, horizon: int) -> list[date]:
    """n monthly origins (first of month), the last one with a full horizon in the data."""
    o = date(last_date.year, last_date.month, 1)
    while o + timedelta(days=horizon - 1) > last_date:
        o = add_months(o, -1)
    return [add_months(o, -i) for i in range(n - 1, -1, -1)]


def exclude_reason(df: pl.DataFrame, disruption_ratio: float) -> pl.Expr:
    """Why a station-day is left out of training and scoring (null = clean). Expects an
    `is_closure` column (False everywhere when the closure rule is off)."""
    disrupted = pl.col("day_type").is_in(["JOHV", "SAHV"]) & (
        pl.col("network_ratio") < disruption_ratio
    )
    return (
        pl.when(pl.col("n_entries").is_null() | (pl.col("quality_flag") == "missing"))
        .then(pl.lit("missing"))
        .when(pl.col("is_covid"))
        .then(pl.lit("covid"))
        .when(pl.col("is_strike_2019"))
        .then(pl.lit("strike_2019"))
        .when(disrupted.fill_null(False))
        .then(pl.lit("network_disruption"))
        .when(pl.col("is_closure"))
        .then(pl.lit("closure"))
        .when(pl.col("quality_flag") == "low")
        .then(pl.lit("flag_low"))
        .when(pl.col("quality_flag") == "high")
        .then(pl.lit("flag_high"))
        .otherwise(pl.lit(None, pl.String))
        .alias("exclude")
    )


def prepare(features: pl.DataFrame, cfg: BacktestConfig) -> pl.DataFrame:
    """Rows from train_start, with `exclude` and a dense `station_code` (LightGBM wants
    consecutive category codes)."""
    if cfg.closure_ratio is None:
        closure = pl.lit(False).alias("is_closure")
    else:
        closure = is_closure(features, cfg.closure_ratio)
    return (
        features.with_columns(closure)
        .filter(pl.col("date") >= cfg.train_start)
        .with_columns(
            exclude_reason(features, cfg.disruption_ratio),
            (pl.col("station_id").rank("dense") - 1).cast(pl.Int32).alias("station_code"),
            (pl.col("date") - pl.lit(cfg.train_start))
            .dt.total_days()
            .cast(pl.Int32)
            .alias("t_days"),
        )
    )


@dataclass
class OriginResult:
    predictions: pl.DataFrame
    exclusions: pl.DataFrame
    importance: pl.DataFrame


def with_horizon(df: pl.DataFrame, origin: date) -> pl.DataFrame:
    h = ((pl.col("date") - pl.lit(origin)).dt.total_days() + 1).cast(pl.Int32)
    return df.with_columns(h.alias("horizon")).with_columns(
        horizon_bucket(pl.col("horizon").clip(upper_bound=60)).alias("horizon_bucket")
    )


def run_origin(
    data: pl.DataFrame,
    profiles: pl.DataFrame,
    origin: date,
    cfg: BacktestConfig,
    weather: pl.DataFrame | None = None,
) -> OriginResult:
    """Forecast origin .. origin + horizon - 1 from data dated < cfg.cutoff(origin).
    `weather` = daily weather since the source starts (climatology in production mode;
    defaults to the weather in `data`, i.e. since train_start)."""
    c = cfg.cutoff(origin)
    end = origin + timedelta(days=cfg.horizon)
    window = data.filter(pl.col("date") < end)
    window = apply_frozen(window, c, profiles)
    train = window.filter((pl.col("date") < c) & pl.col("exclude").is_null())
    test = with_horizon(window.filter(pl.col("date") >= origin), origin)
    if cfg.weather_mode == "production":
        w = weather if weather is not None else wx.daily_weather(data)
        test = wx.production_weather(test, w, origin, c, cfg.forecast_days)

    preds = {
        "naive_4w": baselines.seasonal_naive(train, test, c, cfg.naive_weeks),
        "daytype_12m": baselines.day_type_mean(train, test, c, cfg.daytype_days),
    }
    model = gbm.fit(train, cfg.gbm)
    preds[MAIN] = pl.Series(gbm.predict(model, test, cfg.gbm))
    imp = gbm.importance(model).with_columns(pl.lit(origin).alias("origin"))
    if cfg.weather_variant:
        nw = replace(cfg.gbm, weather=False)
        preds["lgbm_noweather"] = pl.Series(gbm.predict(gbm.fit(train, nw), test, nw))
    extra: dict[str, pl.Series] = {}
    if cfg.intervals:
        extra["busy_threshold"] = intervals.busy_threshold(train, test, c)
    if cfg.intervals and cfg.quantile_models:
        for a, name in [(intervals.LO, "lgbm_q10"), (intervals.HI, "lgbm_q90")]:
            qc = replace(
                cfg.gbm, objective="quantile", alpha=a, num_boost_round=cfg.quantile_rounds
            )
            extra[name] = pl.Series(gbm.predict(gbm.fit(train, qc), test, qc))

    variant_cols = []
    if cfg.variant:
        days_since = (pl.col("date") - pl.lit(c)).dt.total_days() + 1
        variant_cols = [
            pl.lit(c).alias("cutoff"),
            days_since.cast(pl.Int32).alias("days_since_data"),
        ]
        if "weather_source" in test.columns:
            variant_cols.append("weather_source")
    out = test.select(
        pl.lit(origin).alias("origin"),
        "station_id",
        "date",
        "horizon",
        "horizon_bucket",
        *variant_cols,
        pl.col("station_type").fill_null("none"),
        "day_type",
        "exclude",
        pl.col("n_entries").cast(pl.Float64).alias("y"),
    ).with_columns([s.alias(name) for name, s in {**preds, **extra}.items()])
    has_all = pl.all_horizontal([pl.col(m).is_not_null() for m in preds])
    out = out.with_columns(
        pl.when(pl.col("exclude").is_null() & ~has_all)
        .then(pl.lit("no_baseline"))
        .otherwise(pl.col("exclude"))
        .alias("exclude")
    ).with_columns(pl.col("exclude").is_null().alias("scored"))
    excl = out.group_by("exclude").len().with_columns(pl.lit(origin).alias("origin"))
    return OriginResult(out, excl, imp)


def to_long(pred: pl.DataFrame, models: list[str]) -> pl.DataFrame:
    keep = ["origin", "station_id", "date", "horizon", "horizon_bucket", "station_type"]
    return pred.filter(pl.col("scored")).unpivot(
        on=models, index=[*keep, "day_type", "y"], variable_name="model", value_name="pred"
    )


def metric_tables(long: pl.DataFrame) -> pl.DataFrame:
    dims = {
        "overall": [],
        "station_type": ["station_type"],
        "horizon_bucket": ["horizon_bucket"],
        "station_type x horizon_bucket": ["station_type", "horizon_bucket"],
        "day_type": ["day_type"],
        "origin": ["origin"],
    }
    parts = []
    for name, by in dims.items():
        t = summarize(long, by)
        parts.append(_tag(t, "station", name, by))
    for name, by in {"overall": [], "horizon_bucket": ["horizon_bucket"]}.items():
        parts.append(_tag(network_level(long, by), "network", name, by))
    return pl.concat(parts, how="diagonal")


def _tag(t: pl.DataFrame, level: str, name: str, by: list[str]) -> pl.DataFrame:
    group = (
        pl.concat_str([pl.col(c).cast(pl.String) for c in by], separator=" × ")
        if by
        else pl.lit("all")
    )
    return t.select(
        pl.lit(level).alias("level"),
        pl.lit(name).alias("dimension"),
        group.alias("group"),
        "model",
        "n",
        "wape",
        "mae",
        "mape",
    )


@dataclass(frozen=True)
class Paths:
    processed: Path

    @classmethod
    def from_config(cls) -> Paths:
        return cls(Path(load_config()["paths"]["data_dir"]) / "processed")


def config_fingerprint(cfg: BacktestConfig) -> str:
    d = asdict(cfg)
    for k, v in _NEW_DEFAULTS.items():
        if d[k] == v:
            del d[k]
    return json.dumps(d, default=str, sort_keys=True)


def backtest_dir(paths: Paths, cfg: BacktestConfig | None = None) -> Path:
    """backtest/ for the main run, backtest/variants/NAME/ for a lag / weather variant."""
    base = paths.processed / "backtest"
    v = cfg.variant if cfg else None
    return base / "variants" / v if v else base


def origin_dir(paths: Paths, origin: date, cfg: BacktestConfig | None = None) -> Path:
    return backtest_dir(paths, cfg) / "origins" / origin.isoformat()


def load_weather(paths: Paths) -> pl.DataFrame:
    """Daily weather since the source starts (climatology for production weather)."""
    return wx.daily_weather(pl.scan_parquet(paths.processed / "features_daily.parquet"))


def load_data(paths: Paths, cfg: BacktestConfig) -> tuple[pl.DataFrame, pl.DataFrame]:
    features = pl.read_parquet(paths.processed / "features_daily.parquet")
    profiles = pl.read_parquet(paths.processed / "station_profiles.parquet")
    return prepare(features, cfg), profiles


def run_origins(
    paths: Paths,
    cfg: BacktestConfig,
    only: list[date] | None = None,
    log: Callable[[str], None] = print,
) -> list[date]:
    """Backtest each origin; results go to backtest/origins/DATE/ (one folder per origin, so
    a long run can be split and resumed)."""
    data, profiles = load_data(paths, cfg)
    weather = load_weather(paths) if cfg.weather_mode == "production" else None
    warm, scored = all_origins(data["date"].max(), cfg)
    origs = warm + scored
    todo = [o for o in origs if o in only] if only else origs
    for o in todo:
        t0 = time.time()
        r = run_origin(data, profiles, o, cfg, weather)
        d = origin_dir(paths, o, cfg)
        d.mkdir(parents=True, exist_ok=True)
        r.predictions.write_parquet(d / "predictions.parquet")
        r.exclusions.write_parquet(d / "exclusions.parquet")
        r.importance.write_parquet(d / "importance.parquet")
        (d / "config.json").write_text(config_fingerprint(cfg), encoding="utf-8")
        n = r.predictions["scored"].sum()
        log(f"origin {o}: {n:,} scored station-days ({time.time() - t0:.0f} s)")
    return todo


def build_report(
    paths: Paths, cfg: BacktestConfig, log: Callable[[str], None] = print
) -> dict[str, pl.DataFrame]:
    """Combine the per-origin results of the current origin list into tables + report.md.
    Refuses origins that are missing or were run with another configuration."""
    last = pl.scan_parquet(paths.processed / "features_daily.parquet").select(pl.col("date").max())
    warm, origs = all_origins(last.collect().item(), cfg)
    fp = config_fingerprint(cfg)
    keys = ["predictions", "exclusions", "importance"]
    parts: dict[str, list[pl.DataFrame]] = {k: [] for k in keys}
    for o in warm + origs:
        d = origin_dir(paths, o, cfg)
        if not (d / "config.json").exists():
            raise FileNotFoundError(f"origin {o} not run yet: idf-backtest origin {o}")
        if (d / "config.json").read_text(encoding="utf-8") != fp:
            raise ValueError(f"origin {o} was run with another configuration; re-run it")
        for k in parts:
            parts[k].append(pl.read_parquet(d / f"{k}.parquet"))
    out = {k: pl.concat(v, how="diagonal") for k, v in parts.items()}
    if cfg.intervals:
        bands = intervals.conformalize(out["predictions"], origs, MAIN)
        out["predictions"] = out["predictions"].join(
            bands, on=["origin", "station_id", "date"], how="left"
        )
    # warm-up origins only calibrate the intervals: keep them out of every table
    out = {k: v.filter(pl.col("origin").is_in(origs)) for k, v in out.items()}
    out["exclusions"] = out["exclusions"].rename({"len": "n"})
    models = [*BASELINES, MAIN] + (["lgbm_noweather"] if cfg.weather_variant else [])
    long = to_long(out["predictions"], models)
    out["metrics"] = metric_tables(long)
    if cfg.intervals:
        out["intervals"] = interval_metrics(out["predictions"].filter(pl.col("scored")))
    target = backtest_dir(paths, cfg)
    for name, df in out.items():
        df.write_parquet(target / f"{name}.parquet")
    (target / "variant.json").write_text(
        json.dumps({"lag_days": cfg.lag_days, "weather_mode": cfg.weather_mode}), encoding="utf-8"
    )
    (target / "report.md").write_text(report(out, long, cfg, origs), encoding="utf-8")
    log(f"backtest report: {len(origs)} origins (+{len(warm)} warm-up) -> {target / 'report.md'}")
    return out


def interval_metrics(scored: pl.DataFrame) -> pl.DataFrame:
    parts = []
    for name, by in {
        "overall": [],
        "horizon_bucket": ["horizon_bucket"],
        "station_type": ["station_type"],
        "day_type": ["day_type"],
    }.items():
        t = intervals.interval_table(scored, by)
        group = (
            pl.concat_str([pl.col(c).cast(pl.String) for c in by], separator=" × ")
            if by
            else pl.col("group")
        )
        parts.append(
            t.select(
                pl.lit(name).alias("dimension"),
                group.alias("group"),
                "method",
                "n",
                "n_no_band",
                "coverage",
                "rel_width",
                "interval_score",
            )
        )
    return pl.concat(parts)


def run(paths: Paths, cfg: BacktestConfig, log: Callable[[str], None] = print):
    run_origins(paths, cfg, log=log)
    return build_report(paths, cfg, log)


def _md(df: pl.DataFrame, digits: int = 3) -> str:
    def fmt(v):
        if isinstance(v, float):
            return f"{v:.{digits}f}"
        return "" if v is None else str(v)

    head = "| " + " | ".join(df.columns) + " |"
    sep = "|" + "---|" * df.width
    rows = ["| " + " | ".join(fmt(v) for v in r) + " |" for r in df.iter_rows()]
    return "\n".join([head, sep, *rows])


def _natural(col: str) -> pl.Expr:
    """Sort key putting horizon buckets in order (1-7 < 8-28 < 29-60)."""
    return pl.col(col).str.replace_all(r"(\d+)", "000$1").str.replace_all(r"0*(\d{4})", "$1")


def report(
    out: dict[str, pl.DataFrame], long: pl.DataFrame, cfg: BacktestConfig, origs: list[date]
) -> str:
    m = out["metrics"]
    models = long["model"].unique(maintain_order=True).to_list()

    def wide(level: str, dim: str) -> pl.DataFrame:
        t = m.filter((pl.col("level") == level) & (pl.col("dimension") == dim))
        n = t.filter(pl.col("model") == MAIN).select("group", "n")
        w = t.pivot(on="model", index="group", values="wape").select("group", *models)
        return n.join(w, on="group").sort(_natural("group"))

    overall = m.filter(pl.col("dimension") == "overall").select(
        "level", "model", "n", "wape", "mae", "mape"
    )
    st = summarize(long, ["station_type"])
    g_all = gains(summarize(long, []), MAIN, BASELINES, [])
    g_st = gains(st, MAIN, BASELINES, ["station_type"])
    g_hb = gains(summarize(long, ["horizon_bucket"]), MAIN, BASELINES, ["horizon_bucket"]).sort(
        _natural("horizon_bucket")
    )
    excl = (
        out["exclusions"]
        .group_by("exclude")
        .agg(pl.col("n").sum())
        .with_columns(pl.col("exclude").fill_null("scored"))
        .sort("n", descending=True)
    )
    imp = (
        out["importance"]
        .group_by("feature")
        .agg(pl.col("gain").mean())
        .with_columns((pl.col("gain") / pl.col("gain").sum()).alias("gain_share"))
        .sort("gain", descending=True)
        .select("feature", "gain_share")
    )
    title = f"# Backtest report — variant {cfg.variant}" if cfg.variant else "# Backtest report"
    lines = [
        title,
        "",
        *lag_lines(cfg),
        f"Origins: {len(origs)} monthly, {origs[0]} → {origs[-1]}; horizon 1–{cfg.horizon} "
        f"days; training from {cfg.train_start}. LightGBM objective `{cfg.gbm.objective}`, "
        f"{cfg.gbm.num_boost_round} rounds, trend feature {cfg.gbm.trend}, recency half-life "
        f"{cfg.gbm.half_life_days} days.",
        "Baselines: `naive_4w` = same weekday, mean of the last 4 weeks before the origin; "
        "`daytype_12m` = per-station mean by day type over the last 12 months.",
        weather_line(cfg),
        f"Closure rule: share of network < {cfg.closure_ratio} × trailing 365-day median "
        "(models/closures.py), left out of training and scoring.",
        "",
        "## Overall (WAPE main; MAPE on station-days with y ≥ 100)",
        _md(overall),
        "",
        "## Gain of lgbm vs baselines (1 − WAPE ratio)",
        _md(g_all),
        "",
        _md(g_st),
        "",
        _md(g_hb),
        "",
        "## WAPE by station type × horizon bucket",
        _md(wide("station", "station_type x horizon_bucket")),
        "",
        "## WAPE by day type",
        _md(wide("station", "day_type")),
        "",
        "## Network level (daily totals of scored stations)",
        _md(wide("network", "horizon_bucket")),
        "",
        "## WAPE by origin",
        _md(wide("station", "origin")),
        "",
        "## Test station-days by exclusion reason (all origins)",
        _md(excl),
        "",
        "## LightGBM feature importance (mean gain share)",
        _md(imp),
        "",
    ]
    if "intervals" in out:
        lines += interval_report(out)
    return "\n".join(lines)


def weather_line(cfg: BacktestConfig) -> str:
    if cfg.weather_mode == "production":
        return (
            f"Weather: **production-like**: observed for days 1–{cfg.forecast_days} after the "
            "origin (stands in for a weather forecast; forecast error ignored), day-of-year "
            "climatology (± 7 days, years before the cutoff) after. "
        )
    return "Weather is the **observed** weather (real forecasts only reach ~16 days). "


def lag_lines(cfg: BacktestConfig) -> list[str]:
    if not cfg.lag_days:
        return []
    return [
        f"**Publication lag {cfg.lag_days} days**: at origin o, only data dated before "
        f"c = o − {cfg.lag_days} d is used (training, frozen features, baselines, busy "
        "thresholds, interval calibration). Horizon = days since the origin; days since the "
        f"last data = {cfg.lag_days} + horizon.",
        "",
    ]


def interval_report(out: dict[str, pl.DataFrame]) -> list[str]:
    iv = out["intervals"]
    scored = out["predictions"].filter(pl.col("scored"))

    def tab(dim: str) -> pl.DataFrame:
        t = iv.filter(pl.col("dimension") == dim)
        return (
            t.pivot(on="method", index="group", values="coverage")
            .join(
                t.pivot(on="method", index="group", values="interval_score"),
                on="group",
                suffix="_score",
            )
            .sort(_natural("group"))
        )

    busy = intervals.busy_scores(scored)
    return [
        "## Option B: 80 % intervals (target coverage 0.80)",
        "Calibration = forecast log: earlier origins' out-of-sample forecasts for clean days "
        "of the 365 days before each origin's data cutoff (the origin, or origin − lag; 12 "
        "warm-up origins before the first scored one). "
        "`quantile` = LightGBM quantile 10 % / 90 % on log1p, raw; `conformal` = point "
        "forecast + residual quantiles by day type × station type × horizon bucket; `cqr` = "
        "conformalized quantile band. Interval score = Winkler score / Σy (lower is better).",
        _md(iv.filter(pl.col("dimension") == "overall").drop("dimension", "group")),
        "",
        "Coverage and interval score by horizon bucket, station type, day type:",
        _md(tab("horizon_bucket")),
        "",
        _md(tab("station_type")),
        "",
        _md(tab("day_type")),
        "",
        "## Option B: P(busy day) (entries > the station's p90 of the last 365 days, same "
        "day group)",
        _md(pl.DataFrame([busy])),
        "",
        "Reliability (predicted vs observed rate):",
        _md(intervals.reliability(scored)),
        "",
    ]


def variant_dirs(paths: Paths) -> list[Path]:
    """Main backtest folder + every variant folder that has a report."""
    base = paths.processed / "backtest"
    dirs = [base] + sorted((base / "variants").glob("*/"))
    return [d for d in dirs if (d / "metrics.parquet").exists()]


def summary(paths: Paths, log: Callable[[str], None] = print) -> pl.DataFrame:
    """One row per variant x model: WAPE overall / by horizon bucket, network WAPE, and the
    conformal band (coverage, interval score) of lgbm. Writes backtest/variants/summary.md."""
    rows = []
    for d in variant_dirs(paths):
        meta = (
            json.loads((d / "variant.json").read_text(encoding="utf-8"))
            if (d / "variant.json").exists()
            else {"lag_days": 0, "weather_mode": "observed"}
        )
        m = pl.read_parquet(d / "metrics.parquet")
        st = m.filter(pl.col("level") == "station")
        wide = (
            st.filter(pl.col("dimension").is_in(["overall", "horizon_bucket"]))
            .with_columns(
                pl.when(pl.col("dimension") == "overall")
                .then(pl.lit("wape"))
                .otherwise(pl.lit("wape_") + pl.col("group"))
                .alias("k")
            )
            .pivot(on="k", index="model", values="wape")
        )
        n = st.filter(pl.col("dimension") == "overall").select("model", "n")
        net = m.filter((pl.col("level") == "network") & (pl.col("dimension") == "overall"))
        t = n.join(wide, on="model").join(
            net.select("model", pl.col("wape").alias("network_wape")), on="model", how="left"
        )
        if (d / "intervals.parquet").exists():
            iv = pl.read_parquet(d / "intervals.parquet").filter(
                (pl.col("dimension") == "overall") & (pl.col("method") == "conformal")
            )
            t = t.with_columns(
                pl.when(pl.col("model") == MAIN).then(iv["coverage"][0]).alias("coverage"),
                pl.when(pl.col("model") == MAIN).then(iv["interval_score"][0]).alias("int_score"),
            )
        rows.append(
            t.with_columns(
                pl.lit(meta["lag_days"]).alias("lag"), pl.lit(meta["weather_mode"]).alias("weather")
            )
        )
    if not rows:
        raise FileNotFoundError("no backtest report yet")
    order = {m: i for i, m in enumerate([MAIN, *BASELINES])}
    out = (
        pl.concat(rows, how="diagonal")
        .with_columns(pl.col("model").replace_strict(order, default=99).alias("_o"))
        .sort("lag", "weather", "_o")
        .drop("_o")
    )
    cols = ["lag", "weather", "model", "n", "wape"]
    cols += [c for c in ["wape_1-7", "wape_8-28", "wape_29-60"] if c in out.columns]
    cols += [c for c in ["network_wape", "coverage", "int_score"] if c in out.columns]
    out = out.select(cols)
    target = paths.processed / "backtest" / "variants"
    target.mkdir(parents=True, exist_ok=True)
    text = [
        "# Backtest variants: publication lag x weather",
        "",
        "Each row = one `idf-backtest` run (24 origins incl. 12 warm-up; scored rows of the 12 "
        "scored origins). lag = days between the data cutoff and the origin; horizon buckets "
        "count days since the origin. coverage / int_score = lgbm conformal 80 % band.",
        "Scored rows differ slightly between lags (stations without data before the cutoff).",
        "",
        _md(out),
        "",
    ]
    (target / "summary.md").write_text("\n".join(text), encoding="utf-8")
    out.write_parquet(target / "summary.parquet")
    log(f"summary of {len(rows)} runs -> {target / 'summary.md'}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="idf-backtest", description=__doc__.splitlines()[0])
    parser.add_argument(
        "command",
        choices=["run", "origin", "report", "summary"],
        help="run = all origins + report; origin = only the given origins; report = combine; "
        "summary = table of all lag / weather variants",
    )
    parser.add_argument("dates", nargs="*", help="origins for `origin` (YYYY-MM-DD)")
    parser.add_argument("--origins", type=int, help="number of monthly origins")
    parser.add_argument("--objective", choices=["tweedie", "log1p"])
    parser.add_argument("--rounds", type=int, help="LightGBM boosting rounds")
    parser.add_argument("--no-weather-variant", action="store_true")
    parser.add_argument("--lag", type=int, help="publication lag in days (data cutoff)")
    parser.add_argument("--weather", choices=list(WEATHER_MODES))
    parser.add_argument(
        "--no-quantile-models", action="store_true", help="skip the quantile / cqr bands"
    )
    a = parser.parse_args(argv)
    cfg = BacktestConfig.from_config()
    if a.origins:
        cfg = replace(cfg, n_origins=a.origins)
    if a.objective:
        cfg = replace(cfg, gbm=replace(cfg.gbm, objective=a.objective))
    if a.rounds:
        cfg = replace(cfg, gbm=replace(cfg.gbm, num_boost_round=a.rounds))
    if a.no_weather_variant:
        cfg = replace(cfg, weather_variant=False)
    if a.lag is not None:
        cfg = replace(cfg, lag_days=a.lag)
    if a.weather:
        cfg = replace(cfg, weather_mode=a.weather)
    if a.no_quantile_models:
        cfg = replace(cfg, quantile_models=False)
    paths = Paths.from_config()
    if a.command == "summary":
        summary(paths)
        return 0
    if a.command == "run":
        run(paths, cfg)
    elif a.command == "origin":
        if not a.dates:
            parser.error("origin needs at least one date")
        done = run_origins(paths, cfg, [date.fromisoformat(d) for d in a.dates])
        if not done:
            parser.error("none of these dates is a backtest origin")
    else:
        build_report(paths, cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
