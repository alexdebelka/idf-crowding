"""One test per score rule (docs/data-quality.md "Score") + the JSON contract."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import polars as pl
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from idf_crowding.score import dated, export
from idf_crowding.score.build import Paths, build
from idf_crowding.score.places import PlaceOverride, assign, load_overrides
from idf_crowding.score.reference import (
    apply_aliases,
    in_scope,
    lambert93_to_wgs84,
    line_info_from,
    stop_lines_from,
)
from idf_crowding.score.typical import (
    OPERATING_HOURS,
    ScoreSettings,
    band_expr,
    best_slots,
    daily_levels,
    hourly_profiles,
    place_days,
    place_profiles,
    reference_levels,
    usable_days,
    window,
)

S = ScoreSettings()
SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"


def validator(name: str, version: int = 1) -> Draft202012Validator:
    files = ["place.v1", "index.v1", "place.v2", "accuracy.v1"]
    res = {
        f"{n}.schema.json": Resource.from_contents(
            json.loads((SCHEMAS / f"{n}.schema.json").read_text())
        )
        for n in files
    }
    reg = Registry().with_resources(
        [(k, v) for k, v in res.items()] + [(v.contents["$id"], v) for v in res.values()]
    )
    return Draft202012Validator(res[f"{name}.v{version}.schema.json"].contents, registry=reg)


def feat(rows):
    cols = ["station_id", "date", "n_entries", "quality_flag", "day_type", "network_ratio"]
    df = pl.DataFrame(rows, schema=cols, orient="row")
    return df.with_columns(
        pl.lit(False).alias("is_public_holiday"), pl.lit(False).alias("is_bridge")
    )


D = date(2026, 6, 1)


def test_window_is_last_n_days_with_data():
    f = feat([(1, D, 10, None, "JOHV", 1.0), (1, D + timedelta(5), None, "missing", None, 1.0)])
    assert window(f, 365) == (D - timedelta(364), D)


def test_usable_days_rules():
    f = feat(
        [
            (1, D, 10, None, "JOHV", 1.0),  # kept
            (1, D + timedelta(1), 10, "low", "JOHV", 1.0),  # flagged
            (1, D + timedelta(2), 10, None, "JOHV", 0.5),  # strike / abnormal network
            (1, D + timedelta(3), 10, None, "DIJFP", 0.5),  # low but not a JOHV/SAHV day
            (1, D + timedelta(4), 10, None, None, 1.0),  # no day type
            (1, D - timedelta(400), 10, None, "JOHV", 1.0),  # outside the window
        ]
    )
    u = usable_days(f, S, D - timedelta(364), D + timedelta(4))
    assert sorted(u["date"].to_list()) == [D, D + timedelta(3)]


def test_daily_level_mean_and_low_confidence():
    days = pl.DataFrame(
        {
            "place_id": ["a"] * 9 + ["b"] * 2,
            "day_type": ["JOHV"] * 11,
            "n_entries": [10] * 9 + [1, 3],
        }
    )
    lv = {r["place_id"]: r for r in daily_levels(days, "place_id", 8).iter_rows(named=True)}
    assert lv["a"]["daily_entries"] == 10 and not lv["a"]["low_confidence"]
    assert lv["b"]["daily_entries"] == 2 and lv["b"]["n_days"] == 2 and lv["b"]["low_confidence"]


def test_hourly_profile_mean_of_quarters_missing_hours_zero_sums_to_one():
    p = pl.DataFrame(
        {
            "period": ["2025Q4", "2025Q4", "2026Q1", "2024Q1"],
            "station_id": [1, 1, 1, 1],
            "day_type": ["JOHV"] * 4,
            "hour": pl.Series([8, 9, 8, 8], dtype=pl.Int8),
            "share": [0.5, 0.5, 1.0, 1.0],
        }
    )
    prof = hourly_profiles(p, ["2025Q4", "2026Q1"])
    sh = dict(zip(prof["hour"].to_list(), prof["share"].to_list(), strict=True))
    assert sh[8] == pytest.approx(0.75) and sh[9] == pytest.approx(0.25)
    assert sum(sh.values()) == pytest.approx(1.0) and len(sh) == 24


def test_place_days_sum_only_when_all_members_usable():
    members = pl.DataFrame({"place_id": ["p", "p"], "station_id": [1, 2]})
    days = pl.DataFrame(
        {
            "station_id": [1, 2, 1],
            "date": [D, D, D + timedelta(1)],
            "day_type": ["JOHV"] * 3,
            "n_entries": [10, 5, 10],
            "is_holiday": [False] * 3,
        }
    )
    pd_ = place_days(days, members)
    assert pd_["date"].to_list() == [D] and pd_["n_entries"].to_list() == [15]


def test_place_profile_weighted_by_member_level():
    members = pl.DataFrame({"place_id": ["p", "p"], "station_id": [1, 2]})
    prof = pl.DataFrame(
        {"station_id": [1, 2], "day_type": ["JOHV"] * 2, "hour": [8, 9], "share": [1.0, 1.0]}
    )
    lv = pl.DataFrame({"station_id": [1, 2], "day_type": ["JOHV"] * 2, "daily_entries": [30, 10]})
    pp = place_profiles(prof, lv, members)
    sh = dict(zip(pp["hour"].to_list(), pp["share"].to_list(), strict=True))
    assert sh == {8: pytest.approx(0.75), 9: pytest.approx(0.25)}


def test_reference_level_quantile_on_actual_days_without_holidays():
    prof = pl.DataFrame(
        {"place_id": ["p", "p"], "day_type": ["JOHV"] * 2, "hour": [8, 9], "share": [0.5, 0.5]}
    )
    days = pl.DataFrame(
        {
            "place_id": ["p", "p", "p"],
            "date": [D, D + timedelta(1), D + timedelta(2)],
            "day_type": ["JOHV"] * 3,
            "n_entries": [100, 200, 10_000],
            "is_holiday": [False, False, True],
        }
    )
    ref = reference_levels(days, prof, 1.0)  # max of hourly values: 200 x 0.5
    assert ref["reference_level"].to_list() == [100.0]


def test_bands_thresholds():
    s = pl.DataFrame({"score": [0.0, 39.9, 40.0, 69.9, 70.0, 99.9, 100.0, 250.0]})
    got = s.select(band_expr(pl.col("score"), S.bands))["literal"].to_list()
    assert got == ["quiet"] * 2 + ["moderate"] * 2 + ["busy"] * 2 + ["very_busy"] * 2


def test_bands_from_config():
    s = ScoreSettings.from_config({"bands": {"quiet": 30, "moderate": 60, "busy": 90}})
    assert s.bands == ((30.0, "quiet"), (60.0, "moderate"), (90.0, "busy"))


def test_best_slots_quietest_and_around_peaks():
    exp = {h: 1.0 for h in range(24)}
    exp.update({5: 0.0, 6: 2, 7: 8, 8: 10, 9: 6, 10: 3, 17: 9, 18: 12, 19: 7, 20: 5, 21: 1.5})
    bs = best_slots(exp, S)
    assert bs["quietest"] == [11, 12, 13]  # 05:00 is outside 06-22
    assert bs["around_peaks"] == [{"peak": 8, "alternative": 6}, {"peak": 18, "alternative": 16}]


def test_place_overrides_and_assign(tmp_path):
    f = tmp_path / "places.toml"
    f.write_text('[[place]]\nid = "hub"\nname = "Hub"\nstation_ids = [1, 2]\n')
    ov = load_overrides(f)
    a = assign([1, 2, 3], ov)
    assert dict(zip(a["station_id"], a["place_id"], strict=True)) == {1: "hub", 2: "hub", 3: "3"}
    assert load_overrides(tmp_path / "none.toml") == []
    with pytest.raises(ValueError, match="in places"):
        assign([1], [PlaceOverride("a", "A", (1, 2)), PlaceOverride("b", "B", (1, 3))])
    f.write_text('[[place]]\nid = "Bad Id"\nname = "x"\nstation_ids = [1, 2]\n')
    with pytest.raises(ValueError, match="place id"):
        load_overrides(f)


def test_stop_lines_maps_quay_and_zda_ids_to_zdc():
    al = pl.DataFrame(
        {
            "id": ["IDFM:C01727", "IDFM:C01371"],
            "stop_id": ["IDFM:monomodalStopPlace:500", "IDFM:900"],
            "mode": ["RapidTransit", "Metro"],
        }
    )
    zda = pl.DataFrame({"zdaid": [500, 501], "zdcid": [71264, 71264]})
    arr = pl.DataFrame({"arrid": [900], "zda_of_arr": [501]})
    sl = stop_lines_from(al, zda, arr)
    assert sl.rows() == [(71264, "C01371", "Metro"), (71264, "C01727", "RapidTransit")]


def test_scope_modes_and_extra_lines():
    sl = pl.DataFrame(
        {
            "station_id": [1, 2, 3, 4],
            "line_id": ["C01371", "C01740", "C01843", "C01390"],
            "mode": ["Metro", "LocalTrain", "Tramway", "Tramway"],
        }
    )
    assert in_scope(sl, ["Metro", "RapidTransit"], ["C01843"]).to_list() == [1, 3]


def test_zdc_aliases_move_lines_to_data_zdc():
    sl = pl.DataFrame(
        {
            "station_id": [474151, 71264],
            "line_id": ["C01742", "C01371"],
            "mode": ["RapidTransit", "Metro"],
        }
    )
    out = apply_aliases(sl, {474151: 71264})
    assert out["station_id"].to_list() == [71264, 71264]
    s = ScoreSettings.from_config({"zdc_aliases": [{"from": 1, "to": 2, "name": "X"}]})
    assert s.zdc_aliases == ((1, 2, "X"),)


def test_line_info_kinds_and_active_only():
    ref = pl.DataFrame(
        {
            "id_line": ["C01371", "C01742", "C01740", "C01843", "C01748", "C02833"],
            "shortname_line": ["1", "A", "L", "T4", "TER", "18"],
            "transportmode": ["metro", "rail", "rail", "tram", "rail", "metro"],
            "networkname": [None, "RER", "Transilien", None, "TER", None],
            "colourweb_hexa": ["FFBE00"] * 6,
            "textcolourweb_hexa": ["000000"] * 6,
            "status": ["active"] * 5 + ["prochainement active"],
        }
    )
    li = line_info_from(ref)
    assert li["kind"].to_list() == ["metro", "rer", "transilien", "tram"]
    assert li["color"][0] == "#ffbe00"


def test_lambert93_to_wgs84_matches_reference_geopoint():
    # arrets.csv row: x/y EPSG:2154 and the portal's own geopoint (lat, lon)
    lat, lon = lambert93_to_wgs84(661869, 6879188)
    assert lat == pytest.approx(49.01146877700828, abs=1e-7)
    assert lon == pytest.approx(2.4787650478995347, abs=1e-7)


# ---- end to end: tiny processed + raw fixture -> JSON valid against the schemas ----


def write_fixture(tmp: Path) -> Paths:
    processed, raw = tmp / "processed", tmp / "raw"
    processed.mkdir()
    start = date(2026, 1, 5)  # Monday
    rows = []
    for i in range(70):
        d = start + timedelta(i)
        wd = d.isoweekday()
        dt = "DIJFP" if wd == 7 else ("SAHV" if wd == 6 else "JOHV")
        for sid, base in [(71264, 1000), (60001, 50)]:
            rows.append((sid, d, base * (1 if wd < 6 else 0.5), None, dt, 1.0))
    f = feat(rows).with_columns(pl.col("n_entries").cast(pl.Int64))
    f.write_parquet(processed / "features_daily.parquet")
    prof = []
    for q in ["2025Q3", "2025Q4", "2026Q1", "2026Q2"]:
        for sid in (71264, 60001):
            for dt in ("JOHV", "SAHV", "DIJFP"):
                for h in range(24):
                    share = 0.1 if h in (8, 18) else 0.8 / 22
                    prof.append((q, sid, dt, h, share, 1))
    pl.DataFrame(
        prof,
        schema={
            "period": pl.String,
            "station_id": pl.Int64,
            "day_type": pl.String,
            "hour": pl.Int8,
            "share": pl.Float64,
            "n_stop_codes": pl.UInt32,
        },
        orient="row",
    ).write_parquet(processed / "station_profiles.parquet")
    pl.DataFrame(
        {
            "station_id": [71264, 60001],
            "label": ["CHATELET", "SOMEWHERE"],
            "ref_name": ["Châtelet", "Somewhere"],
            "ref_town": ["Paris 1er", "Ailleurs"],
            "x_epsg2154": [651500, 600000],
            "y_epsg2154": [6862000, 6850000],
        }
    ).write_parquet(processed / "stations.parquet")
    ref = raw / "idfm/reference"
    files = {
        "arrets-lignes": "id;route_long_name;stop_id;stop_name;operatorname;shortname;mode\n"
        "IDFM:C01371;1;IDFM:900;Châtelet;RATP;1;Metro\n"
        "IDFM:C01740;L;IDFM:monomodalStopPlace:777;Somewhere;SNCF;L;LocalTrain\n",
        "zones-d-arrets": "zdaid;zdcid\n501;71264\n777;60001\n",
        "arrets": "arrid;zdaid\n900;501\n",
        "referentiel-des-lignes": "id_line;shortname_line;transportmode;networkname;"
        "colourweb_hexa;textcolourweb_hexa;status\n"
        "C01371;1;metro;;ffbe00;000000;active\nC01740;L;rail;Transilien;c4a4cc;000000;active\n",
    }
    for ds, text in files.items():
        (ref / ds).mkdir(parents=True)
        (ref / ds / "2026-11-12.csv").write_text(text, encoding="utf-8")
    return Paths(raw, processed, tmp / "app_data", None)


def test_build_end_to_end_writes_valid_json(tmp_path):
    paths = write_fixture(tmp_path)
    now = datetime(2026, 11, 12, tzinfo=UTC)
    records = build(paths, S, log=lambda _: None, now=now)
    assert [r["place"]["id"] for r in records] == ["71264"]  # Transilien-only station hidden
    place = json.loads((paths.app_data / "places/71264.json").read_text())
    index = json.loads((paths.app_data / "index.json").read_text())
    validator("place").validate(place)
    validator("index").validate(index)
    johv = place["day_types"]["JOHV"]
    assert [h["h"] for h in johv["hours"]][:2] == [4, 5] and len(johv["hours"]) == 24
    peak = max(johv["hours"], key=lambda h: h["score"])
    assert peak["h"] in (8, 18) and peak["band"] == "very_busy"
    assert place["place"]["lines"][0]["name"] == "1"
    assert 48.8 < place["place"]["lat"] < 48.9
    assert len(json.dumps(place)) < 20_000
    assert (tmp_path / "processed/typical_week.parquet").is_file()


def test_schema_rejects_unknown_band():
    bad = {
        "schema_version": 1,
        "generated_at": "2026-11-12T00:00:00+00:00",
        "data_period": {"start": "2025-07-01", "end": "2026-06-30"},
        "place": {"id": "1", "name": "x", "station_ids": [1], "lines": []},
        "reference_level": 1,
        "day_types": {
            "JOHV": {
                "hours": [
                    {"h": h, "expected_entries": 0, "score": 0, "band": "packed"} for h in range(24)
                ],
                "daily_entries": 0,
                "n_days": 1,
                "low_confidence": True,
                "best_slots": {"quietest": [], "around_peaks": []},
            }
        },
        "attribution": export.ATTRIBUTION,
    }
    assert not validator("place").is_valid(bad)


# --- Date forecasts (place.v2, docs/data-quality.md "Date forecasts in the app") ---


def fc_rows(rows):
    cols = ["station_id", "date", "point", "lo", "hi", "day_type", "special_day"]
    return pl.DataFrame(rows, schema=cols, orient="row").with_columns(
        pl.col("point", "lo", "hi").cast(pl.Float64),
        pl.col("special_day").cast(pl.String),
        pl.lit(date(2026, 11, 18)).alias("issue_date"),
        pl.lit(date(2026, 3, 15)).alias("data_end"),
    )


F = date(2026, 12, 24)  # Thursday


def test_place_daily_sums_members_and_needs_all_of_them():
    members = assign([1, 2, 3], [PlaceOverride("hub", "Hub", (1, 2))])
    fc = fc_rows(
        [
            (1, F, 100, 80, 120, "JOVS", None),
            (2, F, 50, 40, 60, "JOVS", None),
            (1, F + timedelta(1), 100, 80, 120, "DIJFP", None),  # member 2 missing
            (3, F, 10, 8, 12, "JOVS", None),
            (3, F + timedelta(1), 10, 8, 12, None, None),  # no day type
        ]
    )
    out = dated.place_daily(fc, members)
    assert out.select("place_id", "date", "point").rows() == [("3", F, 10.0), ("hub", F, 150.0)]


def test_place_daily_band_only_for_single_station_places():
    # Summing member bands overstates the width: merged Places get no band until it is
    # computed on the summed forecast.
    members = assign([1, 2, 3], [PlaceOverride("hub", "Hub", (1, 2))])
    fc = fc_rows(
        [
            (1, F, 100, 80, 120, "JOVS", None),
            (2, F, 50, 40, 60, "JOVS", None),
            (3, F, 10, 8, 12, "JOVS", None),
        ]
    )
    out = {r["place_id"]: r for r in dated.place_daily(fc, members).to_dicts()}
    assert (out["3"]["lo"], out["3"]["hi"]) == (8.0, 12.0)
    assert (out["hub"]["lo"], out["hub"]["hi"]) == (None, None)


def test_calendar_reasons_from_holiday_sources():
    hol = pl.DataFrame({"date": [date(2026, 12, 25)]})
    r = dated.calendar_reasons(pl.Series([F, F + timedelta(1)]), hol, None)
    assert r == {F: [], F + timedelta(1): ["public_holiday"]}


def test_date_records_score_delta_reasons_and_past_dates():
    daily = dated.place_daily(
        fc_rows(
            [
                (1, F - timedelta(1), 900, 800, 1000, "JOVS", None),  # before today
                (1, F, 1200, 1000, 1500.4, "JOVS", "christmas_eve"),
                (1, F + timedelta(2), 500, 400, 600, "SAVS", None),  # no SAVS profile
            ]
        ),
        assign([1], []),
    )
    hourly = pl.DataFrame(
        {"place_id": ["1", "1"], "day_type": ["JOVS", "JOVS"], "hour": [8, 18], "share": [0.6, 0.4]}
    )
    levels = pl.DataFrame({"place_id": ["1"], "day_type": ["JOVS"], "daily_entries": [1000.0]})
    refs = pl.DataFrame({"place_id": ["1"], "reference_level": [400.0]})
    out = dated.date_records(daily, hourly, levels, refs, {F: ["school_holidays"]}, F)
    (rec,) = out["1"]
    assert rec["d"] == "2026-12-24" and rec["day_type"] == "JOVS"
    assert (rec["daily"], rec["lo"], rec["hi"], rec["delta_pct"]) == (1200, 1000, 1500, 20)
    by_hour = dict(zip(OPERATING_HOURS, rec["scores"], strict=True))
    assert by_hour[8] == 180 and by_hour[18] == 120 and sum(rec["scores"]) == 300
    assert rec["reasons"] == ["christmas_eve", "school_holidays"]


def write_forecast(paths: Paths, n_days: int = 85) -> date:
    """forecast.parquet for the fixture's cutoff (data ends 2026-03-15)."""
    start = date(2026, 11, 18)
    rows = []
    for i in range(n_days):
        d = start + timedelta(i)
        wd = d.isoweekday()
        dt = "DIJFP" if wd == 7 else ("SAHV" if wd == 6 else "JOHV")
        special = "christmas_day" if (d.month, d.day) == (12, 25) else None
        for sid, base in [(71264, 1100), (60001, 55)]:
            rows.append((sid, d, base, base * 0.9, base * 1.1, dt, special))
    out = paths.processed / "forecast" / "2026-03-16"
    out.mkdir(parents=True)
    fc_rows(rows).write_parquet(out / "forecast.parquet")
    return start


