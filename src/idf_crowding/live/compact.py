"""Pack each finished day of raw disruption snapshots into one archive (lossless).

Consecutive snapshots are ~99 % identical, so one xz archive per day is 30-50x smaller
than separate .json.gz files. Layout after compaction of raw/YYYY-MM-DD/:

    snapshots.tar.xz   every snapshot body, member name = original name without ".gz"
    compacted.json     what was packed: per member sha256 + bytes, archive sha256
    polls.jsonl        unchanged; its "file" pointers resolve through `read_snapshot`

Originals are deleted only when `delete` is true AND the archive was re-read and every
body matched both its .json.gz file and the sha256 logged at poll time. The current UTC
day is never touched. Use `read_snapshot` / `iter_snapshots` to read either layout.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import lzma
import os
import tarfile
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

ARCHIVE = "snapshots.tar.xz"
MANIFEST = "compacted.json"
XZ_PRESET = 9 | lzma.PRESET_EXTREME


class VerificationError(RuntimeError):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def logged_hashes(day_dir: Path) -> dict[str, str]:
    """file name -> sha256 recorded at poll time, for polls that wrote a new file."""
    out: dict[str, str] = {}
    polls = day_dir / "polls.jsonl"
    if not polls.is_file():
        return out
    for line in polls.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        if rec.get("changed") and rec.get("file") and rec.get("sha256"):
            out[Path(rec["file"]).name] = rec["sha256"]
    return out


def member_name(gz_name: str) -> str:
    return gz_name.removesuffix(".gz")


def compactable_days(raw_dir: Path, today: date) -> list[Path]:
    """Day folders strictly before `today` (UTC) that still hold .json.gz snapshots."""
    days = []
    for d in sorted(p for p in raw_dir.iterdir() if p.is_dir()):
        try:
            day = date.fromisoformat(d.name)
        except ValueError:
            continue
        if day < today and any(d.glob("*.json.gz")):
            days.append(d)
    return days


def build_archive(day_dir: Path) -> dict[str, Any]:
    """Write snapshots.tar.xz (atomically) from the day's .json.gz files; return manifest."""
    files = sorted(day_dir.glob("*.json.gz"))
    logged = logged_hashes(day_dir)
    members = []
    tmp = day_dir / (ARCHIVE + ".tmp")
    with tarfile.open(tmp, "w:xz", preset=XZ_PRESET) as tar:
        for f in files:
            body = gzip.decompress(f.read_bytes())
            digest = _sha(body)
            if f.name in logged and logged[f.name] != digest:
                tmp.unlink(missing_ok=True)
                raise VerificationError(f"{f.name}: body does not match sha256 in polls.jsonl")
            info = tarfile.TarInfo(member_name(f.name))
            info.size = len(body)
            info.mtime = int(f.stat().st_mtime)
            tar.addfile(info, io.BytesIO(body))
            members.append({"name": info.name, "sha256": digest, "bytes": len(body)})
    os.replace(tmp, day_dir / ARCHIVE)
    manifest = {
        "archive": ARCHIVE,
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "archive_sha256": _sha((day_dir / ARCHIVE).read_bytes()),
        "archive_bytes": (day_dir / ARCHIVE).stat().st_size,
        "source_bytes": sum(f.stat().st_size for f in files),
        "members": members,
    }
    (day_dir / MANIFEST).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def verify(day_dir: Path) -> list[Path]:
    """Re-read the archive; return the .json.gz files it fully covers. Raises on mismatch."""
    manifest = json.loads((day_dir / MANIFEST).read_text(encoding="utf-8"))
    if _sha((day_dir / ARCHIVE).read_bytes()) != manifest["archive_sha256"]:
        raise VerificationError(f"{day_dir.name}: archive sha256 differs from manifest")
    expected = {m["name"]: m["sha256"] for m in manifest["members"]}
    seen: dict[str, str] = {}
    with tarfile.open(day_dir / ARCHIVE, "r:xz") as tar:
        for m in tar:
            fh = tar.extractfile(m)
            if fh is not None:
                seen[m.name] = _sha(fh.read())
    if seen != expected:
        raise VerificationError(f"{day_dir.name}: archive content differs from manifest")
    logged = logged_hashes(day_dir)
    covered = []
    for f in sorted(day_dir.glob("*.json.gz")):
        name = member_name(f.name)
        body_sha = _sha(gzip.decompress(f.read_bytes()))
        if seen.get(name) != body_sha:
            raise VerificationError(f"{f.name}: missing from archive or different")
        if f.name in logged and logged[f.name] != body_sha:
            raise VerificationError(f"{f.name}: differs from sha256 logged at poll time")
        covered.append(f)
    return covered


def compact_day(day_dir: Path, delete: bool = False) -> dict[str, Any]:
    """Archive one day (or extend an existing archive) and optionally delete originals."""
    if (day_dir / ARCHIVE).exists():
        # Originals left from an earlier run without --delete: the archive must cover them.
        try:
            covered = verify(day_dir)
        except VerificationError:
            # New .json.gz files appeared after the archive (e.g. clock skew): rebuild
            # from what is on disk only if the archive held nothing that is now missing.
            manifest = json.loads((day_dir / MANIFEST).read_text(encoding="utf-8"))
            on_disk = {member_name(f.name) for f in day_dir.glob("*.json.gz")}
            if not {m["name"] for m in manifest["members"]} <= on_disk:
                raise
            build_archive(day_dir)
            covered = verify(day_dir)
    else:
        build_archive(day_dir)
        covered = verify(day_dir)
    manifest = json.loads((day_dir / MANIFEST).read_text(encoding="utf-8"))
    deleted = 0
    if delete:
        for f in covered:
            f.unlink()
            deleted += 1
    return {
        "day": day_dir.name,
        "snapshots": len(manifest["members"]),
        "source_bytes": manifest["source_bytes"],
        "archive_bytes": manifest["archive_bytes"],
        "verified": True,
        "deleted": deleted,
    }


def compact_all(raw_dir: Path, today: date, delete: bool = False) -> list[dict[str, Any]]:
    return [compact_day(d, delete=delete) for d in compactable_days(raw_dir, today)]


def read_snapshot(out_dir: Path, file: str) -> bytes:
    """Body for a polls.jsonl "file" pointer, whether or not its day was compacted."""
    path = out_dir / file
    if path.is_file():
        return gzip.decompress(path.read_bytes())
    archive = path.parent / ARCHIVE
    with tarfile.open(archive, "r:xz") as tar:
        fh = tar.extractfile(member_name(path.name))
        if fh is None:
            raise FileNotFoundError(file)
        return fh.read()


def iter_snapshots(day_dir: Path) -> Iterator[tuple[str, bytes]]:
    """(member name, body) for every snapshot of one day, in time order."""
    if (day_dir / ARCHIVE).exists():
        with tarfile.open(day_dir / ARCHIVE, "r:xz") as tar:
            items = {m.name: tar.extractfile(m).read() for m in tar if m.isfile()}
    else:
        items = {}
    for f in day_dir.glob("*.json.gz"):
        items.setdefault(member_name(f.name), gzip.decompress(f.read_bytes()))
    yield from sorted(items.items())
