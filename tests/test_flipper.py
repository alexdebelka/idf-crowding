"""Flipper Zero export (score/flipper.py): file layout and the rules it applies."""

import struct
from datetime import date

import pytest

from idf_crowding.score import flipper

BANDS = [
    {"band": "quiet", "below": 40.0},
    {"band": "moderate", "below": 70.0},
    {"band": "busy", "below": 100.0},
    {"band": "very_busy", "below": None},
]


def place(pid, dates=None, typical=None):
    p = {"place": {"id": pid}, "day_types": {}}
    if dates is not None:
        p["forecast"] = {"issue_date": "2026-11-18", "data_end": "2026-06-30", "dates": dates}
    if typical is not None:
        p["day_types"]["JOHV"] = {
            "hours": [{"h": (i + 4) % 24, "score": typical} for i in range(24)]
        }
    return p


def parse(blob):
    head = flipper.HEADER.unpack_from(blob)
    pos, recs = flipper.HEADER.size, []
    for _ in range(head[13]):
        pid, n = struct.unpack_from("<IB", blob, pos)
        pos += 5
        name = blob[pos : pos + n].decode("utf-8")
        pos += n
        (nl,) = struct.unpack_from("<B", blob, pos)
        pos += 1
        lines = []
        for _ in range(nl):
            kind, ln = struct.unpack_from("<BB", blob, pos)
            lines.append((kind, blob[pos + 2 : pos + 2 + ln].decode()))
            pos += 2 + ln
        recs.append((pid, name, lines))
    assert pos == head[14]
    return head, recs, blob[head[14] :]


def test_layout_and_order():
    index = {
        "bands": BANDS,
        "places": [
            {"id": "2", "name": "Étoile", "lines": [{"name": "1", "kind": "metro"}]},
            {
                "id": "1",
                "name": "Châtelet – Les Halles",
                "lines": [
                    {"name": "A", "kind": "rer"},
                    {"name": "A", "kind": "rer"},
                    {"name": "T2", "kind": "tram"},
                    {"name": "X", "kind": "bus"},
                ],
            },
        ],
    }
    d = [{"d": "2026-11-19", "scores": list(range(24))}, {"d": "2026-11-20", "scores": [80] * 24}]
    blob = flipper.build_file(index, {"1": place("1", d), "2": place("2", d)}, days=28)
    head, recs, scores = parse(blob)
    assert head[0] == b"APT1" and head[1:5] == (1, 24, 4, 2)
    assert head[5] == (date(2026, 11, 19) - date(1970, 1, 1)).days and head[6] == 2
    assert head[9:12] == (40, 70, 100)
    # sorted ignoring accents; en dash folded (Latin-1 fonts); duplicates dropped; unknown kind 4
    assert [r[1] for r in recs] == ["Châtelet - Les Halles", "Étoile"]
    assert recs[0][2] == [(1, "A"), (3, "T2"), (4, "X")]
    assert len(scores) == 2 * 2 * 24
    assert list(scores[:24]) == [s // 2 for s in range(24)]


@pytest.mark.parametrize("s", range(0, 200))
def test_band_edges_survive_the_divisor(s):
    for t in (40, 70, 100):
        assert (flipper.encode_score(s) * flipper.DIVISOR < t) == (s < t)


def test_cap_and_floor():
    assert flipper.encode_score(600) == 255
    assert flipper.encode_score(-3) == 0
    assert flipper.encode_score(41.9) == 20


def test_missing_date_uses_typical_week():
    index = {
        "bands": BANDS,
        "places": [{"id": "1", "name": "A", "lines": []}, {"id": "2", "name": "B", "lines": []}],
    }
    dated = place(
        "1", [{"d": "2026-11-19", "scores": [10] * 24}, {"d": "2026-11-20", "scores": [10] * 24}]
    )
    typical = place("2", None, typical=60)  # Thursday 19 -> JOHV
    _, _, scores = parse(flipper.build_file(index, {"1": dated, "2": typical}, days=28))
    assert list(scores[48:72]) == [30] * 24


def test_bad_bands_refused():
    with pytest.raises(ValueError):
        flipper.thresholds([{"below": 41}, {"below": 70}, {"below": 100}, {"below": None}])


def test_device_name_is_utf8_latin1_and_never_cut_inside_a_character():
    assert flipper.device_name("Gare – Œuvre ’s") == b"Gare - OEuvre 's"
    assert flipper.device_name("\u20ac") == b"?"
    long = flipper.device_name("é" * 200)
    assert len(long) == 254 and long.decode("utf-8") == "é" * 127
