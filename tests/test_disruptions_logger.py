import gzip
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from idf_crowding.live.disruptions import (
    Response,
    RetryableError,
    Settings,
    detect_gap,
    open_gap,
    poll_once,
)

T0 = datetime(2026, 1, 15, 8, 0, 0, tzinfo=UTC)
BODY = json.dumps(
    {"disruptions": [], "lines": [], "lastUpdatedDate": "2026-01-15T07:59:00.000Z"}
).encode()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(url="https://example.invalid", api_key="x", out_dir=tmp_path)


def ok(body: bytes = BODY):
    return lambda _settings: Response(200, body)


def no_sleep(_seconds: float) -> None:
    pass


def read_polls(settings: Settings, day: str = "2026-01-15") -> list[dict]:
    path = settings.out_dir / "raw" / day / "polls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_success_writes_gzipped_raw_body(settings):
    record = poll_once(settings, fetch=ok(), now=T0)

    assert record["ok"] and record["changed"]
    assert record["file"] == "raw/2026-01-15/20260115T080000Z.json.gz"
    assert gzip.decompress((settings.out_dir / record["file"]).read_bytes()) == BODY
    assert record["last_updated_date"] == "2026-01-15T07:59:00.000Z"
    assert read_polls(settings) == [record]


def test_identical_body_is_not_stored_twice(settings):
    first = poll_once(settings, fetch=ok(), now=T0)
    second = poll_once(settings, fetch=ok(), now=T0 + timedelta(minutes=5))

    assert second["changed"] is False
    assert second["file"] == first["file"]
    assert len(list((settings.out_dir / "raw" / "2026-01-15").glob("*.json.gz"))) == 1


def test_changed_body_is_stored(settings):
    poll_once(settings, fetch=ok(), now=T0)
    second = poll_once(settings, fetch=ok(BODY + b" "), now=T0 + timedelta(minutes=5))

    assert second["changed"] is True
    assert len(list((settings.out_dir / "raw" / "2026-01-15").glob("*.json.gz"))) == 2


def test_failure_is_logged_without_raw_file(settings):
    def failing(_settings):
        raise RetryableError("HTTP 503")

    record = poll_once(settings, fetch=failing, now=T0, sleep=no_sleep)

    assert record["ok"] is False
    assert record["errors"] == ["HTTP 503"] * settings.max_attempts
    assert not list(settings.out_dir.rglob("*.json.gz"))
    assert read_polls(settings) == [record]


def test_non_200_is_logged_with_excerpt(settings):
    record = poll_once(settings, fetch=lambda _s: Response(401, b"bad key"), now=T0)

    assert record["ok"] is False and record["status_code"] == 401
    assert record["body_excerpt"] == "bad key"


def test_retry_then_success(settings):
    calls = iter([RetryableError("ConnectError"), Response(200, BODY)])

    def flaky(_settings):
        result = next(calls)
        if isinstance(result, Exception):
            raise result
        return result

    record = poll_once(settings, fetch=flaky, now=T0, sleep=no_sleep)

    assert record["ok"] and record["errors"] == ["ConnectError"]


def test_gap_logged_after_missed_polls(settings):
    poll_once(settings, fetch=ok(), now=T0)
    record = poll_once(settings, fetch=ok(), now=T0 + timedelta(minutes=30))

    gaps = (settings.out_dir / "gaps.jsonl").read_text().splitlines()
    assert json.loads(gaps[0])["start"] == "2026-01-15T08:00:00Z"
    assert json.loads(gaps[0])["seconds"] == 1800
    assert record["gap_before_seconds"] == 1800


def test_no_gap_for_regular_polls(settings):
    for i in range(3):
        poll_once(settings, fetch=ok(), now=T0 + timedelta(minutes=5 * i, seconds=20))

    assert not (settings.out_dir / "gaps.jsonl").exists()


def test_detect_gap_threshold(settings):
    assert detect_gap(None, T0, settings) is None
    assert detect_gap("2026-01-15T08:00:00Z", T0 + timedelta(seconds=450), settings) is None
    assert detect_gap("2026-01-15T08:00:00Z", T0 + timedelta(seconds=451), settings) is not None


def test_open_gap_reports_ongoing_outage(settings):
    poll_once(settings, fetch=ok(), now=T0)

    assert open_gap(settings, now=T0 + timedelta(minutes=5)) is None
    assert open_gap(settings, now=T0 + timedelta(hours=2))["seconds"] == 7200


def test_polls_split_by_utc_day(settings):
    poll_once(settings, fetch=ok(), now=datetime(2026, 1, 15, 23, 58, tzinfo=UTC))
    poll_once(settings, fetch=ok(), now=datetime(2026, 1, 16, 0, 3, tzinfo=UTC))

    assert len(read_polls(settings, "2026-01-15")) == 1
    assert len(read_polls(settings, "2026-01-16")) == 1
