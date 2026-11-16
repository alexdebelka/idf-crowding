"""Download IDFM open data (validations, stop reference, documentation) into data/raw.

Sources: DATA_SOURCES.md #1-#4, via the Opendatasoft Explore API v2.1 of the IDFM portal.

Layout under <data_dir>/raw/:
    idfm/validations_history/<dataset_id>/<filename>       yearly zips, one record per year
    idfm/validations_quarterly/<dataset_id>/<YYYYQn>.csv   rolling quarterly datasets
    idfm/reference/<dataset_id>/<YYYY-MM-DD>.csv           stop reference, snapshot per day
    idfm/docs/<dataset_id>/<attachment title>
    manifest.jsonl                                          one line per downloaded file

The quarterly datasets keep the same ID and are overwritten by IDFM each year, so each run
stores the quarter it finds under its own period name. Files already on disk are never
overwritten: data/raw is immutable.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx

from idf_crowding.config import load_config

MANIFEST = "manifest.jsonl"
QUARTER_RE = re.compile(r"(\d)\s*(?:er|ème|eme|e)\s+trimestre\s+(\d{4})", re.IGNORECASE)


@dataclass(frozen=True)
class Settings:
    base_url: str
    raw_dir: Path
    history_datasets: dict[str, str]
    quarterly_datasets: list[str]
    reference_datasets: list[str]
    attachments: list[tuple[str, str]]
    timeout_seconds: float = 120
    max_attempts: int = 3
    backoff_seconds: float = 5

    @classmethod
    def from_config(cls, config: dict[str, Any] | None = None) -> Settings:
        config = config or load_config()
        s = config["ingest"]["idfm"]
        return cls(
            base_url=s["base_url"].rstrip("/"),
            raw_dir=Path(config["paths"]["data_dir"]) / "raw",
            history_datasets=dict(s["history_datasets"]),
            quarterly_datasets=list(s["quarterly_datasets"]),
            reference_datasets=list(s["reference_datasets"]),
            attachments=[(a[0], a[1]) for a in s["attachments"]],
            timeout_seconds=s.get("timeout_seconds", 120),
            max_attempts=s.get("max_attempts", 3),
            backoff_seconds=s.get("backoff_seconds", 5),
        )


class RawStore(Protocol):
    """What `download` needs: any source's settings with these attributes."""

    raw_dir: Path
    max_attempts: int
    backoff_seconds: float


@dataclass(frozen=True)
class Item:
    """One file to download. `dest` is relative to the raw dir."""

    url: str
    dest: Path
    dataset_id: str
    period: str
    license: str
    dataset_modified: str


def quarter_from_title(title: str) -> str:
    """'... (1er trimestre 2026)' -> '2026Q1'."""
    m = QUARTER_RE.search(title)
    if not m:
        raise ValueError(f"no quarter found in dataset title: {title!r}")
    return f"{m.group(2)}Q{m.group(1)}"


def _get_json(client: httpx.Client, url: str, **params: Any) -> dict[str, Any]:
    r = client.get(url, params=params or None)
    r.raise_for_status()
    return r.json()


def _meta(client: httpx.Client, base: str, dataset_id: str) -> dict[str, Any]:
    return _get_json(client, f"{base}/catalog/datasets/{dataset_id}")


def _default(meta: dict[str, Any]) -> tuple[str, str, str]:
    d = meta.get("metas", {}).get("default", {})
    return d.get("title", ""), d.get("license", ""), d.get("modified", "")


def plan(client: httpx.Client, s: Settings, today: date) -> list[Item]:
    """List every file to fetch, from the portal's catalog API (no downloads)."""
    base = s.base_url
    items: list[Item] = []

    for ds, file_field in s.history_datasets.items():
        _, lic, mod = _default(_meta(client, base, ds))
        data = _get_json(client, f"{base}/catalog/datasets/{ds}/records", limit=100)
        if data.get("total_count", 0) > 100:
            raise RuntimeError(f"{ds}: more than 100 records, add paging")
        for rec in data["results"]:
            f = rec.get(file_field)
            if not f:
                continue
            items.append(
                Item(
                    url=f["url"],
                    dest=Path("idfm/validations_history") / ds / f["filename"],
                    dataset_id=ds,
                    period=str(rec.get("annee", "")),
                    license=lic,
                    dataset_modified=mod,
                )
            )

    for ds in s.quarterly_datasets:
        title, lic, mod = _default(_meta(client, base, ds))
        period = quarter_from_title(title)
        items.append(
            Item(
                url=f"{base}/catalog/datasets/{ds}/exports/csv?delimiter=%3B",
                dest=Path("idfm/validations_quarterly") / ds / f"{period}.csv",
                dataset_id=ds,
                period=period,
                license=lic,
                dataset_modified=mod,
            )
        )

    for ds in s.reference_datasets:
        _, lic, mod = _default(_meta(client, base, ds))
        items.append(
            Item(
                url=f"{base}/catalog/datasets/{ds}/exports/csv?delimiter=%3B",
                dest=Path("idfm/reference") / ds / f"{today.isoformat()}.csv",
                dataset_id=ds,
                period=f"snapshot {today.isoformat()}",
                license=lic,
                dataset_modified=mod,
            )
        )

    for ds, att_id in s.attachments:
        meta = _meta(client, base, ds)
        _, lic, mod = _default(meta)
        att = next((a for a in meta.get("attachments", []) if a.get("id") == att_id), None)
        if att is None:
            raise RuntimeError(f"{ds}: attachment {att_id!r} not found")
        items.append(
            Item(
                url=att["url"],
                dest=Path("idfm/docs") / ds / att["title"],
                dataset_id=ds,
                period="",
                license=lic,
                dataset_modified=mod,
            )
        )
    return items


def _stream_to(client: httpx.Client, url: str, tmp: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    n = 0
    with client.stream("GET", url) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                h.update(chunk)
                n += len(chunk)
    return h.hexdigest(), n


def download(
    client: httpx.Client, item: Item, s: RawStore, sleep=time.sleep
) -> dict[str, Any] | None:
    """Fetch one item unless it is already on disk; append it to the manifest."""
    dest = s.raw_dir / item.dest
    if dest.exists():
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    for attempt in range(1, s.max_attempts + 1):
        try:
            sha, size = _stream_to(client, item.url, tmp)
            break
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            tmp.unlink(missing_ok=True)
            retryable = isinstance(e, httpx.TransportError) or e.response.status_code >= 500
            if not retryable or attempt == s.max_attempts:
                raise
            sleep(s.backoff_seconds * attempt)
    tmp.replace(dest)
    entry = {
        "path": item.dest.as_posix(),
        "source_url": item.url,
        "dataset_id": item.dataset_id,
        "period": item.period,
        "license": item.license,
        "dataset_modified": item.dataset_modified,
        "downloaded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sha256": sha,
        "bytes": size,
    }
    with open(s.raw_dir / MANIFEST, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry
