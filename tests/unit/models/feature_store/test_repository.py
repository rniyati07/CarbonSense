from __future__ import annotations

import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from models.feature_store.feature_set_v1 import FeatureSetV1
from models.feature_store.repository import FeatureStoreRepository


def _mock_session_with_result(rows: list | None = None) -> AsyncMock:
    session = AsyncMock()
    result = AsyncMock()
    result.fetchall = lambda: rows or []
    session.execute.return_value = result
    return session


def _make_feature(tenant_id, circuit_id, ts) -> FeatureSetV1:
    return FeatureSetV1(
        tenant_id=tenant_id,
        circuit_id=circuit_id,
        ts=ts,
        rolling_baseline_kwh=10.0,
        peak_offpeak_split=0.5,
        after_hours_kwh_ratio=0.1,
        weekend_floor_load=None,
        rolling_efficiency_ratio=1.0,
        stl_residual_magnitude=0.2,
        day_type="business_day",
        rule_fire_indicators={"hvac_after_hours_v3": True},
        low_data_quality=False,
    )


@pytest.mark.unit
class TestSaveFeatures:
    @pytest.mark.asyncio
    async def test_no_op_for_empty_list(self) -> None:
        session = AsyncMock()
        repo = FeatureStoreRepository(session)
        await repo.save_features([])
        session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_issues_one_upsert_per_feature(self) -> None:
        session = AsyncMock()
        repo = FeatureStoreRepository(session)
        tenant_id, circuit_id = uuid4(), uuid4()
        ts = datetime.datetime(2026, 1, 5, tzinfo=datetime.UTC)
        features = [
            _make_feature(tenant_id, circuit_id, ts),
            _make_feature(tenant_id, circuit_id, ts + datetime.timedelta(hours=1)),
        ]

        await repo.save_features(features)

        assert session.execute.await_count == 2
        first_params = session.execute.call_args_list[0].args[1]
        assert first_params["tenant_id"] == str(tenant_id)
        assert first_params["circuit_id"] == str(circuit_id)
        assert first_params["rule_fire_indicators"] == '{"hvac_after_hours_v3": true}'


@pytest.mark.unit
class TestGetFeaturesForBuilding:
    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_rows(self) -> None:
        session = _mock_session_with_result(rows=[])
        repo = FeatureStoreRepository(session)
        now = datetime.datetime.now(datetime.UTC)
        result = await repo.get_features_for_building(uuid4(), uuid4(), now, now)
        assert result == []

    @pytest.mark.asyncio
    async def test_maps_rows_to_feature_set_v1(self) -> None:
        tenant_id, circuit_id = uuid4(), uuid4()
        ts = datetime.datetime(2026, 1, 5, tzinfo=datetime.UTC)
        row = SimpleNamespace(
            tenant_id=tenant_id,
            circuit_id=circuit_id,
            ts=ts,
            rolling_baseline_kwh=10.0,
            peak_offpeak_split=0.5,
            after_hours_kwh_ratio=0.1,
            weekend_floor_load=None,
            rolling_efficiency_ratio=1.0,
            stl_residual_magnitude=0.2,
            day_type="business_day",
            rule_fire_indicators='{"hvac_after_hours_v3": true}',
            low_data_quality=False,
        )
        session = _mock_session_with_result(rows=[row])
        repo = FeatureStoreRepository(session)

        now = datetime.datetime.now(datetime.UTC)
        result = await repo.get_features_for_building(tenant_id, uuid4(), now, now)

        assert len(result) == 1
        assert isinstance(result[0], FeatureSetV1)
        assert result[0].circuit_id == circuit_id
        assert result[0].rule_fire_indicators == {"hvac_after_hours_v3": True}
