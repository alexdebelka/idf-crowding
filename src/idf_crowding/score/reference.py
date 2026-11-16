"""Stop reference helpers: latest snapshot, stop -> line -> ZdC, line colours, coordinates.

Sources (DATA_SOURCES.md #4, #17, #18), all CSV exports with ";":
    idfm/reference/zones-d-arrets/<date>.csv       zdaid -> zdcid
    idfm/reference/arrets/<date>.csv               arrid -> zdaid
    idfm/reference/arrets-lignes/<date>.csv        line id, stop_id, mode
    idfm/reference/referentiel-des-lignes/<date>.csv  line codes, colours, network
`arrets-lignes` stop_id is either "IDFM:monomodalStopPlace:<zdaid>" (rail) or
"IDFM:<arrid>" (metro, tram): both are mapped to the ZdC = Counting point.
"""

from __future__ import annotations

import math
from pathlib import Path

import polars as pl

# Line kinds shown as badges, from referentiel-des-lignes (transportmode / networkname).
KIND_ORDER = {"metro": 0, "rer": 1, "transilien": 2, "tram": 3}


def latest_snapshot(raw: Path, dataset: str) -> Path | None:
    files = sorted((raw / "idfm/reference" / dataset).glob("*.csv"))
    return files[-1] if files else None


def _read(path: Path, columns: list[str]) -> pl.DataFrame:
    return pl.read_csv(path, separator=";", infer_schema=False, encoding="utf8-lossy").select(
        columns
    )


def _require(raw: Path, dataset: str) -> Path:
    path = latest_snapshot(raw, dataset)
    if path is None:
        raise FileNotFoundError(f"no snapshot of {dataset} in {raw}; run `idf-ingest run`")
    return path


def stop_lines(raw: Path) -> pl.DataFrame:
    """One row per ZdC (station_id) x line: station_id, line_id, mode (arrets-lignes mode)."""
    al = _read(_require(raw, "arrets-lignes"), ["id", "stop_id", "mode"])
    zda = _read(_require(raw, "zones-d-arrets"), ["zdaid", "zdcid"]).select(
        pl.col("zdaid").cast(pl.Int64), pl.col("zdcid").cast(pl.Int64)
    )
    arr = _read(_require(raw, "arrets"), ["arrid", "zdaid"]).select(
        pl.col("arrid").cast(pl.Int64), pl.col("zdaid").cast(pl.Int64).alias("zda_of_arr")
    )
    return stop_lines_from(al, zda, arr)


def stop_lines_from(al: pl.DataFrame, zda: pl.DataFrame, arr: pl.DataFrame) -> pl.DataFrame:
    num = pl.col("stop_id").str.extract(r"(\d+)$", 1).cast(pl.Int64)
    df = (
        al.with_columns(
            num.alias("num"),
            pl.col("stop_id").str.contains("monomodalStopPlace").alias("is_zda"),
            pl.col("id").str.replace(r"^IDFM:", "").alias("line_id"),
        )
        .join(arr, left_on="num", right_on="arrid", how="left")
        .with_columns(
            pl.when(pl.col("is_zda"))
            .then(pl.col("num"))
            .otherwise(pl.col("zda_of_arr"))
            .alias("zdaid")
        )
        .join(zda, on="zdaid", how="left")
    )
    return (
        df.filter(pl.col("zdcid").is_not_null())
        .select(pl.col("zdcid").alias("station_id"), "line_id", "mode")
        .unique()
        .sort("station_id", "line_id")
    )


def line_info(raw: Path) -> pl.DataFrame:
    path = _require(raw, "referentiel-des-lignes")
    cols = [
        "id_line",
        "shortname_line",
        "transportmode",
        "networkname",
        "colourweb_hexa",
        "textcolourweb_hexa",
        "status",
    ]
    return line_info_from(_read(path, cols))


def line_info_from(ref: pl.DataFrame) -> pl.DataFrame:
    """Badge lines only (metro, RER, Transilien, tram), active: line_id, name, kind, colours."""
    kind = (
        pl.when(pl.col("transportmode") == "metro")
        .then(pl.lit("metro"))
        .when(pl.col("networkname") == "RER")
        .then(pl.lit("rer"))
        .when(pl.col("networkname") == "Transilien")
        .then(pl.lit("transilien"))
        .when(pl.col("transportmode") == "tram")
        .then(pl.lit("tram"))
    )
    return (
        ref.filter(pl.col("status") == "active")
        .with_columns(kind.alias("kind"))
        .filter(pl.col("kind").is_not_null())
        .select(
            pl.col("id_line").alias("line_id"),
            pl.col("shortname_line").alias("name"),
            "kind",
            ("#" + pl.col("colourweb_hexa").str.to_lowercase()).alias("color"),
            ("#" + pl.col("textcolourweb_hexa").str.to_lowercase()).alias("text_color"),
        )
    )


def apply_aliases(sl: pl.DataFrame, aliases: dict[int, int]) -> pl.DataFrame:
    """Move lines of reference ZdC `from` to data ZdC `to` (see config [score.zdc_aliases])."""
    if not aliases:
        return sl
    return (
        sl.with_columns(pl.col("station_id").replace(aliases))
        .unique()
        .sort("station_id", "line_id")
    )


def in_scope(sl: pl.DataFrame, modes: list[str], extra_lines: list[str]) -> pl.Series:
    """Station ids served by one of `modes` (arrets-lignes mode) or one of `extra_lines`
    (line short names resolved through line_id, e.g. T4)."""
    return (
        sl.filter(pl.col("mode").is_in(modes) | pl.col("line_id").is_in(extra_lines))
        .get_column("station_id")
        .unique()
        .sort()
    )


def lambert93_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """EPSG:2154 (Lambert-93) -> (lat, lon) in degrees on GRS80 (RGF93 ~ WGS84, < 1 m).
    Inverse Lambert conformal conic, IGN algorithms ALG0004 / ALG0001."""
    n, c = 0.7256077650532670, 11754255.4261
    xs, ys = 700000.0, 12655612.0499
    e, lon0 = 0.0818191910428158, math.radians(3.0)
    dx, dy = x - xs, ys - y
    r, gamma = math.hypot(dx, dy), math.atan2(dx, dy)
    lon = lon0 + gamma / n
    iso = -math.log(r / c) / n
    phi = 2 * math.atan(math.exp(iso)) - math.pi / 2
    for _ in range(20):
        es = e * math.sin(phi)
        nxt = 2 * math.atan(((1 + es) / (1 - es)) ** (e / 2) * math.exp(iso)) - math.pi / 2
        if abs(nxt - phi) < 1e-12:
            phi = nxt
            break
        phi = nxt
    return math.degrees(phi), math.degrees(lon)