def test_build_with_forecast_writes_valid_v2(tmp_path):
    paths = write_fixture(tmp_path)
    start = write_forecast(paths)
    now = datetime(2026, 11, 20, 8, tzinfo=UTC)
    build(paths, S, log=lambda _: None, now=now)
    place = json.loads((paths.app_data / "places/71264.json").read_text())
    validator("place", 2).validate(place)
    validator("index").validate(json.loads((paths.app_data / "index.json").read_text()))
    fc = place["forecast"]
    assert (fc["issue_date"], fc["data_end"]) == ("2026-11-18", "2026-03-15")
    dates = fc["dates"]
    assert dates[0]["d"] == "2026-11-20" and len(dates) == 85 - (date(2026, 11, 20) - start).days
    first = dates[0]  # Friday, JOHV: typical level 1000 -> +10 %, same profile as v1
    assert first["delta_pct"] == 10 and (first["lo"], first["hi"]) == (990, 1210)
    typical = [h["score"] for h in place["day_types"]["JOHV"]["hours"]]
    assert first["scores"] == [
        round(1.1 * 100 * 1000 * sh / place["reference_level"])
        for sh in [0.1 if h in (8, 18) else 0.8 / 22 for h in OPERATING_HOURS]
    ]
    assert max(first["scores"]) > max(typical)
    xmas = next(d for d in dates if d["d"] == "2026-12-25")
    assert xmas["reasons"] == ["christmas_day"]
    assert len(json.dumps(place, separators=(",", ":"))) < 25_000


