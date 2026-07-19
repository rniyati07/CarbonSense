import datetime
import json
from collections.abc import Sequence
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Finding


class FindingRepository(Protocol):
    def save_all(self, findings: Sequence[Finding]) -> None: ...


class DatabaseFindingRepository:
    def __init__(self, get_connection: Any):
        self._get_connection = get_connection

    def save_all(self, findings: Sequence[Finding]) -> None:
        if not findings:
            return

        conn = self._get_connection()
        try:
            for f in findings:
                # Basic representation of postgres insert
                # tstzrange requires string format
                conn.execute(
                    """
                    INSERT INTO findings (
                        finding_id, tenant_id, building_id, circuit_id, layer_origin,
                        evidence_window, confidence, status, explainability_bundle
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        tstzrange(%s, %s, '[]'), %s, %s, %s
                    )
                    """,
                    (
                        str(f.finding_id),
                        str(f.tenant_id),
                        str(f.building_id),
                        str(f.circuit_id) if f.circuit_id else None,
                        f.layer_origin,
                        f.evidence_window_start,
                        f.evidence_window_end,
                        f.confidence,
                        f.status,
                        json.dumps(f.explainability_bundle.model_dump(mode="json")),
                    ),
                )
            if hasattr(conn, "commit"):
                conn.commit()
        finally:
            conn.close()


class InMemoryFindingRepository:
    def __init__(self) -> None:
        self.findings: list[Finding] = []

    def save_all(self, findings: Sequence[Finding]) -> None:
        self.findings.extend(findings)


class RuleRegistryRepository(Protocol):
    def get_registered_version(self, rule_id: str) -> int | None: ...


class DatabaseRuleRegistryRepository:
    def __init__(self, get_connection: Any):
        self._get_connection = get_connection

    def get_registered_version(self, rule_id: str) -> int | None:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT version FROM rule_registry "
                "WHERE rule_id = %s ORDER BY version DESC LIMIT 1",
                (rule_id,),
            )
            row = cursor.fetchone()
            return row[0] if row else None
        finally:
            conn.close()


class InMemoryRuleRegistryRepository:
    def __init__(self, versions: dict[str, int] | None = None) -> None:
        self.versions = versions or {}

    def get_registered_version(self, rule_id: str) -> int | None:
        return self.versions.get(rule_id)


# ---------------------------------------------------------------------------
# ENG-2c-wiring addition: fetch the inputs process_readings() needs.
#
# DomainRuleEngineService.process_readings(tenant_id, building_id,
# building_context, readings, circuit_types) has always required its caller
# to supply readings/building_context/circuit_types directly -- nothing in
# this package could fetch them from the database. This is that missing
# piece, following the same async-SQLAlchemy-session, tenant-scoped-caller
# pattern already established by services/calibration/repository.py and
# services/drift_detection/repository.py (NOT the older sync get_connection()
# pattern used by FindingRepository/RuleRegistryRepository above, which
# predates that convention). The caller is expected to have already entered
# shared.auth.tenant_context.tenant_scope(session, tenant_id), exactly as
# the confidence_calibration and drift_detection activities already do.
# ---------------------------------------------------------------------------


