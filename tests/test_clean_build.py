import io
import zipfile
from datetime import date, timedelta

import polars as pl
import pytest

from idf_crowding.clean import build, quality
from idf_crowding.clean.build import (
    MASKED_IMPUTE,
    Paths,
    assign_station,
    choose_sources_by_date,
    station_daily,
    station_map,
    station_profiles,
)


def test_choose_sources_prefers_yearly_archive_on_overlap():
    lf = pl.LazyFrame(
        {
            "date": [date(2025, 7, 1), date(2025, 7, 1), date(2026, 1, 1)],
            "source": ["quarterly/a.csv", "history/b.xlsx", "quarterly/c.csv"],
        }
    )
    out = choose_sources_by_date(lf).collect().sort("date")
    assert out["source"].to_list() == ["history/b.xlsx", "quarterly/c.csv"]


def tickets(rows):
    cols = ["date", "zdc_id", "code_trns", "code_res", "code_arret", "n_validations", "is_masked"]
    return pl.LazyFrame([dict(zip(cols, r, strict=True)) for r in rows]).with_columns(
        pl.lit("2025Q1").alias("period")
    )


def test_station_map_takes_latest_id_and_prefers_reference():
    d1, d2, d3 = date(2024, 1, 1), date(2025, 1, 1), date(2025, 7, 1)
    t = tickets(
        [
            (d1, 63284, 760, 760, 490909, 10, False),
            (d2, 91479, 760, 760, 490909, 10, False),  # newest, but not in reference
            (d1, 71379, 100, 110, 1, 10, False),
            (d3, 99, 100, 110, 1, 10, False),  # newest and in reference
        ]
    )
    ref = pl.Series([63284, 71379, 99])
    m = station_map(t, ref).collect().sort("code_arret")
    assert m["station_id"].to_list() == [99, 63284]


def test_assign_station_fills_missing_zdc_from_stop_code():
    t = tickets(
        [
            (date(2024, 1, 1), 71379, 100, 110, 1, 10, False),
            (date(2025, 1, 1), None, 100, 110, 1, 12, False),
            (date(2025, 1, 1), 555, None, None, None, 7, False),
        ]
    )
    out = assign_station(t, station_map(t)).collect().sort("date", "n_validations")
    assert out["station_id"].to_list() == [71379, 555, 71379]


def test_station_daily_sums_and_imputes_masked_rows():
    t = tickets(
        [
            (date(2025, 1, 1), 1, 100, 110, 1, 100, False),
            (date(2025, 1, 1), 1, 100, 110, 1, 5, True),
            (date(2025, 1, 1), 1, 800, 803, 2, None, True),
            (date(2025, 1, 1), None, 100, None, None, 50, False),
        ]
    )
    out = station_daily(t.with_columns(pl.col("zdc_id").alias("station_id"))).collect()
    assert out.height == 1
    assert out["n_exact"][0] == 100
    assert out["n_masked_rows"][0] == 2
    assert out["n_entries"][0] == 100 + 2 * MASKED_IMPUTE


def test_station_profiles_weights_stop_codes_by_entries():
    t = tickets(
        [
            (date(2025, 1, 1), 1, 100, 110, 1, 300, False),
            (date(2025, 1, 1), 1, 800, 803, 2, 100, False),
        ]
    ).with_columns(pl.col("zdc_id").alias("station_id"))
    prof = pl.LazyFrame(
        {
            "period": ["2025Q1"] * 5,
            "station_id": [1] * 5,
            "code_trns": [100, 100, 800, 800, 800],
            "code_res": [110, 110, 803, 803, 803],
            "code_arret": [1, 1, 2, 2, 2],
            "day_type": ["JOHV"] * 5,
            "hour": [8, 9, 8, 9, None],
            "share": [1.0, 0.0, 0.0, 0.98, 0.02],
        },
        schema_overrides={"hour": pl.Int8},
    )
    out = station_profiles(prof, t).collect().sort("hour")
    assert out["hour"].to_list() == [8, 9]
    assert out["share"].sum() == pytest.approx(1.0)
    # 3/4 of entries come from the stop code that is all at 8h
    assert out["share"][0] == pytest.approx(0.75 / (0.75 + 0.25 * 0.98))