def test_build_without_forecast_stays_v1(tmp_path):
    paths = write_fixture(tmp_path)
    build(paths, S, log=lambda _: None, now=datetime(2026, 11, 20, tzinfo=UTC))
    place = json.loads((paths.app_data / "places/71264.json").read_text())
    assert place["schema_version"] == 1 and "forecast" not in place
    validator("place").validate(place)


def test_schema_v2_rejects_short_scores_and_unknown_reason(tmp_path):
    paths = write_fixture(tmp_path)
    write_forecast(paths, 5)
    build(paths, S, log=lambda _: None, now=datetime(2026, 11, 18, tzinfo=UTC))
    place = json.loads((paths.app_data / "places/71264.json").read_text())
    v = validator("place", 2)
    assert v.is_valid(place)
    place["forecast"]["dates"][0]["scores"].pop()
    assert not v.is_valid(place)
    place["forecast"]["dates"][0]["scores"].append(0)
    place["forecast"]["dates"][0]["reasons"] = ["rain"]
    assert not v.is_valid(place)


# --- Per-station accuracy (docs/data-quality.md "Per-station accuracy") ---


def write_backtest_log(paths: Paths, n_days: int = 200) -> None:
    """lag120_prod deep log: 71264 scored on n_days dates (10 % error), 60001 too."""
    o = date(2025, 6, 1)
    rows = [
        (o, sid, o + timedelta(i), y, y * 0.9, True)
        for i in range(n_days)
        for sid, y in [(71264, 1000.0), (60001, 50.0)]
    ]
    df = pl.DataFrame(
        rows,
        schema=["origin", "station_id", "date", "y", "ens_lgbm_tft_seedavg", "scored"],
        orient="row",
    )
    d = paths.processed / "backtest/variants/lag120_prod/deep"
    d.mkdir(parents=True)
    df.write_parquet(d / "predictions.parquet")


