"""Harmonize IDFM rail validation files (NB_FER, PROFIL_FER) into one schema.

Every rule here exists because some raw file needs it; see docs/data-quality.md.
Functions are pure (bytes / DataFrame in, DataFrame out) so each rule has a test.
"""

from __future__ import annotations

import codecs
import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta

import polars as pl

# ---------------------------------------------------------------- sources and periods

PERIOD_RE = re.compile(r"(?<!\d)(\d{4})[ _]?([STQ])(\d)(?!\d)", re.IGNORECASE)


@dataclass(frozen=True)
class Period:
    """A publication period: half-year (S1/S2) or quarter (Q1-Q4; IDFM writes T1-T4)."""

    year: int
    kind: str  # "S" or "Q"
    n: int

    @property
    def label(self) -> str:
        return f"{self.year}{self.kind}{self.n}"

    @property
    def start(self) -> date:
        month = 1 + (self.n - 1) * (6 if self.kind == "S" else 3)
        return date(self.year, month, 1)

    @property
    def end(self) -> date:
        months = 6 if self.kind == "S" else 3
        m = self.start.month + months
        y = self.year + (m > 12)
        return date(y, (m - 1) % 12 + 1, 1) - timedelta(days=1)


def parse_period(name: str) -> Period:
    """'2017_S2_NB_FER.txt' -> 2017S2; '2024_T3_...' / '2025Q3.csv' -> 2024Q3 / 2025Q3."""
    matches = PERIOD_RE.findall(name)
    if not matches:
        raise ValueError(f"no period in file name: {name!r}")
    year, kind, n = matches[-1]
    kind = "S" if kind.upper() == "S" else "Q"
    return Period(int(year), kind, int(n))


def file_kind(name: str) -> str | None:
    """'NB' for daily counts, 'PROFIL' for hourly profiles, None for anything else."""
    upper = name.upper()
    if "PROFIL" in upper:
        return "PROFIL"
    if "NB_FER" in upper or "NOMBRE-VALIDATIONS" in upper:
        return "NB"
    return None


# ---------------------------------------------------------------- reading raw bytes


def decode(raw: bytes) -> str:
    """UTF-16 (2023 S2), UTF-8 with BOM (2022 S2), UTF-8, else cp1252 (2023 S1, 2024 S1)."""
    if raw[:2] in (codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE):
        return raw.decode("utf-16")
    if raw[:3] == codecs.BOM_UTF8:
        return raw[3:].decode("utf-8")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


def read_table(raw: bytes, name: str) -> pl.DataFrame:
    """Read one raw file into all-string columns. Handles csv/txt (';' or tab) and xlsx."""
    if name.lower().endswith(".xlsx"):
        df = pl.read_excel(io.BytesIO(raw), infer_schema_length=0)
    else:
        text = decode(raw)
        header = text.split("\n", 1)[0]
        sep = "\t" if "\t" in header else ";"
        df = pl.read_csv(
            text.encode("utf-8"),
            separator=sep,
            infer_schema_length=0,
            truncate_ragged_lines=True,
        )
    return df.with_columns(pl.all().cast(pl.Utf8))


# ---------------------------------------------------------------- column names

ALIASES = {
    "date": ["JOUR", "DATE"],
    "code_trns": ["CODE_STIF_TRNS", "COD_STIF_TRNS"],
    "code_res": ["CODE_STIF_RES", "COD_STIF_RES"],
    "code_arret": ["CODE_STIF_ARRET", "COD_STIF_ARRET"],
    "station_label": ["LIBELLE_ARRET"],
    "zdc_id": ["ID_REFA_LDA", "LDA", "ID_ZDC", "IDA"],
    "ticket_raw": ["CATEGORIE_TITRE"],
    "n_raw": ["NB_VALD"],
    "day_type": ["CAT_JOUR"],
    "slot": ["TRNC_HORR_60"],
    "share_raw": ["POURC_VALIDATIONS", "POURCENTAGE_VALIDATIONS"],
}
_LOOKUP = {alias: canon for canon, aliases in ALIASES.items() for alias in aliases}


