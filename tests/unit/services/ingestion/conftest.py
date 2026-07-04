from __future__ import annotations

import csv
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from services.ingestion.config import DataQualityGateConfig
from services.ingestion.models import CircuitInfo, RawIngestionBatch

FIXTURES_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "ingestion"

HVAC_CIRCUIT_ID = UUID("00000000-0000-0000-0000-000000000001")
LIGHT_CIRCUIT_ID = UUID("00000000-0000-0000-0000-000000000002")
TENANT_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
BUILDING_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def load_csv_rows(filename: str) -> list[dict[str, Any]]:
    path = FIXTURES_DIR / filename
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def make_batch(
    filename: str,
    *,
    source_id: str = "default",
    ingestion_source: str = "csv_upload",
    source_timezone: str = "Asia/Kolkata",
    circuit_map: dict[str, CircuitInfo] | None = None,
) -> RawIngestionBatch:
    rows = load_csv_rows(filename)
    if circuit_map is None:
        circuit_map = default_circuit_map()
    return RawIngestionBatch(
        tenant_id=TENANT_ID,
        building_id=BUILDING_ID,
        source_id=source_id,
        ingestion_source=ingestion_source,
        raw_rows=rows,
        source_timezone=source_timezone,
        circuit_map=circuit_map,
    )


def default_circuit_map() -> dict[str, CircuitInfo]:
    return {
        "HVAC-001": CircuitInfo(circuit_id=HVAC_CIRCUIT_ID, circuit_type="hvac"),
        "LIGHT-001": CircuitInfo(circuit_id=LIGHT_CIRCUIT_ID, circuit_type="lighting"),
    }


@pytest.fixture()
def gate_config() -> DataQualityGateConfig:
    return DataQualityGateConfig()


@pytest.fixture()
def circuit_map() -> dict[str, CircuitInfo]:
    return default_circuit_map()
