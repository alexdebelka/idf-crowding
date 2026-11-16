"""Places: one per Counting point by default; an override file merges several into one.

places.toml (repo root, path in config [score] places_file):

    [[place]]
    id = "chatelet-les-halles"      # URL-safe, lower case
    name = "Châtelet – Les Halles"
    station_ids = [71264, 474151]   # ZdC ids; entries are summed, never split by line

A station may belong to one override only.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

import polars as pl

PLACE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


@dataclass(frozen=True)
class PlaceOverride:
    id: str
    name: str
    station_ids: tuple[int, ...]


def load_overrides(path: Path | None) -> list[PlaceOverride]:
    if path is None or not path.is_file():
        return []
    with open(path, "rb") as f:
        data = tomllib.load(f)
    out = []
    for p in data.get("place", []):
        o = PlaceOverride(str(p["id"]), str(p["name"]), tuple(int(x) for x in p["station_ids"]))
        if not PLACE_ID.match(o.id) or o.id.isdigit():
            raise ValueError(f"place id {o.id!r}: use lower-case letters, digits and '-'")
        if len(o.station_ids) < 2:
            raise ValueError(f"place {o.id}: an override needs at least 2 station_ids")
        out.append(o)
    return out


def assign(station_ids: list[int], overrides: list[PlaceOverride]) -> pl.DataFrame:
    """place_id, station_id for every station in `station_ids` (default place id =
    str(station_id)). Override members missing from `station_ids` are ignored."""
    seen: dict[int, str] = {}
    ids = {o.id for o in overrides}
    if len(ids) != len(overrides):
        raise ValueError("duplicate place id in overrides")
    for o in overrides:
        for sid in o.station_ids:
            if sid in seen:
                raise ValueError(f"station {sid} is in places {seen[sid]} and {o.id}")
            seen[sid] = o.id
    rows = [(seen.get(sid, str(sid)), sid) for sid in station_ids]
    return pl.DataFrame(rows, schema={"place_id": pl.String, "station_id": pl.Int64}, orient="row")