def test_build_writes_place_accuracy_and_summary(tmp_path):
    paths = write_fixture(tmp_path)
    write_forecast(paths)
    write_backtest_log(paths)
    build(paths, S, log=lambda _: None, now=datetime(2026, 11, 20, 8, tzinfo=UTC))
    place = json.loads((paths.app_data / "places/71264.json").read_text())
    validator("place", 2).validate(place)
    assert place["accuracy"] == {"wape_pct": 10.0, "n_days": 200}
    summary = json.loads((paths.app_data / "accuracy.json").read_text())
    validator("accuracy").validate(summary)
    # spread over the app's Places only (60001 is Transilien-only, out of scope)
    assert summary["places"]["n_places"] == 1 and summary["places"]["median_pct"] == 10.0


def test_build_place_accuracy_null_below_min_days(tmp_path):
    paths = write_fixture(tmp_path)
    write_forecast(paths)
    write_backtest_log(paths, n_days=179)
    build(paths, S, log=lambda _: None, now=datetime(2026, 11, 20, 8, tzinfo=UTC))
    place = json.loads((paths.app_data / "places/71264.json").read_text())
    assert "accuracy" in place and place["accuracy"] is None
    validator("place", 2).validate(place)


def test_build_without_backtest_log_has_no_accuracy(tmp_path):
    paths = write_fixture(tmp_path)
    write_forecast(paths)
    paths.app_data.mkdir(parents=True)
    (paths.app_data / "accuracy.json").write_text("{}")  # stale file from an earlier build
    build(paths, S, log=lambda _: None, now=datetime(2026, 11, 20, 8, tzinfo=UTC))
    place = json.loads((paths.app_data / "places/71264.json").read_text())
    assert place["schema_version"] == 2 and "accuracy" not in place
    assert not (paths.app_data / "accuracy.json").exists()


def test_build_v1_files_never_carry_accuracy(tmp_path):
    paths = write_fixture(tmp_path)
    write_backtest_log(paths)
    build(paths, S, log=lambda _: None, now=datetime(2026, 11, 20, tzinfo=UTC))
    place = json.loads((paths.app_data / "places/71264.json").read_text())
    assert place["schema_version"] == 1 and "accuracy" not in place
    validator("place").validate(place)
    assert (paths.app_data / "accuracy.json").is_file()
