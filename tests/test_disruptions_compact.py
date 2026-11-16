import gzip
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from idf_crowding.live.compact import (
    ARCHIVE,
    MANIFEST,
    VerificationError,
    compact_all,
    compact_day,
    iter_snapshots,
    read_snapshot,
)
from idf_crowding.live.disruptions import Response, Settings, poll_once

DAY1 = datetime(2026, 1, 15, 23, 45, tzinfo=UTC)  # 3 polls on day 1, 1 on day 2


def body(i: int) -> bytes:
    msgs = [{"id": f"m{k}", "title": "Travaux" * 20} for k in range(50 + i)]
    return json.dumps({"disruptions": msgs, "lastUpdatedDate": f"t{i}"}).encode()


@pytest.fixture
def logged(tmp_path: Path) -> Settings:
    """Three polls on day 1, the last one unchanged, then one poll on day 2."""
    s = Settings(url="https://example.invalid", api_key="x", out_dir=tmp_path)
    bodies = [body(0), body(1), body(1), body(2)]
    for k, b in enumerate(bodies):
        poll_once(s, fetch=lambda _s, b=b: Response(200, b), now=DAY1 + timedelta(minutes=5 * k))
    return s


def day_dir(s: Settings, d: str = "2026-01-15") -> Path:
    return s.out_dir / "raw" / d


def test_compact_skips_current_day_and_keeps_originals_by_default(logged):
    results = compact_all(logged.out_dir / "raw", today=date(2026, 1, 16))

    assert [r["day"] for r in results] == ["2026-01-15"]
    assert results[0]["snapshots"] == 2 and results[0]["deleted"] == 0
    assert (day_dir(logged) / ARCHIVE).exists()
    assert len(list(day_dir(logged).glob("*.json.gz"))) == 2
    assert not (day_dir(logged, "2026-01-16") / ARCHIVE).exists()


def test_compact_with_delete_is_lossless(logged):
    before = list(iter_snapshots(day_dir(logged)))
    pointers = [
        json.loads(line)["file"]
        for line in (day_dir(logged) / "polls.jsonl").read_text().splitlines()
    ]

    compact_day(day_dir(logged), delete=True)

    assert not list(day_dir(logged).glob("*.json.gz"))
    assert list(iter_snapshots(day_dir(logged))) == before
    # every polls.jsonl pointer still resolves, including the "unchanged" poll
    assert [read_snapshot(logged.out_dir, p) for p in pointers] == [body(0), body(1), body(1)]


def test_compact_is_idempotent_and_can_delete_later(logged):
    compact_day(day_dir(logged))
    again = compact_day(day_dir(logged), delete=True)

    assert again["deleted"] == 2
    assert again["archive_bytes"] < again["source_bytes"]


def test_compact_refuses_body_that_differs_from_logged_hash(logged):
    victim = sorted(day_dir(logged).glob("*.json.gz"))[0]
    victim.write_bytes(gzip.compress(b'{"tampered": true}'))

    with pytest.raises(VerificationError):
        compact_day(day_dir(logged), delete=True)

    assert victim.exists()
    assert not (day_dir(logged) / ARCHIVE).exists()


def test_corrupt_archive_is_rebuilt_from_originals_before_deleting(logged):
    before = list(iter_snapshots(day_dir(logged)))
    compact_day(day_dir(logged))
    archive = day_dir(logged) / ARCHIVE
    archive.write_bytes(archive.read_bytes()[:-10])

    compact_day(day_dir(logged), delete=True)

    assert not list(day_dir(logged).glob("*.json.gz"))
    assert list(iter_snapshots(day_dir(logged))) == before


def test_corrupt_archive_without_originals_raises(logged):
    compact_day(day_dir(logged), delete=True)
    archive = day_dir(logged) / ARCHIVE
    archive.write_bytes(archive.read_bytes()[:-10])

    with pytest.raises(VerificationError):
        compact_day(day_dir(logged), delete=True)


def test_manifest_records_every_member(logged):
    compact_day(day_dir(logged))
    manifest = json.loads((day_dir(logged) / MANIFEST).read_text())
    assert [m["name"] for m in manifest["members"]] == [
        "20260115T234500Z.json",
        "20260115T235000Z.json",
    ]
