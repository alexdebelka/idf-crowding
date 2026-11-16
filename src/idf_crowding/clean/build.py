"""Build the harmonized validation tables from data/raw (Phase 2).

    idf-clean extract   one parquet per raw source file (cached; re-runs only new files)
    idf-clean combine   dedupe overlapping sources, write interim + processed tables
    idf-clean quality   data-quality flags and report
    idf-clean all       the three steps

Outputs (all rebuilt from data/raw):
    data/interim/validations/{nb,profil}/<period>__<source>.parquet
    data/interim/validations_daily_tickets.parquet   station x date x ticket category
    data/interim/validations_profiles.parquet        station x period x day type x hour
    data/interim/station_map.parquet                 operator stop code -> station id
    data/processed/station_daily.parquet             station x date -> n_entries
    data/processed/station_profiles.parquet          station x period x day type x hour
    data/processed/stations.parquet                  one row per counting point (ZdC)
    data/processed/quality/...                       see clean/quality.py
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from idf_crowding.clean.validations import (
    Period,
    file_kind,
    harmonize_daily,
    harmonize_profile,
    parse_period,
    read_table,
)
from idf_crowding.config import load_config

# Masked rows ("Moins de 5": 1-4, or "5" meaning 1-5) count as this many entries in totals.
MASKED_IMPUTE = 3

# Lower = preferred when two sources cover the same dates.
PRIORITY = {"history": 0, "quarterly": 1}


@dataclass(frozen=True)
class Source:
    kind: str  # "NB" | "PROFIL"
    period: Period
    name: str  # unique, e.g. "history/data-rf-2024/2024_T3_NB_FER.txt"
    origin: str  # key of PRIORITY
    read: Callable[[], bytes]

    @property
    def slug(self) -> str:
        return re.sub(r"[^A-Za-z0-9]+", "_", self.name).strip("_")

    @property
    def filename(self) -> str:
        return f"{self.period.label}__{self.slug}.parquet"


@dataclass(frozen=True)
class Paths:
    raw: Path
    interim: Path
    processed: Path

    @classmethod
    def from_config(cls) -> Paths:
        data = Path(load_config()["paths"]["data_dir"])
        return cls(data / "raw", data / "interim", data / "processed")


def _zip_reader(zip_path: Path, member: str) -> Callable[[], bytes]:
    def read() -> bytes:
        with zipfile.ZipFile(zip_path) as zf:
            return zf.read(member)

    return read


def discover(raw: Path) -> Iterator[Source]:
    """All NB/PROFIL files: members of the yearly zips, then the rolling quarterly CSVs.

    Nested zips (the 2020 archive contains copies of 2015-2019) and folders are skipped.
    """
    for zip_path in sorted((raw / "idfm/validations_history").glob("*/*.zip")):
        with zipfile.ZipFile(zip_path) as zf:
            members = [i.filename for i in zf.infolist()]
        for member in members:
            if member.endswith("/") or member.lower().endswith(".zip"):
                continue
            kind = file_kind(Path(member).name)
            if kind is None:
                continue
            yield Source(
                kind,
                parse_period(Path(member).name),
                f"history/{member}",
                "history",
                _zip_reader(zip_path, member),
            )
    for csv in sorted((raw / "idfm/validations_quarterly").glob("*/*.csv")):
        kind = file_kind(csv.parent.name)
        if kind is None:
            continue
        yield Source(
            kind,
            parse_period(csv.name),
            f"quarterly/{csv.parent.name}/{csv.name}",
            "quarterly",
            csv.read_bytes,
        )


def extract(paths: Paths, force: bool = False, log: Callable[[str], None] = print) -> list[Path]:
    """Harmonize each raw file once. `force` rewrites cached files (after a rule change)."""
    written = []
    for src in discover(paths.raw):
        out = paths.interim / "validations" / src.kind.lower() / src.filename
        if out.exists() and not force:
            continue
        log(f"extract {src.name}")
        df = read_table(src.read(), src.name)
        if src.kind == "NB":
            df = harmonize_daily(df, src.period, src.name)
        else:
            df = harmonize_profile(df, src.period, src.name)
        out.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(out)
        written.append(out)
    return written


def source_priority(source: pl.Expr) -> pl.Expr:
    return source.str.split("/").list.first().replace_strict(PRIORITY, return_dtype=pl.Int8)


def choose_sources_by_date(daily: pl.LazyFrame) -> pl.LazyFrame:
    """For each date, keep the rows of one source: lowest priority value, then name."""
    return (
        daily.select("date", "source")
        .unique()
        .with_columns(source_priority(pl.col("source")).alias("priority"))
        .sort("date", "priority", "source")
        .group_by("date", maintain_order=True)
        .first()
        .select("date", "source")
    )


def choose_sources_by_period(profiles: pl.LazyFrame) -> pl.LazyFrame:
    return (
        profiles.select("period", "source")
        .unique()
        .with_columns(source_priority(pl.col("source")).alias("priority"))
        .sort("period", "priority", "source")
        .group_by("period", maintain_order=True)
        .first()
        .select("period", "source")
    )


TRIPLE = ["code_trns", "code_res", "code_arret"]


def station_map(tickets: pl.LazyFrame, reference_ids: pl.Series | None = None) -> pl.LazyFrame:
    """Operator stop code (transporter, network, stop) -> current station id.

    The station id is a ZdC id (zones de correspondance). IDFM renumbered some ZdC over
    time (57 stop codes have two or more ids) and left it empty in some files (2015-2017,
    2024 T4, 2025 T2-T3, 2026), so each stop code takes the ZdC id of its most recent row,
    preferring ids that exist in the current stop reference (e.g. Orly airport: 63284,
    91479, 63278 over time; 91479 is not in the reference).
    """
    known = (
        pl.lit(False) if reference_ids is None else pl.col("zdc_id").is_in(reference_ids.implode())
    )
    return (
        tickets.filter(pl.col("zdc_id").is_not_null() & pl.col("code_arret").is_not_null())
        .group_by([*TRIPLE, "zdc_id"])
        .agg(pl.col("date").max().alias("last_seen"))
        .with_columns(known.alias("known"))
        .sort("known", "last_seen")
        .group_by(TRIPLE)
        .agg(pl.col("zdc_id").last().alias("station_id"))
    )


def assign_station(lf: pl.LazyFrame, mapping: pl.LazyFrame) -> pl.LazyFrame:
    """Add station_id: from the stop-code map, else the row's own ZdC id, else null."""
    return lf.join(mapping, on=TRIPLE, how="left", nulls_equal=False).with_columns(
        pl.coalesce("station_id", "zdc_id").alias("station_id")
    )


