"""One test per harmonization rule (see docs/data-quality.md)."""

from datetime import date

import polars as pl
import pytest

from idf_crowding.clean.validations import (
    Period,
    decode,
    file_kind,
    harmonize_daily,
    harmonize_profile,
    mask_regime,
    parse_dates,
    parse_int,
    parse_period,
    parse_slot,
    read_table,
    rename_columns,
    ticket_group,
)


@pytest.mark.parametrize(
    ("name", "label"),
    [
        ("2015S1_NB_FER.csv", "2015S1"),
        ("2017_S2_NB_FER.txt", "2017S2"),
        ("2023_S1_NB_FER .txt", "2023S1"),
        ("2024_T3_NB_FER.txt", "2024Q3"),
        ("T1 FER/2025_T1_NB_FER.xlsx", "2025Q1"),
        ("2025Q3.csv", "2025Q3"),
    ],
)
def test_parse_period(name, label):
    assert parse_period(name).label == label


def test_period_bounds():
    assert (Period(2024, "S", 1).start, Period(2024, "S", 1).end) == (
        date(2024, 1, 1),
        date(2024, 6, 30),
    )
    assert Period(2025, "Q", 4).end == date(2025, 12, 31)


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("2018_S2_NB_Fer.txt", "NB"),
        ("2018_S2_Profil_Fer.txt", "PROFIL"),
        ("validations-reseau-ferre-nombre-validations-par-jour-1er-trimestre", "NB"),
        ("validations-reseau-ferre-profils-horaires-par-jour-type-1er-trimestre", "PROFIL"),
        ("data-rf-2015.zip", None),
    ],
)
def test_file_kind(name, kind):
    assert file_kind(name) == kind


def test_decode_handles_all_encodings_seen():
    text = "LIBELLE_ARRET\nSAINT-GERMAIN-DES-PRÉS\n"
    assert decode(text.encode("utf-16")) == text
    assert decode(b"\xef\xbb\xbf" + text.encode("utf-8")) == text
    assert decode(text.encode("utf-8")) == text
    assert decode(text.encode("cp1252")) == text


def test_read_table_detects_separator():
    tab = read_table(b"JOUR\tNB_VALD\n01/01/2016\t        115\n", "x.txt")
    semi = read_table(b"JOUR;NB_VALD\n01/01/2015;117\n", "x.csv")
    assert tab.columns == semi.columns == ["JOUR", "NB_VALD"]
    assert tab["NB_VALD"][0] == "        115"


def test_rename_columns_maps_every_alias():
    df = pl.DataFrame(
        {
            "﻿JOUR": ["x"],
            "lda": ["1"],
            "Pourcentage_validations": ["1"],
            "TRNC_HORR_60": ["x"],
        }
    )
    assert rename_columns(df).columns == ["date", "zdc_id", "share_raw", "slot"]
    for alias in ["ID_REFA_LDA", "ID_ZDC", "ida", "id_zdc"]:
        assert rename_columns(pl.DataFrame({alias: ["1"]})).columns == ["zdc_id"]


def test_rename_columns_rejects_unknown():
    with pytest.raises(ValueError):
        rename_columns(pl.DataFrame({"SOMETHING_NEW": ["1"]}))


def test_parse_dates_all_formats():
    s = pl.DataFrame(
        {"d": ["01/07/2015", "01/07/24", "2024-10-01", "2025-01-01 00:00:00", "", None]}
    )
    out = s.select(parse_dates(pl.col("d")))["d"].to_list()
    assert out == [date(2015, 7, 1), date(2024, 7, 1), date(2024, 10, 1), date(2025, 1, 1)] + [
        None,
        None,
    ]


def test_parse_int_strips_padding_thousands_and_floats():
    s = pl.DataFrame({"v": ["        115", "1 020", "1 053", "71379.0", "Moins de 5"]})
    assert s.select(parse_int(pl.col("v")))["v"].to_list() == [115, 1020, 1053, 71379, None]


