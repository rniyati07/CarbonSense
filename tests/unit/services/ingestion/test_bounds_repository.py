"""ENG-3a-3 audit fix: BoundsRepository hot-reload tests."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from services.ingestion.bounds_repository import (
    FileBoundsRepository,
    InMemoryBoundsRepository,
)
from services.ingestion.config import BoundsConfig, BoundsEntry


@pytest.mark.unit
class TestInMemoryBoundsRepository:
    def test_returns_default_config(self) -> None:
        repo = InMemoryBoundsRepository()
        config = repo.get()
        assert isinstance(config, BoundsConfig)
        assert "hvac" in config.circuit_type_bounds

    def test_set_and_get(self) -> None:
        repo = InMemoryBoundsRepository()
        custom = BoundsConfig(
            circuit_type_bounds={"custom": BoundsEntry(min_kwh=1.0, max_kwh=99.0)},
        )
        repo.set(custom)
        result = repo.get()
        assert "custom" in result.circuit_type_bounds
        assert result.circuit_type_bounds["custom"].max_kwh == 99.0


@pytest.mark.unit
class TestFileBoundsRepository:
    def test_loads_from_json(self, tmp_path: Path) -> None:
        bounds_file = tmp_path / "bounds.json"
        bounds_file.write_text(json.dumps({
            "version": "2.0.0",
            "circuit_type_bounds": {
                "hvac": {"min_kwh": 0.0, "max_kwh": 1500.0},
            },
            "default_bounds": {"min_kwh": 0.0, "max_kwh": 3000.0},
        }))

        repo = FileBoundsRepository(bounds_file)
        config = repo.get()
        assert config.version == "2.0.0"
        assert config.circuit_type_bounds["hvac"].max_kwh == 1500.0
        assert config.default_bounds.max_kwh == 3000.0

    def test_hot_reload_on_file_change(self, tmp_path: Path) -> None:
        bounds_file = tmp_path / "bounds.json"
        bounds_file.write_text(json.dumps({
            "version": "1.0.0",
            "circuit_type_bounds": {
                "hvac": {"min_kwh": 0.0, "max_kwh": 2000.0},
            },
        }))

        repo = FileBoundsRepository(bounds_file)
        assert repo.get().circuit_type_bounds["hvac"].max_kwh == 2000.0

        time.sleep(0.05)
        bounds_file.write_text(json.dumps({
            "version": "2.0.0",
            "circuit_type_bounds": {
                "hvac": {"min_kwh": 0.0, "max_kwh": 999.0},
            },
        }))

        config = repo.get()
        assert config.circuit_type_bounds["hvac"].max_kwh == 999.0
        assert config.version == "2.0.0"

    def test_missing_file_returns_default(self, tmp_path: Path) -> None:
        repo = FileBoundsRepository(tmp_path / "nonexistent.json")
        config = repo.get()
        assert isinstance(config, BoundsConfig)
        assert "main_feed" in config.circuit_type_bounds

    def test_gate_uses_bounds_repo(self, tmp_path: Path) -> None:
        bounds_file = tmp_path / "bounds.json"
        bounds_file.write_text(json.dumps({
            "version": "1.0.0",
            "circuit_type_bounds": {
                "hvac": {"min_kwh": 0.0, "max_kwh": 0.001},
                "lighting": {"min_kwh": 0.0, "max_kwh": 0.001},
            },
            "default_bounds": {"min_kwh": 0.0, "max_kwh": 0.001},
        }))

        from services.ingestion.quality_gate import DataQualityGate
        from tests.unit.services.ingestion.conftest import make_batch

        repo = FileBoundsRepository(bounds_file)
        gate = DataQualityGate(bounds_repo=repo)
        batch = make_batch("clean_batch.csv")
        result = gate.process_batch(batch)
        assert result.quarantined_count > 0
        assert result.overall_status == "quarantined"
