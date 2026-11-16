"""Load config.toml (+ config.local.toml overrides) and the .env file."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]


def find_upwards(name: str, start: Path) -> Path | None:
    """Return the first `name` found in `start` or any of its parents."""
    for folder in [start, *start.parents]:
        candidate = folder / name
        if candidate.is_file():
            return candidate
    return None


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge `override` into a copy of `base`, recursing into nested tables."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(root: Path = REPO_ROOT) -> dict[str, Any]:
    """Read config.toml, apply config.local.toml if present, resolve [paths] against `root`."""
    with open(root / "config.toml", "rb") as f:
        config = tomllib.load(f)
    local = root / "config.local.toml"
    if local.is_file():
        with open(local, "rb") as f:
            config = deep_merge(config, tomllib.load(f))
    config["paths"] = {k: str((root / v).resolve()) for k, v in config.get("paths", {}).items()}
    return config


def load_env(start: Path = REPO_ROOT) -> Path | None:
    """Load the nearest .env from `start` or a parent folder; existing env vars win."""
    path = find_upwards(".env", start)
    if path is not None:
        load_dotenv(path, override=False)
    return path


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set; add it to .env (see .env.example)")
    return value
