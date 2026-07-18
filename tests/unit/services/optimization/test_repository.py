from __future__ import annotations

import datetime
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from services.optimization.models import ModelQualityIncident
from services.optimization.repository import BuildingRecord, OptimizationRepository


def _mock_session_with_result(rows: list[SimpleNamespace] | None = None, one_row=None) -> AsyncMock:
    session = AsyncMock()
    result = AsyncMock()
    result.fetchall = lambda: rows or []
    result.fetchone = lambda: one_row
    session.execute.return_value = result
    return session


class TestGetBuilding:
    @pytest.mark.asyncio
    async def test_returns_none_when_building_missing(self) -> None:
        session = _mock_session_with_result(one_row=None)
        repo = OptimizationRepository(session)
        result = await repo.get_building(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_maps_row_to_building_record(self) -> None:
        row = SimpleNamespace(
            building_type="office",
            climate_zone="deccan",
            declared_tariff_schedule={"peak_rate_inr_per_kwh": 10.0},
            declared_rooftop_area_sqm=500.0,
            latitude=12.97,
            longitude=77.59,
        )
        session = _mock_session_with_result(one_row=row)
        repo = OptimizationRepository(session)
        result = await repo.get_building(uuid4())
        assert isinstance(result, BuildingRecord)
        assert result.building_type == "office"
        assert result.declared_rooftop_area_sqm == 500.0
        assert result.latitude == 12.97


class TestGetCircuits:
    @pytest.mark.asyncio
    async def test_maps_rows_to_circuit_info(self) -> None:
        circuit_id = uuid4()
        rows = [SimpleNamespace(circuit_id=circuit_id, circuit_type="hvac")]
        session = _mock_session_with_result(rows=rows)
        repo = OptimizationRepository(session)
        result = await repo.get_circuits(uuid4())
        assert len(result) == 1
        assert result[0].circuit_id == circuit_id
        assert result[0].circuit_type == "hvac"


class TestGetJustifyingFindings:
    @pytest.mark.asyncio
    async def test_extracts_rule_ids_from_bundle(self) -> None:
        finding_id, circuit_id = uuid4(), uuid4()
        bundle = {
            "rule_citations": [{"rule_id": "hvac_after_hours_v3", "version": 3, "citation": "x"}]
        }
        rows = [
            SimpleNamespace(
                finding_id=finding_id,
                circuit_id=circuit_id,
                layer_origin="domain_rule",
                confidence=None,
                explainability_bundle=bundle,
            )
        ]
        session = _mock_session_with_result(rows=rows)
        repo = OptimizationRepository(session)
        result = await repo.get_justifying_findings(uuid4())
        assert len(result) == 1
        assert result[0].finding_id == finding_id
        assert result[0].rule_ids == ("hvac_after_hours_v3",)

    @pytest.mark.asyncio
    async def test_handles_bundle_stored_as_json_string(self) -> None:
        finding_id = uuid4()
        bundle_json = json.dumps({"rule_citations": []})
        rows = [
            SimpleNamespace(
                finding_id=finding_id,
                circuit_id=None,
                layer_origin="ml_ensemble",
                confidence=0.6,
                explainability_bundle=bundle_json,
            )
        ]
        session = _mock_session_with_result(rows=rows)
        repo = OptimizationRepository(session)
        result = await repo.get_justifying_findings(uuid4())
        assert result[0].rule_ids == ()

    @pytest.mark.asyncio
    async def test_query_excludes_dismissed_findings(self) -> None:
        session = _mock_session_with_result(rows=[])
        repo = OptimizationRepository(session)
        await repo.get_justifying_findings(uuid4())
        stmt = session.execute.call_args.args[0]
        assert "dismissed" in str(stmt)


class TestGetReadingsByCircuit:
    @pytest.mark.asyncio
    async def test_delegates_to_stl_readings_repository(self) -> None:
        session = AsyncMock()
        building_id = uuid4()
        window_start = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
        window_end = window_start + datetime.timedelta(days=7)

        with patch(
            "services.stl_detection.repository.STLReadingsRepository.get_readings_by_circuit",
            AsyncMock(return_value={}),
        ) as mock_delegate:
            repo = OptimizationRepository(session)
            result = await repo.get_readings_by_circuit(building_id, window_start, window_end)

        mock_delegate.assert_awaited_once_with(building_id, window_start, window_end)
        assert result == {}


class TestSaveIncident:
    @pytest.mark.asyncio
    async def test_issues_insert_with_serialized_metadata(self) -> None:
        session = AsyncMock()
        repo = OptimizationRepository(session)
        incident = ModelQualityIncident(
            incident_id=uuid4(),
            tenant_id=uuid4(),
            building_id=uuid4(),
            scenario_model="load_shift_v1",
            incident_type="pct_reduction_out_of_range",
            severity="warning",
            message="test message",
            metadata={"violation_types": ["pct_reduction_out_of_range"]},
            created_at=datetime.datetime.now(datetime.UTC),
        )
        await repo.save_incident(incident)

        session.execute.assert_awaited_once()
        params = session.execute.call_args.args[1]
        assert params["incident_id"] == str(incident.incident_id)
        assert params["scenario_model"] == "load_shift_v1"
        assert json.loads(params["metadata"]) == {"violation_types": ["pct_reduction_out_of_range"]}
