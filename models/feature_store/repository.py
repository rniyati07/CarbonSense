"""ENG-6 — Feature Store persistence.

The read side of the gap described in migration 0009's docstring:
FeatureAssembler (services/ml_ensemble/feature_assembly.py) has always
been able to *compute* FeatureSetV1 rows; nothing could previously save or
query them for reuse as training data. This repository is that missing
piece, following the same async-SQLAlchemy-session, tenant-scoped-caller
pattern as every other repository in this codebase (services/calibration/
repository.py, services/drift_detection/repository.py, etc.) -- the caller
is expected to have already entered
shared.auth.tenant_context.tenant_scope(session, tenant_id).
"""

from __future__ import annotations

import datetime
import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from models.feature_store.feature_set_v1 import FeatureSetV1


class FeatureStoreRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_features(self, features: list[FeatureSetV1]) -> None:
        """Upsert FeatureSetV1 rows. Re-assembling features for a window
        that already has rows (e.g. a re-triggered analysis run) overwrites
        rather than duplicating -- see migration 0009's docstring."""
        if not features:
            return

        stmt = text(
            """
            INSERT INTO feature_store (
                tenant_id, circuit_id, ts, feature_schema_version,
                rolling_baseline_kwh, peak_offpeak_split, after_hours_kwh_ratio,
                weekend_floor_load, rolling_efficiency_ratio, stl_residual_magnitude,
                day_type, rule_fire_indicators, low_data_quality
            ) VALUES (
                :tenant_id, :circuit_id, :ts, :feature_schema_version,
                :rolling_baseline_kwh, :peak_offpeak_split, :after_hours_kwh_ratio,
                :weekend_floor_load, :rolling_efficiency_ratio, :stl_residual_magnitude,
                :day_type, :rule_fire_indicators, :low_data_quality
            )
            ON CONFLICT (tenant_id, circuit_id, ts) DO UPDATE SET
                rolling_baseline_kwh = EXCLUDED.rolling_baseline_kwh,
                peak_offpeak_split = EXCLUDED.peak_offpeak_split,
                after_hours_kwh_ratio = EXCLUDED.after_hours_kwh_ratio,
                weekend_floor_load = EXCLUDED.weekend_floor_load,
                rolling_efficiency_ratio = EXCLUDED.rolling_efficiency_ratio,
                stl_residual_magnitude = EXCLUDED.stl_residual_magnitude,
                day_type = EXCLUDED.day_type,
                rule_fire_indicators = EXCLUDED.rule_fire_indicators,
                low_data_quality = EXCLUDED.low_data_quality
            """
        )
        for feature in features:
            await self._session.execute(
                stmt,
                {
                    "tenant_id": str(feature.tenant_id),
                    "circuit_id": str(feature.circuit_id),
                    "ts": feature.ts,
                    "feature_schema_version": feature.feature_schema_version,
                    "rolling_baseline_kwh": feature.rolling_baseline_kwh,
                    "peak_offpeak_split": feature.peak_offpeak_split,
                    "after_hours_kwh_ratio": feature.after_hours_kwh_ratio,
                    "weekend_floor_load": feature.weekend_floor_load,
                    "rolling_efficiency_ratio": feature.rolling_efficiency_ratio,
                    "stl_residual_magnitude": feature.stl_residual_magnitude,
                    "day_type": feature.day_type,
                    "rule_fire_indicators": json.dumps(feature.rule_fire_indicators),
                    "low_data_quality": feature.low_data_quality,
                },
            )

    async def get_features_for_building(
        self,
        tenant_id: UUID,
        building_id: UUID,
        window_start: datetime.datetime,
        window_end: datetime.datetime,
    ) -> list[FeatureSetV1]:
        """Every stored feature row for a building's circuits within a
        training window, ordered by timestamp. Joins submeter_circuits
        since feature_store itself is keyed by circuit_id, not
        building_id (matching normalized_readings' own shape)."""
        stmt = text(
            """
            SELECT fs.tenant_id, fs.circuit_id, fs.ts, fs.rolling_baseline_kwh,
                   fs.peak_offpeak_split, fs.after_hours_kwh_ratio, fs.weekend_floor_load,
                   fs.rolling_efficiency_ratio, fs.stl_residual_magnitude, fs.day_type,
                   fs.rule_fire_indicators, fs.low_data_quality
            FROM feature_store fs
            JOIN submeter_circuits sc ON fs.circuit_id = sc.circuit_id
            WHERE fs.tenant_id = :tenant_id
              AND sc.building_id = :building_id
              AND fs.ts >= :window_start
              AND fs.ts <= :window_end
            ORDER BY fs.ts
            """
        )
        result = await self._session.execute(
            stmt,
            {
                "tenant_id": str(tenant_id),
                "building_id": str(building_id),
                "window_start": window_start,
                "window_end": window_end,
            },
        )
        return [_row_to_feature(row) for row in result.fetchall()]


def _row_to_feature(row: Any) -> FeatureSetV1:
    rule_fire_indicators = row.rule_fire_indicators
    if isinstance(rule_fire_indicators, str):
        rule_fire_indicators = json.loads(rule_fire_indicators)
    return FeatureSetV1(
        tenant_id=row.tenant_id,
        circuit_id=row.circuit_id,
        ts=row.ts,
        rolling_baseline_kwh=row.rolling_baseline_kwh,
        peak_offpeak_split=row.peak_offpeak_split,
        after_hours_kwh_ratio=row.after_hours_kwh_ratio,
        weekend_floor_load=row.weekend_floor_load,
        rolling_efficiency_ratio=row.rolling_efficiency_ratio,
        stl_residual_magnitude=row.stl_residual_magnitude,
        day_type=row.day_type,
        rule_fire_indicators=rule_fire_indicators or {},
        low_data_quality=row.low_data_quality,
    )
