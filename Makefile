.PHONY: setup test lint format check poll status compact backup ingest ingest-plan clean features backtest deep-export deep-score score

setup:
	uv sync

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

check: lint test

# Disruption logger (one poll; schedule it, see deploy/)
poll:
	uv run idf-disruptions poll

status:
	uv run idf-disruptions status

compact:
	uv run idf-disruptions compact

backup:
	./scripts/backup_live.sh

# Phase 1: download IDFM validations, stop reference and docs to data/raw (+ manifest)
ingest-plan:
	uv run idf-ingest plan

ingest:
	uv run idf-ingest run

# Phase 2: harmonized tables + data-quality report from data/raw
clean:
	uv run idf-clean all

# Phase 4: model features (calendar, weather, ticket ramp, station type)
features:
	uv run idf-features build

# Phase 5: rolling-origin backtest (baselines + LightGBM) -> data/processed/backtest/
backtest:
	uv run idf-backtest run

# v0: typical-week Crowding score -> data/processed/typical_week.parquet + app/public/data/*.json
score:
	uv run idf-score build

# Option C: inputs for deep models trained on a GPU elsewhere (notebooks/03_deep_colab.ipynb),
# then scoring of their forecasts against lgbm
deep-export:
	uv run idf-deep export

deep-score:
	uv run idf-deep score
