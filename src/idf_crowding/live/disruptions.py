"""Raw logger for PRIM "Messages Info Trafic - requête globale" (DATA_SOURCES.md #12).

One call to `poll_once` = one request. Scheduling is left to cron / systemd / launchd
(see deploy/). Responses are stored as-is, gzipped; parsing happens later (Phase 4b).

Layout under <live_dir>/disruptions/:
    raw/YYYY-MM-DD/YYYYMMDDTHHMMSSZ.json.gz  response body, only when it changed
    raw/YYYY-MM-DD/polls.jsonl                one line per poll (success or failure)
    gaps.jsonl                                periods without a successful poll
    state.json                                last success, last body hash

Finished days are packed into one archive by `idf-disruptions compact` (see compact.py).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from idf_crowding.config import load_config, load_env, require_env

SOURCE = "prim_messages_info_trafic_bulk"


@dataclass(frozen=True)
class Settings:
    url: str
    api_key: str
    out_dir: Path
    interval_seconds: int = 300
    gap_factor: float = 1.5
    timeout_seconds: float = 30
    max_attempts: int = 3
    backoff_seconds: float = 5
    delete_after_compact: bool = False

    @classmethod
    def from_config(cls) -> Settings:
        load_env()
        config = load_config()
        section = config["live"]["disruptions"]
        return cls(
            url=section["url"],
            api_key=require_env(section["api_key_env"]),
            out_dir=Path(config["paths"]["live_dir"]) / "disruptions",
            interval_seconds=section["interval_seconds"],
            gap_factor=section["gap_factor"],
            timeout_seconds=section["timeout_seconds"],
            max_attempts=section["max_attempts"],
            backoff_seconds=section["backoff_seconds"],
            delete_after_compact=section.get("delete_after_compact", False),
        )


@dataclass(frozen=True)
class Response:
    status_code: int
    body: bytes


Fetcher = Callable[[Settings], Response]


class RetryableError(Exception):
    pass


def http_fetch(settings: Settings) -> Response:
    headers = {"apikey": settings.api_key, "Accept": "application/json"}
    try:
        r = httpx.get(settings.url, headers=headers, timeout=settings.timeout_seconds)
    except httpx.TransportError as e:
        raise RetryableError(f"{type(e).__name__}: {e}") from e
    if r.status_code == 429 or r.status_code >= 500:
        raise RetryableError(f"HTTP {r.status_code}")
    return Response(r.status_code, r.content)


def fetch_with_retries(
    settings: Settings, fetch: Fetcher, sleep: Callable[[float], None] = time.sleep
) -> tuple[Response | None, list[str]]:
    """Return (response, errors). Response is None if every attempt failed."""
    errors: list[str] = []
    for attempt in range(settings.max_attempts):
        try:
            return fetch(settings), errors
        except RetryableError as e:
            errors.append(str(e))
            if attempt + 1 < settings.max_attempts:
                sleep(settings.backoff_seconds * 2**attempt)
    return None, errors


def iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def read_state(path: Path) -> dict[str, Any]:
    if path.is_file():
        return json.loads(path.read_text())
    return {}


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def last_updated_date(body: bytes) -> str | None:
    try:
        value = json.loads(body).get("lastUpdatedDate")
    except (ValueError, AttributeError):
        return None
    return value if isinstance(value, str) else None


def detect_gap(
    last_success: str | None, now: datetime, settings: Settings
) -> dict[str, Any] | None:
    """Gap between the previous successful poll and `now`, if longer than expected."""
    if last_success is None:
        return None
    previous = datetime.strptime(last_success, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    seconds = (now - previous).total_seconds()
    if seconds <= settings.interval_seconds * settings.gap_factor:
        return None
    return {"source": SOURCE, "start": last_success, "end": iso(now), "seconds": int(seconds)}


def poll_once(
    settings: Settings,
    fetch: Fetcher = http_fetch,
    now: datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Run one poll, write the raw body if it changed, log the poll and any gap."""
    now = (now or datetime.now(UTC)).replace(microsecond=0)
    day_dir = settings.out_dir / "raw" / now.strftime("%Y-%m-%d")
    state_path = settings.out_dir / "state.json"
    state = read_state(state_path)

    response, errors = fetch_with_retries(settings, fetch, sleep)
    record: dict[str, Any] = {"source": SOURCE, "polled_at": iso(now), "errors": errors}

    if response is None or response.status_code != 200:
        record.update(ok=False, status_code=response.status_code if response else None)
        if response is not None:
            record["body_excerpt"] = response.body[:500].decode("utf-8", "replace")
        append_jsonl(day_dir / "polls.jsonl", record)
        return record

    digest = hashlib.sha256(response.body).hexdigest()
    record.update(
        ok=True,
        status_code=200,
        sha256=digest,
        bytes=len(response.body),
        last_updated_date=last_updated_date(response.body),
    )
    if digest == state.get("last_sha256"):
        # Identical body: keep a pointer instead of a second copy.
        record.update(changed=False, file=state.get("last_file"))
    else:
        rel = Path("raw") / now.strftime("%Y-%m-%d") / f"{now:%Y%m%dT%H%M%SZ}.json.gz"
        write_atomic(settings.out_dir / rel, gzip.compress(response.body, mtime=0))
        record.update(changed=True, file=rel.as_posix())
        state.update(last_sha256=digest, last_file=rel.as_posix())

    gap = detect_gap(state.get("last_success"), now, settings)
    if gap is not None:
        append_jsonl(settings.out_dir / "gaps.jsonl", gap)
        record["gap_before_seconds"] = gap["seconds"]

    append_jsonl(day_dir / "polls.jsonl", record)
    state["last_success"] = iso(now)
    write_atomic(state_path, json.dumps(state, indent=2).encode())
    return record


def open_gap(settings: Settings, now: datetime | None = None) -> dict[str, Any] | None:
    """Gap still in progress (no successful poll since), for status checks."""
    now = (now or datetime.now(UTC)).replace(microsecond=0)
    state = read_state(settings.out_dir / "state.json")
    return detect_gap(state.get("last_success"), now, settings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="idf-disruptions", description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=["poll", "status", "compact"])
    parser.add_argument(
        "--delete-originals",
        action="store_true",
        help="compact: delete .json.gz files once the archive is verified",
    )
    args = parser.parse_args(argv)
    settings = Settings.from_config()

    if args.command == "poll":
        record = poll_once(settings)
        summary = {k: record.get(k) for k in ("polled_at", "ok", "status_code", "changed")}
        print(json.dumps(summary))
        return 0 if record["ok"] else 1

    if args.command == "compact":
        from idf_crowding.live.compact import compact_all

        delete = args.delete_originals or settings.delete_after_compact
        today = datetime.now(UTC).date()
        for result in compact_all(settings.out_dir / "raw", today, delete=delete):
            print(json.dumps(result))
        return 0

    state = read_state(settings.out_dir / "state.json")
    gaps_path = settings.out_dir / "gaps.jsonl"
    n_gaps = len(gaps_path.read_text().splitlines()) if gaps_path.is_file() else 0
    status = {
        "out_dir": str(settings.out_dir),
        "last_success": state.get("last_success"),
        "logged_gaps": n_gaps,
        "open_gap": open_gap(settings),
    }
    print(json.dumps(status, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