def rename_columns(df: pl.DataFrame) -> pl.DataFrame:
    """Map every known raw header (any case, BOM, spaces) to one canonical name."""
    mapping = {}
    for col in df.columns:
        key = col.replace("﻿", "").strip().upper()
        if key not in _LOOKUP:
            raise ValueError(f"unknown column {col!r}")
        mapping[col] = _LOOKUP[key]
    if len(set(mapping.values())) != len(mapping):
        raise ValueError(f"two columns map to the same name: {mapping}")
    return df.rename(mapping)


# ---------------------------------------------------------------- value parsers


def parse_dates(col: pl.Expr) -> pl.Expr:
    """dd/mm/yyyy (2015-2024 S1, 2025 T2), dd/mm/yy (2024 T3), ISO (2024 T4, xlsx, API)."""
    s = col.str.strip_chars()
    iso = s.str.slice(0, 10).str.strptime(pl.Date, "%Y-%m-%d", strict=False)
    long_fr = s.str.strptime(pl.Date, "%d/%m/%Y", strict=False)
    short_fr = s.str.strptime(pl.Date, "%d/%m/%y", strict=False)
    return (
        pl.when(s.str.contains(r"^\d{4}-\d{2}-\d{2}"))
        .then(iso)
        .when(s.str.contains(r"^\d{2}/\d{2}/\d{4}$"))
        .then(long_fr)
        .when(s.str.contains(r"^\d{2}/\d{2}/\d{2}$"))
        .then(short_fr)
        .otherwise(None)
    )


def parse_int(col: pl.Expr) -> pl.Expr:
    """'  115', '1 020' (thousands space, 2024 T3), '71379.0' (float ids) -> Int64."""
    cleaned = col.str.replace_all(r"[\s  ]", "")
    return cleaned.cast(pl.Float64, strict=False).round(0).cast(pl.Int64)


LT5_TEXT = "moins de 5"


def mask_regime(n_raw: pl.Series) -> str:
    """How small counts are hidden in one file (see docs/data-quality.md).

    - 'lt5_text': 1-4 written as "Moins de 5" (2015 S1 - 2017 S1)
    - 'le5_as5':  no value below 5 and no text: 5 means "5 or fewer" (2017 S2 - 2023 S1)
    - 'none':     exact values down to 1 (2023 S2 onwards)
    """
    s = n_raw.str.strip_chars().str.to_lowercase()
    if (s == LT5_TEXT).any():
        return "lt5_text"
    values = s.str.replace_all(r"[\s  ]", "").cast(pl.Float64, strict=False)
    if ((values >= 1) & (values <= 4)).any():
        return "none"
    return "le5_as5"


