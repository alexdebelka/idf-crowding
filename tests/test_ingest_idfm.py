import hashlib
import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from idf_crowding.config import REPO_ROOT, load_config
from idf_crowding.ingest.idfm import Item, Settings, download, plan, quarter_from_title

BASE = "https://portal.test/api/explore/v2.1"


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        base_url=BASE,
        raw_dir=tmp_path / "raw",
        history_datasets={"histo": "reseau_ferre"},
        quarterly_datasets=["nb-1er"],
        reference_datasets=["zdc"],
        attachments=[("histo", "doc_pdf")],
        backoff_seconds=0,
    )


def meta(title: str, attachments=None) -> dict:
    return {
        "metas": {"default": {"title": title, "license": "ODbL", "modified": "2026-09-01"}},
        "attachments": attachments or [],
    }


def fake_portal(request: httpx.Request) -> httpx.Response:
    path = request.url.path.removeprefix("/api/explore/v2.1")
    routes = {
        "/catalog/datasets/histo": meta(
            "Historique", [{"id": "doc_pdf", "title": "Doc.pdf", "url": f"{BASE}/att/doc"}]
        ),
        "/catalog/datasets/histo/records": {
            "total_count": 1,
            "results": [
                {
                    "annee": "2024",
                    "reseau_ferre": {"filename": "data-rf-2024.zip", "url": f"{BASE}/f/24"},
                }
            ],
        },
        "/catalog/datasets/nb-1er": meta("Nombre de validations par jour (1er trimestre 2026)"),
        "/catalog/datasets/zdc": meta("Zones de correspondance"),
    }
    if path in routes:
        return httpx.Response(200, json=routes[path])
    return httpx.Response(404)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Validations (1er trimestre 2026)", "2026Q1"),
        ("Validations (2ème trimestre 2026)", "2026Q2"),
        ("Validations (3eme trimestre 2025)", "2025Q3"),
        ("Validations (4ème trimestre 2025)", "2025Q4"),
    ],
)
def test_quarter_from_title(title, expected):
    assert quarter_from_title(title) == expected


def test_quarter_from_title_rejects_unknown():
    with pytest.raises(ValueError):
        quarter_from_title("Historique 2015-2025")


def test_plan_lists_all_sources(tmp_path):
    s = make_settings(tmp_path)
    client = httpx.Client(transport=httpx.MockTransport(fake_portal))

    items = plan(client, s, date(2026, 11, 11))

    assert [i.dest.as_posix() for i in items] == [
        "idfm/validations_history/histo/data-rf-2024.zip",
        "idfm/validations_quarterly/nb-1er/2026Q1.csv",
        "idfm/reference/zdc/2026-11-11.csv",
        "idfm/docs/histo/Doc.pdf",
    ]
    assert items[0].period == "2024"
    assert items[1].url.endswith("/catalog/datasets/nb-1er/exports/csv?delimiter=%3B")


def item(url=f"{BASE}/f/24") -> Item:
    return Item(url, Path("idfm/x/file.zip"), "histo", "2024", "ODbL", "2026-09-01")


def test_download_writes_file_and_manifest_once(tmp_path):
    s = make_settings(tmp_path)
    body = b"zip-bytes" * 1000
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(200, content=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))

    entry = download(client, item(), s)
    again = download(client, item(), s)

    assert (s.raw_dir / "idfm/x/file.zip").read_bytes() == body
    assert entry["sha256"] == hashlib.sha256(body).hexdigest()
    assert entry["bytes"] == len(body)
    assert again is None, "existing files in data/raw must not be re-downloaded"
    assert len(calls) == 1
    lines = (s.raw_dir / "manifest.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["source_url"] == f"{BASE}/f/24"


def test_download_retries_server_errors_then_succeeds(tmp_path):
    s = make_settings(tmp_path)
    responses = iter([httpx.Response(503), httpx.Response(200, content=b"ok")])
    client = httpx.Client(transport=httpx.MockTransport(lambda r: next(responses)))

    entry = download(client, item(), s, sleep=lambda _: None)

    assert entry["bytes"] == 2


def test_download_failure_leaves_no_file(tmp_path):
    s = make_settings(tmp_path)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404)))

    with pytest.raises(httpx.HTTPStatusError):
        download(client, item(), s, sleep=lambda _: None)

    assert not list((s.raw_dir / "idfm/x").iterdir())
    assert not (s.raw_dir / "manifest.jsonl").exists()


def test_repo_config_has_ingest_section():
    s = Settings.from_config(load_config(REPO_ROOT))
    assert s.base_url.startswith("https://data.iledefrance-mobilites.fr/")
    assert len(s.quarterly_datasets) == 8
    assert s.raw_dir.name == "raw"