def test_station_day_flags_missing_and_low():
    start = date(2025, 1, 6)  # Monday
    days = [start + timedelta(days=i) for i in range(7 * 12)]
    rows = []
    for d in days:
        rows.append({"station_id": 1, "date": d, "n_entries": 1000})
        if d != start + timedelta(weeks=6):
            rows.append({"station_id": 2, "date": d, "n_entries": 1000})
        # the rest of the network stays normal, so station 1's drop is station-specific
        rows += [{"station_id": k, "date": d, "n_entries": 1000} for k in range(3, 13)]
    daily = pl.DataFrame(rows)
    low_day = start + timedelta(weeks=5)
    daily = daily.with_columns(
        pl.when((pl.col("station_id") == 1) & (pl.col("date") == low_day))
        .then(10)
        .otherwise(pl.col("n_entries"))
        .alias("n_entries")
    )
    flags = quality.station_day_flags(daily)
    got = {(r["station_id"], r["date"], r["flag"]) for r in flags.iter_rows(named=True)}
    assert got == {(1, low_day, "low"), (2, start + timedelta(weeks=6), "missing")}


# ------------------------------------------------------------ end to end on a tiny fixture

NB_2024 = (
    "JOUR\tCODE_STIF_TRNS\tCODE_STIF_RES\tCODE_STIF_ARRET\tLIBELLE_ARRET\tID_ZDC\t"
    "CATEGORIE_TITRE\tNB_VALD\n"
    "01/07/24\t100\t110\t1\tPORTE MAILLOT\t71379\tForfait Navigo\t1 020\n"
    "01/07/24\t100\t110\t1\tPORTE MAILLOT\t71379\tAmethyste\t3\n"
)
PROFIL_2024 = (
    "CODE_STIF_TRNS;CODE_STIF_RES;CODE_STIF_ARRET;LIBELLE_ARRET;ID_ZDC;CAT_JOUR;TRNC_HORR_60;"
    "POURCENTAGE_VALIDATIONS\n"
    "100;110;1;PORTE MAILLOT;71379;JOHV;8H-9H;60\n"
    "100;110;1;PORTE MAILLOT;71379;JOHV;9H-10H;40\n"
)
NB_2025Q3 = (
    "jour;code_stif_trns;code_stif_res;code_stif_arret;id_zdc;libelle_arret;categorie_titre;"
    "nb_vald\n"
    "2025-07-01;100.0;110;1;;PORTE MAILLOT;Forfait Navigo;900.0\n"
)


def test_end_to_end_on_fixture(tmp_path):
    raw = tmp_path / "raw"
    hist = raw / "idfm/validations_history/histo-validations-reseau-ferre"
    hist.mkdir(parents=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("data-rf-2024/", "")
        zf.writestr("data-rf-2024/2024_T3_NB_FER.txt", NB_2024.encode("utf-8"))
        zf.writestr("data-rf-2024/2024_T3_PROFIL_FER.txt", PROFIL_2024.encode("cp1252"))
        zf.writestr("data-rf-2024/data-rf-2015.zip", b"nested copy, ignored")
    (hist / "data-rf-2024.zip").write_bytes(buf.getvalue())
    q = (
        raw
        / "idfm/validations_quarterly"
        / ("validations-reseau-ferre-nombre-validations-par-jour-3eme-trimestre")
    )
    q.mkdir(parents=True)
    (q / "2025Q3.csv").write_text(NB_2025Q3, encoding="utf-8")

    paths = Paths(raw, tmp_path / "interim", tmp_path / "processed")
    assert len(build.extract(paths, log=lambda _: None)) == 3
    assert build.extract(paths, log=lambda _: None) == []  # cached
    build.combine(paths, log=lambda _: None)
    quality.run(paths)

    daily = pl.read_parquet(paths.processed / "station_daily.parquet").sort("date")
    assert daily["station_id"].to_list() == [71379, 71379]  # 2025 row had no ZdC id
    assert daily["n_entries"].to_list() == [1023, 900]
    prof = pl.read_parquet(paths.processed / "station_profiles.parquet")
    assert prof["share"].to_list() == pytest.approx([0.6, 0.4])
    assert (paths.processed / "quality/report.md").exists()