def _ascii_upper(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().upper().strip()


# Two vocabularies: old (to 2023 S1) and new (from 2023 S2). Grouping is approximate:
# v0 only uses totals over all tickets.
TICKET_GROUPS = {
    "NAVIGO": "navigo",
    "FORFAIT NAVIGO": "navigo",
    "IMAGINE R": "imagine_r",
    "AMETHYSTE": "amethyste",
    "TST": "solidarity",
    "FGT": "solidarity",
    "CONTRAT SOLIDARITE TRANSPORT": "solidarity",
    "NAVIGO JOUR": "short_passes",
    "FORFAITS COURTS": "short_passes",
    "AUTRE TITRE": "other",
    "AUTRES TITRES": "other",
    "NON DEFINI": "undefined",
    "?": "undefined",
}


def ticket_group(raw: str | None) -> str:
    if raw is None:
        return "undefined"
    return TICKET_GROUPS.get(_ascii_upper(raw), "unknown")


def parse_slot(col: pl.Expr) -> pl.Expr:
    """'6H-7H' -> 6, '23H-0H' -> 23, 'ND' (not determined) -> null."""
    return col.str.strip_chars().str.extract(r"^(\d{1,2})H-", 1).cast(pl.Int8)


# ---------------------------------------------------------------- harmonize one file

DAILY_SCHEMA = {
    "date": pl.Date,
    "zdc_id": pl.Int64,
    "code_trns": pl.Int64,
    "code_res": pl.Int64,
    "code_arret": pl.Int64,
    "station_label": pl.Utf8,
    "ticket_raw": pl.Utf8,
    "ticket_group": pl.Utf8,
    "n_validations": pl.Int64,
    "is_masked": pl.Boolean,
    "mask_regime": pl.Utf8,
    "period": pl.Utf8,
    "source": pl.Utf8,
}

PROFILE_SCHEMA = {
    "period": pl.Utf8,
    "zdc_id": pl.Int64,
    "code_trns": pl.Int64,
    "code_res": pl.Int64,
    "code_arret": pl.Int64,
    "station_label": pl.Utf8,
    "day_type": pl.Utf8,
    "hour": pl.Int8,
    "share": pl.Float64,
    "source": pl.Utf8,
}

DAY_TYPES = {"JOHV", "SAHV", "JOVS", "SAVS", "DIJFP"}

# Seen as ZdC id on rows labelled "Inconnu" (0, 999999) or with no id yet (-1, Orly 2025 T4).
UNKNOWN_ZDC = {0, -1, 999999}


def _codes() -> list[pl.Expr]:
    """Integer codes. ZdC ids 0, -1 and 999999 are placeholders for an unknown id."""
    zdc = parse_int(pl.col("zdc_id"))
    return [
        pl.when(zdc.is_in(list(UNKNOWN_ZDC))).then(None).otherwise(zdc).alias("zdc_id"),
        *(parse_int(pl.col(c)).alias(c) for c in ("code_trns", "code_res", "code_arret")),
    ]


def harmonize_daily(df: pl.DataFrame, period: Period, source: str) -> pl.DataFrame:
    """Raw NB_FER table (string columns) -> DAILY_SCHEMA."""
    df = rename_columns(df)
    regime = mask_regime(df["n_raw"])
    n = parse_int(pl.col("n_raw"))
    text_mask = pl.col("n_raw").str.strip_chars().str.to_lowercase() == LT5_TEXT
    masked = text_mask if regime == "lt5_text" else (n == 5) & pl.lit(regime == "le5_as5")
    out = df.with_columns(
        parse_dates(pl.col("date")).alias("date"),
        *_codes(),
        pl.col("station_label").str.strip_chars(),
        pl.col("ticket_raw").str.strip_chars(),
        pl.col("ticket_raw")
        .map_elements(ticket_group, return_dtype=pl.Utf8, skip_nulls=False)
        .alias("ticket_group"),
        pl.when(text_mask).then(None).otherwise(n).alias("n_validations"),
        masked.fill_null(False).alias("is_masked"),
        pl.lit(regime).alias("mask_regime"),
        pl.lit(period.label).alias("period"),
        pl.lit(source).alias("source"),
    )
    return out.select([pl.col(c).cast(t) for c, t in DAILY_SCHEMA.items()])


def harmonize_profile(df: pl.DataFrame, period: Period, source: str) -> pl.DataFrame:
    """Raw PROFIL_FER table -> PROFILE_SCHEMA. Share is a fraction (0-1), not a percent."""
    df = rename_columns(df)
    out = df.with_columns(
        *_codes(),
        pl.col("station_label").str.strip_chars(),
        pl.col("day_type").str.strip_chars().str.to_uppercase(),
        parse_slot(pl.col("slot")).alias("hour"),
        (pl.col("share_raw").str.replace(",", ".").cast(pl.Float64, strict=False) / 100).alias(
            "share"
        ),
        pl.lit(period.label).alias("period"),
        pl.lit(source).alias("source"),
    )
    return out.select([pl.col(c).cast(t) for c, t in PROFILE_SCHEMA.items()])
