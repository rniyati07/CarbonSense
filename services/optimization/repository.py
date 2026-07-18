"""ENG-4 — Optimization Engine repository.

Follows the same async-SQLAlchemy-session, tenant-scoped-caller (RLS)
pattern as services/calibration/repository.py and
services/rules_engine/repository.py.

get_readings_by_circuit() composes services.stl_detection.repository's
STLReadingsRepository rather than re-implementing the identical
normalized_readings-by-circuit query a third time in this codebase (rules
engine and STL detection each already have their own version of it).
"""

from __future__ import annotations

import datetime
import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.ingestion.models import NormalizedReading
from services.optimization.interfaces import CircuitInfo, JustifyingFinding
from services.optimization.models import ModelQualityIncident
from services.stl_detection.repository import STLReadingsRepository


class BuildingRecord:
    def __init__(
        self,
        building_type: str,
        climate_zone: str | None,
        declared_tariff_schedule: dict[str, object] | None,
        declared_rooftop_area_sqm: float | None,
        latitude: float | None,
        longitude: float | None,
    ) -> None:
        self.building_type = building_type
        self.climate_zone = climate_zone
        self.declared_tariff_schedule = declared_tariff_schedule
        self.declared_rooftop_area_sqm = declared_rooftop_area_sqm
        self.latitude = latitude
        self.longitude = longitude


class OptimizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._readings_repo = STLReadingsRepository(session)

    async def get_building(self, building_id: UUID) -> BuildingRecord | None:
        stmt = text(
            """
            SELECT building_type, climate_zone, declared_tariff_schedule,
                   declared_rooftop_area_sqm, latitude, longitude
            FROM buildings
            WHERE building_id = :building_id
            """
        )
        result = await self._session.execute(stmt, {"building_id": str(building_id)})
        row = result.fetchone()
        if row is None:
            return None
        return BuildingRecord(
            building_type=row.building_type,
            climate_zone=row.climate_zone,
            declared_tariff_schedule=row.declared_tariff_schedule,
            declared_rooftop_area_sqm=row.declared_rooftop_area_sqm,
            latitude=row.latitude,
            longitude=row.longitude,
        )

    async def get_circuits(self, building_id: UUID) -> list[CircuitInfo]:
        stmt = text(
            "SELECT circuit_id, circuit_type FROM submeter_circuits "
            "WHERE building_id = :building_id"
        )
        result = await self._session.execute(stmt, {"building_id": str(building_id)})
        return [
            CircuitInfo(circuit_id=row.circuit_id, circuit_type=row.circuit_type)
            for row in result.fetchall()
        ]

    async def get_justifying_findings(self, building_id: UUID) -> list[JustifyingFinding]:
        """Findings eligible to justify a scenario (ENG-4c): every
        non-dismissed finding for the building. A dismissed finding was
        judged not-real by a human reviewer and must not justify a
        recommendation."""
        stmt = text(
            """
            SELECT finding_id, circuit_id, layer_origin, confidence, explainability_bundle
            FROM findings
            WHERE building_id = :building_id
              AND status != 'dismissed'
            """
        )
        result = await self._session.execute(stmt, {"building_id": str(building_id)})
        findings: list[JustifyingFinding] = []
        for row in result.fetchall():
            bundle = row.explainability_bundle
            if isinstance(bundle, str):
                bundle = json.loads(bundle)
            rule_citations = (bundle or {}).get("rule_citations") or []
            rule_ids = tuple(c["rule_id"] for c in rule_citations if "rule_id" in c)
            findings.append(
                JustifyingFinding(
                    finding_id=row.finding_id,
                    circuit_id=row.circuit_id,
                    layer_origin=row.layer_origin,
                    rule_ids=rule_ids,
                    confidence=row.confidence,
                )
            )
        return findings

    async def get_readings_by_circuit(
        self,
        building_id: UUID,
        window_start: datetime.datetime,
        window_end: datetime.datetime,
    ) -> dict[UUID, list[NormalizedReading]]:
        return await self._readings_repo.get_readings_by_circuit(
            building_id, window_start, window_end
        )

    async def save_incident(self, incident: ModelQualityIncident) -> None:
        stmt = text(
            """
            INSERT INTO model_quality_incidents (
                incident_id, tenant_id, building_id, scenario_model,
                incident_type, severity, message, metadata, created_at
            ) VALUES (
                :incident_id, :tenant_id, :building_id, :scenario_model,
                :incident_type, :severity, :message, :metadata, :created_at
            )
            """
        )
        await self._session.execute(
            stmt,
            {
                "incident_id": str(incident.incident_id),
                "tenant_id": str(incident.tenant_id),
                "building_id": str(incident.building_id),
                "scenario_model": incident.scenario_model,
                "incident_type": incident.incident_type,
                "severity": incident.severity,
                "message": incident.message,
                "metadata": json.dumps(incident.metadata),
                "created_at": incident.created_at,
            },
        )
