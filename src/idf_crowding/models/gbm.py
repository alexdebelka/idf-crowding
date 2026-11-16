"""Global LightGBM model: one model for all stations, direct multi-horizon.

No lags: the forecast for any horizon only uses calendar, weather, the frozen ticket ramp,
the frozen station type and the station id (categorical), so a single model serves
horizons 1-60 without leakage.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import polars as pl

from idf_crowding.models.level import LEVEL_FEATURES

DAY_TYPES = ["JOHV", "JOVS", "SAHV", "SAVS", "DIJFP"]
STATION_TYPES = ["origin", "mixed", "destination"]
WEATHER = ["precip_mm", "snow_cm", "precip_hours", "tmax_c", "tmin_c"]
CALENDAR = [
    "weekday",
    "month",
    "day_of_year",
    "is_public_holiday",
    "is_bridge",
    "is_school_holiday",
]
# station_code = dense 0..n-1 code of station_id (models/backtest.py `prepare`)
CATEGORICAL = ["station_code", "day_type", "station_type"]


@dataclass
class GBMConfig:
    objective: str = "tweedie"  # "tweedie" (raw counts) or "log1p" (L2 on log1p counts)
    weather: bool = True
    trend: bool = True  # add `t_days` (days since train start): lets trees isolate recent eras
    half_life_days: float | None = 365  # recency weights 0.5 ** (age / half_life)
    level: bool = False  # recent station level at the origin + horizon (models/level.py)
    alpha: float | None = None  # quantile level when objective == "quantile" (on log1p)
    num_boost_round: int = 600
    params: dict = field(
        default_factory=lambda: {
            "learning_rate": 0.05,
            "num_leaves": 255,
            "min_data_in_leaf": 50,
            "feature_fraction": 0.9,
            "bagging_fraction": 0.8,
            "bagging_freq": 1,
            "cat_smooth": 10,
            "tweedie_variance_power": 1.3,
            "num_threads": 0,
            "seed": 0,
            "deterministic": True,
            "verbose": -1,
        }
    )

    def features(self) -> list[str]:
        cols = ["station_code", *CALENDAR, "day_type", "station_type", "am_share_7_10"]
        cols.append("short_pass_share")
        if self.weather:
            cols += WEATHER
        if self.trend:
            cols.append("t_days")
        if self.level:
            cols += LEVEL_FEATURES
        return cols


def design_matrix(df: pl.DataFrame, cols: list[str]) -> np.ndarray:
    """float64 matrix; categoricals as fixed integer codes, nulls as NaN."""
    exprs = []
    for c in cols:
        if c == "day_type":
            e = pl.col(c).replace_strict(DAY_TYPES, list(range(len(DAY_TYPES))), default=None)
        elif c == "station_type":
            e = pl.col(c).replace_strict(
                STATION_TYPES, list(range(len(STATION_TYPES))), default=None
            )
        else:
            e = pl.col(c)
        exprs.append(e.cast(pl.Float64).alias(c))
    return df.select(exprs).to_numpy()


def recency_weights(train: pl.DataFrame, half_life_days: float | None) -> np.ndarray | None:
    """0.5 ** (days before the last training date / half life); None = equal weights."""
    if not half_life_days:
        return None
    age = (train["date"].max() - train["date"]).dt.total_days().to_numpy()
    return np.power(0.5, age / half_life_days)


def fit(train: pl.DataFrame, cfg: GBMConfig):
    import lightgbm as lgb

    cols = cfg.features()
    x = design_matrix(train, cols)
    y = train["n_entries"].cast(pl.Float64).to_numpy()
    params = dict(cfg.params)
    if cfg.objective == "tweedie":
        params["objective"] = "tweedie"
    elif cfg.objective == "log1p":
        params["objective"] = "regression"
        params.pop("tweedie_variance_power", None)
        y = np.log1p(y)
    elif cfg.objective == "quantile":
        # quantiles commute with monotone transforms: fit on log1p, back-transform exactly
        params.update(objective="quantile", alpha=cfg.alpha)
        params.pop("tweedie_variance_power", None)
        y = np.log1p(y)
    else:
        raise ValueError(f"unknown objective {cfg.objective!r}")
    cats = [c for c in CATEGORICAL if c in cols]
    w = recency_weights(train, cfg.half_life_days)
    ds = lgb.Dataset(
        x, y, weight=w, feature_name=cols, categorical_feature=cats, free_raw_data=True
    )
    return lgb.train(params, ds, num_boost_round=cfg.num_boost_round)


def predict(model, df: pl.DataFrame, cfg: GBMConfig) -> np.ndarray:
    p = model.predict(design_matrix(df, cfg.features()))
    if cfg.objective in ("log1p", "quantile"):
        p = np.expm1(p)
    return np.clip(p, 0, None)


def importance(model) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "feature": model.feature_name(),
            "gain": model.feature_importance("gain"),
            "splits": model.feature_importance("split"),
        }
    ).sort("gain", descending=True)
