"""Write the app's JSON contract (schemas/*.v1.schema.json): index.json + places/<id>.json."""

from __future__ import annotations

import json
import warnings
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from idf_crowding.score.typical import DAY_TYPES, OPERATING_HOURS, ScoreSettings, best_slots

SCHEMA_VERSION = 1
ATTRIBUTION = {
    "source": "Île-de-France Mobilités",
    "source_url": "https://data.iledefrance-mobilites.fr",
    "license": "ODbL",
    "license_url": "https://opendatacommons.org/licenses/odbl/1-0/",
}


def day_type_record(rows: pl.DataFrame, level: dict[str, Any], s: ScoreSettings) -> dict:
    by_hour = {int(r["hour"]): r for r in rows.iter_rows(named=True)}
    hours = []
    for h in OPERATING_HOURS:
        r = by_hour.get(h)
        exp = 0.0 if r is None else float(r["expected_entries"])
        score = 0.0 if r is None else float(r["score"])
        band = "quiet" if r is None else r["band"]
        hours.append({"h": h, "expected_entries": round(exp), "score": round(score), "band": band})
    expected = {h: float(by_hour[h]["expected_entries"]) for h in by_hour}
    return {
        "hours": hours,
        "daily_entries": round(level["daily_entries"]),
        "n_days": int(level["n_days"]),
        "low_confidence": bool(level["low_confidence"]),
        "best_slots": best_slots(expected, s),
    }


def place_records(
    hourly: pl.DataFrame,
    levels: pl.DataFrame,
    refs: pl.DataFrame,
    meta: dict[str, dict[str, Any]],
    s: ScoreSettings,
    period: tuple[date, date],
    profile_periods: list[str],
    generated_at: datetime,
) -> list[dict[str, Any]]:
    lv = {(r["place_id"], r["day_type"]): r for r in levels.iter_rows(named=True)}
    ref = dict(zip(refs["place_id"], refs["reference_level"], strict=True))
    out = []
    for (pid,), grp in hourly.sort("place_id").group_by("place_id", maintain_order=True):
        day_types = {}
        for dt in DAY_TYPES:
            rows = grp.filter(pl.col("day_type") == dt)
            if rows.height:
                day_types[dt] = day_type_record(rows, lv[(pid, dt)], s)
        out.append(
            {
                "schema_version": SCHEMA_VERSION,
                "generated_at": generated_at.isoformat(timespec="seconds"),
                "data_period": {"start": period[0].isoformat(), "end": period[1].isoformat()},
                "profile_periods": profile_periods,
                "place": meta[pid],
                "reference_level": round(float(ref[pid]), 1),
                "day_types": day_types,
                "attribution": ATTRIBUTION,
            }
        )
    return out


def index_record(
    places: list[dict[str, Any]],
    s: ScoreSettings,
    period: tuple[date, date],
    generated_at: datetime,
) -> dict[str, Any]:
    keep = ["id", "name", "town", "lat", "lon", "lines"]
    bands = [{"band": name, "below": upper} for upper, name in s.bands]
    bands.append({"band": "very_busy", "below": None})
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at.isoformat(timespec="seconds"),
        "data_period": {"start": period[0].isoformat(), "end": period[1].isoformat()},
        "bands": bands,
        "places": sorted(
            (
                {k: p["place"].get(k) for k in keep}
                | {"weekday_entries": p["day_types"].get("JOHV", {}).get("daily_entries")}
                for p in places
            ),
            key=lambda x: x["name"],
        ),
        "attribution": ATTRIBUTION,
    }


def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def write(out_dir: Path, index: dict[str, Any], places: list[dict[str, Any]]) -> list[Path]:
    """Write files; remove stale places/*.json (warns if the filesystem refuses)."""
    pdir = out_dir / "places"
    pdir.mkdir(parents=True, exist_ok=True)
    written = []
    for p in places:
        path = pdir / f"{p['place']['id']}.json"
        path.write_text(_dump(p), encoding="utf-8")
        written.append(path)
    (out_dir / "index.json").write_text(_dump(index), encoding="utf-8")
    keep = {p.name for p in written}
    for stale in pdir.glob("*.json"):
        if stale.name not in keep:
            try:
                stale.unlink()
            except OSError as e:
                warnings.warn(f"could not remove stale {stale.name}: {e}", stacklevel=2)
    return [out_dir / "index.json", *written]