def station_daily(tickets: pl.LazyFrame) -> pl.LazyFrame:
    """station x date totals. Rows without a station id are dropped (counted in quality)."""
    exact = pl.when(pl.col("is_masked")).then(0).otherwise(pl.col("n_validations"))
    return (
        tickets.filter(pl.col("station_id").is_not_null() & pl.col("date").is_not_null())
        .group_by("station_id", "date")
        .agg(
            exact.sum().alias("n_exact"),
            pl.col("is_masked").sum().cast(pl.Int64).alias("n_masked_rows"),
            pl.col("period").first(),
        )
        .with_columns(
            (pl.col("n_exact") + MASKED_IMPUTE * pl.col("n_masked_rows")).alias("n_entries")
        )
        .sort("station_id", "date")
    )


def station_profiles(profiles: pl.LazyFrame, tickets: pl.LazyFrame) -> pl.LazyFrame:
    """Hourly share per station x period x day type.

    Profiles are published per operator stop code; a station with several stop codes gets
    their average weighted by each code's entries over the same period. Hour 'ND' (not
    determined, < 0.1 % of entries) is dropped and the remaining shares are rescaled to 1.
    """
    weights = (
        tickets.filter(pl.col("station_id").is_not_null())
        .group_by("period", *TRIPLE)
        .agg(pl.col("n_validations").sum().alias("w"))
    )
    p = (
        profiles.filter(pl.col("station_id").is_not_null() & pl.col("hour").is_not_null())
        .join(weights, on=["period", *TRIPLE], how="left")
        .with_columns(pl.col("w").fill_null(0))
    )
    return (
        p.group_by("period", "station_id", "day_type", "hour")
        .agg(
            ((pl.col("share") * pl.col("w")).sum() / pl.col("w").sum()).alias("wshare"),
            pl.col("share").mean().alias("mshare"),
            pl.col("w").sum().alias("w"),
            pl.struct(TRIPLE).n_unique().alias("n_stop_codes"),
        )
        .with_columns(pl.when(pl.col("w") > 0).then("wshare").otherwise("mshare").alias("share"))
        .with_columns(
            pl.col("share") / pl.col("share").sum().over("period", "station_id", "day_type")
        )
        .select("period", "station_id", "day_type", "hour", "share", "n_stop_codes")
        .sort("period", "station_id", "day_type", "hour")
    )


