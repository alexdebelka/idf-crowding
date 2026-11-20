"""One binary file with every Place's date forecasts, for the Flipper Zero app (flipper/).

    idf-score flipper [--days N] [--out PATH]

Reads the app's published contract (<app_data_dir>/index.json and places/*.json, place.v2),
so the file shows exactly what the web app shows. Layout (little-endian), version 1:

    0   b"APT1"
    4   u8  version (1)
    5   u8  hours per day (24, operating day 04 h ... 03 h)
    6   u8  first hour (4)
    7   u8  score divisor (2: stored value = min(255, score // 2))
    8   u16 first date, days since 1970-01-01
    10  u16 number of dates
    12  u16 forecast issue date (days since 1970-01-01, 0 = none)
    14  u16 data end date (idem)
    16  u8  x 3 band thresholds: moderate from, busy from, very busy from (score units)
    19  u8  reserved (0)
    20  u16 number of Places
    22  u32 offset of the score block
    26  Place records, sorted by name: u32 id, u8 name length, name (UTF-8),
        u8 number of lines, then per line: u8 kind, u8 name length, name (ASCII).
        Names are UTF-8 (the device draws UTF-8) limited to Latin-1 characters (its fonts).
    ... score block: Places in record order x dates x 24 hours, u8 each.

The divisor keeps band edges exact: thresholds are even, and floor(s / 2) * 2 < t iff s < t.
A date without its own forecast falls back to the typical week of its weekday, as in the app.
"""

from __future__ import annotations

import json
import struct
import unicodedata
from datetime import date, timedelta
from pathlib import Path
from typing import Any

MAGIC = b"APT1"
VERSION = 1
HOURS = 24
FIRST_HOUR = 4
DIVISOR = 2
EPOCH = date(1970, 1, 1)
KINDS = {"metro": 0, "rer": 1, "transilien": 2, "tram": 3}
KIND_OTHER = 4
HEADER = struct.Struct("<4sBBBBHHHH3BBHI")
# Characters outside Latin-1 that occur in station names (the device fonts are Latin-1).
LATIN1_FALLBACK = {"–": "-", "—": "-", "’": "'", "œ": "oe", "Œ": "OE"}


def day_number(iso: str | None) -> int:
    return (date.fromisoformat(iso) - EPOCH).days if iso else 0


def device_name(s: str) -> bytes:
    """UTF-8 bytes of Latin-1 characters only, at most 255 bytes, never cut inside one."""
    s = "".join(LATIN1_FALLBACK.get(c, c) for c in s)
    s = "".join(c if ord(c) < 256 else "?" for c in s)
    out = s.encode("utf-8")
    while len(out) > 255:
        s = s[:-1]
        out = s.encode("utf-8")
    return out


def sort_key(name: str) -> str:
    plain = unicodedata.normalize("NFD", name)
    return "".join(c for c in plain if not unicodedata.combining(c)).casefold()


def default_day_type(d: date) -> str:
    wd = d.isoweekday()  # Monday 1 ... Sunday 7
    return "DIJFP" if wd == 7 else "SAHV" if wd == 6 else "JOHV"


def typical_scores(place: dict[str, Any], d: date) -> list[int]:
    day_types = place.get("day_types") or {}
    for dt in (default_day_type(d), "JOHV", "JOVS", "SAHV", "SAVS", "DIJFP"):
        hours = (day_types.get(dt) or {}).get("hours") or []
        if len(hours) == HOURS:
            out = [0] * HOURS
            for r in hours:
                out[(r["h"] - FIRST_HOUR) % HOURS] = r["score"]
            return out
    return [0] * HOURS


def encode_score(s: float) -> int:
    return max(0, min(255, int(s) // DIVISOR))


def thresholds(bands: list[dict[str, Any]]) -> tuple[int, int, int]:
    edges = [b["below"] for b in bands if b.get("below") is not None]
    if len(edges) != 3 or any(e % DIVISOR or e > 255 for e in edges):
        raise ValueError(f"expected 3 even band edges <= 255, got {edges}")
    return tuple(int(e) for e in edges)  # type: ignore[return-value]


def place_record(place_id: str, name: str, lines: list[dict[str, Any]]) -> bytes:
    seen: list[tuple[int, bytes]] = []
    for line in lines:
        item = (KINDS.get(line["kind"], KIND_OTHER), line["name"].encode("ascii", "replace")[:8])
        if item not in seen:
            seen.append(item)
    out = struct.pack("<I", int(place_id))
    nb = device_name(name)
    out += struct.pack("<B", len(nb)) + nb + struct.pack("<B", min(len(seen), 255))
    for kind, nm in seen[:255]:
        out += struct.pack("<BB", kind, len(nm)) + nm
    return out


def build_file(index: dict[str, Any], places: dict[str, dict[str, Any]], days: int) -> bytes:
    """index: index.json; places: id -> place file. Returns the file's bytes."""
    order = sorted(index["places"], key=lambda p: (sort_key(p["name"]), p["id"]))
    dated = [p for p in places.values() if p.get("forecast", {}).get("dates")]
    if dated:
        first = min(date.fromisoformat(p["forecast"]["dates"][0]["d"]) for p in dated)
        last = max(date.fromisoformat(p["forecast"]["dates"][-1]["d"]) for p in dated)
        n_days = min(days, (last - first).days + 1)
        issue = max(p["forecast"].get("issue_date") or "" for p in dated) or None
        data_end = max(p["forecast"].get("data_end") or "" for p in dated) or None
    else:
        first, n_days, issue, data_end = date.today(), days, None, None
    records, scores = b"", bytearray()
    for meta in order:
        place = places[meta["id"]]
        records += place_record(meta["id"], meta["name"], meta["lines"])
        by_date = {d["d"]: d["scores"] for d in (place.get("forecast") or {}).get("dates", [])}
        for i in range(n_days):
            d = first + timedelta(days=i)
            row = by_date.get(d.isoformat())
            if not row or len(row) != HOURS:
                row = typical_scores(place, d)
            scores += bytes(encode_score(s) for s in row)
    t = thresholds(index["bands"])
    offset = HEADER.size + len(records)
    header = HEADER.pack(
        MAGIC,
        VERSION,
        HOURS,
        FIRST_HOUR,
        DIVISOR,
        day_number(first.isoformat()),
        n_days,
        day_number(issue),
        day_number(data_end),
        *t,
        0,
        len(order),
        offset,
    )
    return header + records + bytes(scores)


def export(app_data: Path, out: Path, days: int) -> dict[str, Any]:
    index = json.loads((app_data / "index.json").read_text(encoding="utf-8"))
    places = {
        p["id"]: json.loads((app_data / "places" / f"{p['id']}.json").read_text(encoding="utf-8"))
        for p in index["places"]
    }
    blob = build_file(index, places, days)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(blob)
    head = HEADER.unpack_from(blob)
    return {
        "path": str(out),
        "bytes": len(blob),
        "places": head[13],
        "first": (EPOCH + timedelta(days=head[5])).isoformat(),
        "days": head[6],
    }
