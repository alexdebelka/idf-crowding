from datetime import date, timedelta

import polars as pl
import pytest

from idf_crowding.models import growth


def feats(start, end, level, stations=(1, 2), holiday=None):
    """Daily rows: n_entries = level(date, station)."""
    rows = []
    d = start
    while d < end:
        for s in stations:
            v = level(d, s)
            if v is not None:
                rows.append(
                    {
                        "station_id": s,
                        "date": d,
                        "n_entries": v,
                        "quality_flag": None,
                        "is_public_holiday": d == holiday,
                    }
                )
        d += timedelta(days=1)
    return pl.DataFrame(rows, schema_overrides={"quality_flag": pl.String})


def test_growth_rates_per_weekday_class():
    c = date(2026, 1, 1)

    # weekdays flat, weekends +20 % from 2025 on
    def lvl(d, s):
        weekend = d.weekday() >= 5
        return 100 * (1.2 if weekend and d.year >= 2025 else 1.0)

    g = growth.growth_rates(feats(date(2024, 1, 1), c, lvl), c, 182)
    r = dict(g.iter_rows())
    assert r["wk"] == pytest.approx(1.0)
    assert r["sat"] == pytest.approx(1.2) and r["sun"] == pytest.approx(1.2)


def test_growth_uses_stations_in_both_windows_and_skips_holidays():
    c = date(2026, 1, 1)

    # station 2 opens in 2025 (not in the earlier window): must not count as growth
    def lvl(d, s):
        if s == 2 and d.year < 2025:
            return None
        return 1000.0 if (d == date(2025, 11, 11)) else 100.0

    g = growth.growth_rates(feats(date(2024, 1, 1), c, lvl, holiday=date(2025, 11, 11)), c, 182)
    assert dict(g.iter_rows())["wk"] == pytest.approx(1.0)


def test_growth_ignores_data_on_or_after_cutoff():
    c = date(2026, 1, 1)
    base = feats(date(2024, 1, 1), c, lambda d, s: 100.0)
    late = feats(c, date(2026, 3, 1), lambda d, s: 500.0)
    assert growth.growth_rates(pl.concat([base, late]), c).equals(growth.growth_rates(base, c))


def test_apply_factor_is_one_at_cutoff_and_compounds():
    c = date(2026, 1, 1)
    rates = pl.DataFrame({"cls": ["wk", "sat", "sun"], "g": [1.1, 1.1, 1.1]})
    rows = pl.DataFrame(
        {"station_id": [1, 1], "date": [c, c + timedelta(days=364)], "lgbm": [100.0, 100.0]}
    )
    out = growth.apply(rows, rates, c)
    assert out["growth"].to_list() == pytest.approx([1.0, 1.1])
    assert out["lgbm"].to_list() == pytest.approx([100.0, 110.0])
    assert out["lgbm_raw"].to_list() == [100.0, 100.0]


def test_apply_log_uses_each_origins_own_cutoff():
    # +10 % per year until 2024-07-01, flat afterwards
    t0, stop = date(2022, 6, 1), date(2024, 7, 1)

    def lvl(d, s):
        return 100.0 * 1.1 ** ((min(d, stop) - t0).days / 365)

    f = feats(t0, date(2026, 6, 1), lvl)
    log = pl.DataFrame(
        {
            "cutoff": [date(2024, 6, 1), date(2026, 5, 1)],
            "station_id": [1, 1],
            "date": [date(2024, 9, 1), date(2026, 8, 1)],
            "lgbm": [100.0, 100.0],
        }
    )
    out = growth.apply_log(log, f).sort("cutoff")
    early, late = out["growth"].to_list()
    assert early > 1.02  # growing in the year before its cutoff
    assert late == pytest.approx(1.0)  # flat in the year before its cutoff