def latest_reference(raw: Path) -> pl.DataFrame | None:
    """Most recent snapshot of zones-de-correspondance (ZdC = validation station id)."""
    snaps = sorted((raw / "idfm/reference/zones-de-correspondance").glob("*.csv"))
    if not snaps:
        return None
    ref = pl.read_csv(snaps[-1], separator=";", infer_schema_length=0)
    return ref.select(
        pl.col("zdcid").cast(pl.Int64).alias("zdc_id"),
        pl.col("zdcname").alias("ref_name"),
        pl.col("zdctype").alias("ref_type"),
        pl.col("zdctown").alias("ref_town"),
        pl.col("zdcxepsg2154").cast(pl.Int64).alias("x_epsg2154"),
        pl.col("zdcyepsg2154").cast(pl.Int64).alias("y_epsg2154"),
    )


def stations(tickets: pl.LazyFrame, raw: Path) -> pl.DataFrame:
    st = (
        tickets.filter(pl.col("station_id").is_not_null())
        .sort("date")
        .group_by("station_id")
        .agg(
            pl.col("station_label").drop_nulls().last().alias("label"),
            pl.col("station_label").drop_nulls().unique().sort().alias("labels"),
            pl.col("zdc_id").drop_nulls().unique().sort().alias("zdc_ids_seen"),
            pl.struct(TRIPLE).unique().alias("stop_codes"),
            pl.col("date").min().alias("first_date"),
            pl.col("date").max().alias("last_date"),
            pl.col("date").n_unique().alias("n_days"),
        )
        .collect()
    )
    ref = latest_reference(raw)
    if ref is not None:
        st = st.join(ref.rename({"zdc_id": "station_id"}), on="station_id", how="left")
        return st.with_columns(pl.col("ref_name").is_not_null().alias("in_reference")).sort(
            "station_id"
        )
    st = st.with_columns(pl.lit(False).alias("in_reference"))
    return st.sort("station_id")


def combine(paths: Paths, log: Callable[[str], None] = print) -> None:
    nb = pl.scan_parquet(paths.interim / "validations/nb/*.parquet")
    chosen = choose_sources_by_date(nb)
    tickets_path = paths.interim / "validations_daily_tickets.parquet"
    log(f"write {tickets_path.name}")
    nb.join(chosen, on=["date", "source"], how="semi").sink_parquet(tickets_path)

    prof = pl.scan_parquet(paths.interim / "validations/profil/*.parquet")
    profiles_path = paths.interim / "validations_profiles.parquet"
    log(f"write {profiles_path.name}")
    prof.join(choose_sources_by_period(prof), on=["period", "source"], how="semi").sink_parquet(
        profiles_path
    )

    paths.processed.mkdir(parents=True, exist_ok=True)
    ref = latest_reference(paths.raw)
    ref_ids = None if ref is None else ref["zdc_id"]
    mapping = station_map(pl.scan_parquet(tickets_path), ref_ids).collect()
    mapping.write_parquet(paths.interim / "station_map.parquet")
    tickets = assign_station(pl.scan_parquet(tickets_path), mapping.lazy())
    log("write station_daily.parquet")
    station_daily(tickets).sink_parquet(paths.processed / "station_daily.parquet")
    log("write station_profiles.parquet")
    profiles = assign_station(pl.scan_parquet(profiles_path), mapping.lazy())
    station_profiles(profiles, tickets).sink_parquet(paths.processed / "station_profiles.parquet")
    log("write stations.parquet")
    stations(tickets, paths.raw).write_parquet(paths.processed / "stations.parquet")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="idf-clean", description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["extract", "combine", "quality", "all"])
    parser.add_argument("--force", action="store_true", help="re-extract cached files")
    args = parser.parse_args(argv)
    paths = Paths.from_config()
    if args.command in ("extract", "all"):
        n = len(extract(paths, force=args.force))
        print(f"extract: {n} new files")
    if args.command in ("combine", "all"):
        combine(paths)
    if args.command in ("quality", "all"):
        from idf_crowding.clean.quality import run as run_quality

        run_quality(paths)
    return 0


if __name__ == "__main__":
    sys.exit(main())