class RulesEngineReadingsRepository:
    """Fetches normalized_readings, building context, and circuit types
    for a (tenant_id, building_id, window) needed by process_readings()."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_readings(
        self,
        tenant_id: UUID,
        building_id: UUID,
        window_start: datetime.datetime,
        window_end: datetime.datetime,
    ) -> list[dict[str, Any]]:
        """Return pass/degraded readings as plain dicts.

        process_readings() accepts dict or attribute-style readings (see
        DictToObject in service.py) -- dicts avoid depending on
        services.ingestion.models.NormalizedReading's stricter required
        fields (source_system, ingestion_timestamp, normalization_version)
        that aren't relevant to rule evaluation and aren't selected here.
        """
        stmt = text(
            """
            SELECT nr.circuit_id, nr.ts, nr.kwh, nr.data_quality_status
            FROM normalized_readings nr
            JOIN submeter_circuits sc ON nr.circuit_id = sc.circuit_id
            WHERE sc.building_id = :building_id
              AND nr.ts >= :window_start
              AND nr.ts <= :window_end
              AND nr.data_quality_status IN ('pass', 'degraded')
            ORDER BY nr.ts
            """
        )
        result = await self._session.execute(
            stmt,
            {
                "building_id": str(building_id),
                "window_start": window_start,
                "window_end": window_end,
            },
        )
        return [
            {
                "circuit_id": row.circuit_id,
                "ts": row.ts,
                "kwh": row.kwh,
                "data_quality_status": row.data_quality_status,
            }
            for row in result.fetchall()
        ]

    async def get_circuit_types(self, building_id: UUID) -> dict[UUID, str]:
        stmt = text(
            "SELECT circuit_id, circuit_type FROM submeter_circuits "
            "WHERE building_id = :building_id"
        )
        result = await self._session.execute(stmt, {"building_id": str(building_id)})
        return {row.circuit_id: row.circuit_type for row in result.fetchall()}

    async def get_building_context(self, building_id: UUID) -> dict[str, Any]:
        """Return the declared_unoccupied_baseline/occupancy_schedule pair the
        shipped rule YAMLs (hvac_after_hours_v3, scheduling_violation_v1,
        weekend_vampire_load_v1) reference as `building.declared_unoccupied_baseline`
        / `building.occupancy_schedule` -- exact attribute names confirmed
        against those YAML files, not guessed.
        """
        stmt = text(
            """
            SELECT building_type, climate_zone, declared_unoccupied_baseline,
                   declared_occupancy_schedule
            FROM buildings
            WHERE building_id = :building_id
            """
        )
        result = await self._session.execute(stmt, {"building_id": str(building_id)})
        row = result.fetchone()
        if row is None:
            return {"declared_unoccupied_baseline": 0.0, "occupancy_schedule": None}
        return {
            "building_type": row.building_type,
            "climate_zone": row.climate_zone,
            "declared_unoccupied_baseline": row.declared_unoccupied_baseline or 0.0,
            "occupancy_schedule": row.declared_occupancy_schedule,
        }


# ---------------------------------------------------------------------------
# ENG-5b addition: the Findings API's read path. Nothing before ENG-5
# needed to SELECT findings back out with their full evidence window and
# bundle -- every prior consumer (ExplainabilityRepository, the
# Optimization Engine's get_justifying_findings()) either only writes or
# only needs a partial projection. This is the first full row->Finding
# reconstruction, following the same async-SQLAlchemy-session pattern as
# every other repository in this module.
# ---------------------------------------------------------------------------

_FINDING_SELECT_COLUMNS = """
    finding_id, tenant_id, building_id, circuit_id, layer_origin, detected_at,
    lower(evidence_window) AS window_start, upper(evidence_window) AS window_end,
    confidence, status, explainability_bundle
"""


def _row_to_finding(row: Any) -> Finding:
    bundle = row.explainability_bundle
    if isinstance(bundle, str):
        bundle = json.loads(bundle)
    return Finding(
        finding_id=row.finding_id,
        tenant_id=row.tenant_id,
        building_id=row.building_id,
        circuit_id=row.circuit_id,
        layer_origin=row.layer_origin,
        detected_at=row.detected_at,
        evidence_window_start=row.window_start,
        evidence_window_end=row.window_end,
        confidence=row.confidence,
        status=row.status,
        explainability_bundle=bundle,
    )


class FindingQueryRepository:
    """Read path for the Findings API (TRD v2.0 §7.1): list with filters,
    fetch one. Always tenant_id-filtered explicitly, in addition to
    whatever the caller's tenant_scope(session, tenant_id) RLS context
    already enforces -- defense in depth, matching this repository
    module's existing convention.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_findings(
        self,
        tenant_id: UUID,
        building_id: UUID | None = None,
        status: str | None = None,
        min_confidence: float | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Finding]:
        clauses = ["tenant_id = :tenant_id"]
        params: dict[str, Any] = {"tenant_id": str(tenant_id), "limit": limit, "offset": offset}

        if building_id is not None:
            clauses.append("building_id = :building_id")
            params["building_id"] = str(building_id)
        if status is not None:
            clauses.append("status = :status")
            params["status"] = status
        if min_confidence is not None:
            clauses.append("confidence >= :min_confidence")
            params["min_confidence"] = min_confidence

        # clauses is built only from a fixed whitelist of hardcoded column-name
        # literals above -- every actual value is bound via `params`, never
        # interpolated -- so this is not a real SQL-injection vector.
        stmt = text(
            f"""
            SELECT {_FINDING_SELECT_COLUMNS}
            FROM findings
            WHERE {" AND ".join(clauses)}
            ORDER BY detected_at DESC
            LIMIT :limit OFFSET :offset
            """  # noqa: S608
        )
        result = await self._session.execute(stmt, params)
        return [_row_to_finding(row) for row in result.fetchall()]

    async def get_finding(self, tenant_id: UUID, finding_id: UUID) -> Finding | None:
        stmt = text(
            f"""
            SELECT {_FINDING_SELECT_COLUMNS}
            FROM findings
            WHERE tenant_id = :tenant_id AND finding_id = :finding_id
            """  # noqa: S608
        )
        result = await self._session.execute(
            stmt, {"tenant_id": str(tenant_id), "finding_id": str(finding_id)}
        )
        row = result.fetchone()
        return _row_to_finding(row) if row is not None else None