@pytest.mark.parametrize(
    ("values", "regime"),
    [
        (["Moins de 5", "5", "40"], "lt5_text"),
        (["5", "5", "6", "120"], "le5_as5"),
        (["1", "4", "5", "120"], "none"),
        (["1.0", "5.0"], "none"),
    ],
)
def test_mask_regime(values, regime):
    assert mask_regime(pl.Series(values)) == regime


@pytest.mark.parametrize(
    ("raw", "group"),
    [
        ("NAVIGO", "navigo"),
        ("Forfait Navigo", "navigo"),
        ("Contrat Solidarité Transport", "solidarity"),
        ("Contrat Solidarite Transport", "solidarity"),
        ("FGT", "solidarity"),
        ("NAVIGO JOUR", "short_passes"),
        ("Forfaits courts", "short_passes"),
        ("Amethyste", "amethyste"),
        ("?", "undefined"),
        (None, "undefined"),
        ("Brand new ticket", "unknown"),
    ],
)
def test_ticket_group(raw, group):
    assert ticket_group(raw) == group


def test_parse_slot():
    s = pl.DataFrame({"s": ["0H-1H", "6H-7H", "23H-0H", "ND"]})
    assert s.select(parse_slot(pl.col("s")))["s"].to_list() == [0, 6, 23, None]


def nb_raw(values, zdc="71379"):
    n = len(values)
    return pl.DataFrame(
        {
            "JOUR": ["01/01/2018"] * n,
            "CODE_STIF_TRNS": ["100"] * n,
            "CODE_STIF_RES": ["110"] * n,
            "CODE_STIF_ARRET": ["1"] * n,
            "LIBELLE_ARRET": ["PORTE MAILLOT "] * n,
            "ID_REFA_LDA": [zdc] * n,
            "CATEGORIE_TITRE": ["NAVIGO"] * n,
            "NB_VALD": values,
        }
    )


P = Period(2018, "S", 1)


def test_harmonize_daily_text_mask():
    out = harmonize_daily(nb_raw(["Moins de 5", "5", "40"]), P, "src")
    assert out["n_validations"].to_list() == [None, 5, 40]
    assert out["is_masked"].to_list() == [True, False, False]
    assert out["station_label"][0] == "PORTE MAILLOT"


def test_harmonize_daily_five_means_five_or_fewer():
    out = harmonize_daily(nb_raw(["5", "6", "40"]), P, "src")
    assert out["n_validations"].to_list() == [5, 6, 40]
    assert out["is_masked"].to_list() == [True, False, False]


def test_harmonize_daily_exact_values():
    out = harmonize_daily(nb_raw(["1", "5", "40"]), P, "src")
    assert out["is_masked"].to_list() == [False, False, False]


@pytest.mark.parametrize("placeholder", ["0", "-1", "999999"])
def test_harmonize_daily_unknown_zdc_placeholders(placeholder):
    out = harmonize_daily(nb_raw(["10"], zdc=placeholder), P, "src")
    assert out["zdc_id"].to_list() == [None]


def test_harmonize_profile_share_is_fraction_and_nd_has_no_hour():
    raw = pl.DataFrame(
        {
            "CODE_STIF_TRNS": ["100.0", "100"],
            "CODE_STIF_RES": ["110", "110"],
            "CODE_STIF_ARRET": ["1", "1"],
            "LIBELLE_ARRET": ["X", "X"],
            "ID_ZDC": ["71379.0", "71379"],
            "CAT_JOUR": ["johv", "JOHV"],
            "TRNC_HORR_60": ["6H-7H", "ND"],
            "POURCENTAGE_VALIDATIONS": ["12,5", "0.01"],
        }
    )
    out = harmonize_profile(raw, Period(2025, "Q", 1), "src")
    assert out["share"].to_list() == pytest.approx([0.125, 0.0001])
    assert out["hour"].to_list() == [6, None]
    assert out["day_type"].to_list() == ["JOHV", "JOHV"]
    assert out["code_trns"].to_list() == [100, 100]
