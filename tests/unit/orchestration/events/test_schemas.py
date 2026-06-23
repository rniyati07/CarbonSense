"""ENG-2b: Event schema serialization tests.

Verifies that events roundtrip through JSON serialization with all
required fields (tenant_id, building_id, correlation_id, event_id, timestamp).
"""

from __future__ import annotations

import datetime
from uuid import uuid4

import pytest

from orchestration.events.kafka.schemas.base import BaseEvent
from orchestration.events.kafka.schemas.data_arrived import BuildingDataArrivedEvent
from orchestration.events.kafka.serialization import from_json_dict, to_json_bytes


@pytest.mark.unit
def test_base_event_serialization_roundtrip() -> None:
    event = BaseEvent(
        event_id=uuid4(),
        tenant_id=uuid4(),
        building_id=uuid4(),
        correlation_id=uuid4(),
        timestamp=datetime.datetime.now(tz=datetime.UTC),
        event_type="test.event",
    )
    data = to_json_bytes(event)
    parsed = from_json_dict(data)
    assert parsed["event_type"] == "test.event"
    assert parsed["tenant_id"] == str(event.tenant_id)
    assert parsed["building_id"] == str(event.building_id)
    assert parsed["correlation_id"] == str(event.correlation_id)
    assert parsed["event_id"] == str(event.event_id)
    assert "timestamp" in parsed


@pytest.mark.unit
def test_building_data_arrived_event_roundtrip() -> None:
    event = BuildingDataArrivedEvent(
        event_id=uuid4(),
        tenant_id=uuid4(),
        building_id=uuid4(),
        correlation_id=uuid4(),
        timestamp=datetime.datetime.now(tz=datetime.UTC),
        event_type="building.data.arrived",
        data_quality_status="pass",
        batch_row_count=500,
        ingestion_source="csv_upload",
    )
    data = to_json_bytes(event)
    parsed = from_json_dict(data)
    assert parsed["event_type"] == "building.data.arrived"
    assert parsed["data_quality_status"] == "pass"
    assert parsed["batch_row_count"] == 500
    assert parsed["ingestion_source"] == "csv_upload"


@pytest.mark.unit
def test_all_required_fields_present() -> None:
    """Every event must contain the 5 mandatory fields per ENG-2b contract."""
    event = BuildingDataArrivedEvent(
        event_id=uuid4(),
        tenant_id=uuid4(),
        building_id=uuid4(),
        correlation_id=uuid4(),
        timestamp=datetime.datetime.now(tz=datetime.UTC),
        event_type="building.data.arrived",
        data_quality_status="degraded",
        batch_row_count=10,
        ingestion_source="smart_meter_api",
    )
    parsed = from_json_dict(to_json_bytes(event))
    required = {"event_id", "tenant_id", "building_id", "correlation_id", "timestamp"}
    assert required.issubset(parsed.keys())
