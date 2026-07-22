"""ENG-6b — batch feature-engineering pipeline.

Runs the identical STL Residual Detection (ENG-3c) -> Domain Rule Engine
(ENG-3b) -> Feature Assembly (ENG-3d-1) sequence
orchestration/temporal/activities/analysis_stubs.py's three activities
already run inside AnalysisPipelineWorkflow -- reusing the same service
classes (STLDetectionService, DomainRuleEngineService, FeatureAssembler)
and repositories directly, not a reimplementation. What's different here
is the execution context: a plain async function callable from a script or
test, not a Temporal activity, so a bulk-ingested public dataset's history
can be feature-engineered in one pass rather than waiting for
AnalysisPipelineWorkflow to run against it circuit-window by
circuit-window in real time.

Deliberately does NOT persist Domain Rule Engine Findings (unlike
rule_engine_activity, which does via ExplainabilityRepository). Findings
are customer-facing, surfaced on dashboards and in the Findings API; a
historical public-dataset backfill populating feature_store as training
data should not also manufacture "findings" against a real tenant's
building. process_readings()'s return value is used transiently here only
to derive rule-fire indicators for FeatureSetV1, matching exactly how
feature_assembly_activity itself consumes rule_engine_activity's output
(RuleFireEvent, not the persisted Finding rows).
"""

from __future__ import annotations

import datetime
import logging
from collections import defaultdict
from pathlib import Path
from uuid import UUID

from models.feature_store.feature_set_v1 import FeatureSetV1, FeatureSetV1STLFields
from models.feature_store.repository import FeatureStoreRepository
from services.ml_ensemble.feature_assembly import FeatureAssembler
from services.rules_engine.registry import RuleRegistry
from services.rules_engine.repository import RulesEngineReadingsRepository
from services.rules_engine.service import DomainRuleEngineService
from services.stl_detection.exceptions import CalendarLookupError
from services.stl_detection.repository import (
    InMemoryCalendarRepository,
    STLReadingsRepository,
    TimescaleCalendarRepository,
)
from services.stl_detection.service import STLDetectionService
from shared.auth.tenant_context import tenant_scope
from shared.database import get_session_factory

logger = logging.getLogger(__name__)


async def run_batch_feature_engineering(
    tenant_id: UUID,
    building_id: UUID,
    window_start: datetime.datetime,
    window_end: datetime.datetime,
    persist: bool = True,
) -> list[FeatureSetV1]:
    """Feature-engineer every circuit's readings for (tenant, building)
    within [window_start, window_end] and, by default, persist the result
    to the feature store.

    Returns the assembled FeatureSetV1 rows regardless of `persist`, so
    callers (a backfill script, an evaluation harness) can use them
    directly without a round-trip read.
    """
    import services.rules_engine as rules_engine_pkg

    rules_dir = Path(rules_engine_pkg.__file__).resolve().parent / "rules"
    registry = RuleRegistry(str(rules_dir))
    rule_service = DomainRuleEngineService(registry)

    factory = get_session_factory()
    async with factory() as session, tenant_scope(session, tenant_id):
        stl_readings_by_circuit = await STLReadingsRepository(session).get_readings_by_circuit(
            building_id, window_start, window_end
        )
        calendar_entries = await TimescaleCalendarRepository(session).fetch_calendar_entries(
            building_id, window_start.date(), window_end.date()
        )

        readings_repo = RulesEngineReadingsRepository(session)
        rule_engine_readings = await readings_repo.get_readings(
            tenant_id, building_id, window_start, window_end
        )
        circuit_types = await readings_repo.get_circuit_types(building_id)
        building_context = await readings_repo.get_building_context(building_id)

    findings = rule_service.process_readings(
        tenant_id=tenant_id,
        building_id=building_id,
        building_context=building_context,
        readings=rule_engine_readings,
        circuit_types=circuit_types,
    )
    rule_fires_by_circuit: dict[UUID, dict[datetime.datetime, dict[str, bool]]] = defaultdict(dict)
    for finding in findings:
        if finding.circuit_id is None or not finding.explainability_bundle.rule_citations:
            continue
        rule_id = finding.explainability_bundle.rule_citations[0].rule_id
        rule_fires_by_circuit[finding.circuit_id].setdefault(finding.evidence_window_start, {})[
            rule_id
        ] = True

    calendar_repo = InMemoryCalendarRepository(calendar_entries)
    stl_service = STLDetectionService(calendar_repo=calendar_repo)

    stl_fields_by_circuit: dict[UUID, dict[datetime.datetime, FeatureSetV1STLFields]] = defaultdict(
        dict
    )
    for circuit_id, readings in stl_readings_by_circuit.items():
        try:
            residuals = stl_service.analyse_circuit_window_with_repo(readings, building_id)
        except CalendarLookupError:
            logger.warning(
                "run_batch_feature_engineering: no calendar coverage for circuit=%s -- "
                "skipping STL for this circuit's window.",
                circuit_id,
            )
            continue
        for residual in residuals:
            stl_fields_by_circuit[residual.circuit_id][residual.ts] = (
                FeatureSetV1STLFields.from_stl_result(residual)
            )

    assembler = FeatureAssembler()
    features: list[FeatureSetV1] = []
    for circuit_id, readings in stl_readings_by_circuit.items():
        features.extend(
            assembler.assemble(
                readings=readings,
                stl_fields_by_ts=stl_fields_by_circuit.get(circuit_id, {}),
                rule_fires_by_ts=rule_fires_by_circuit.get(circuit_id, {}),
            )
        )

    if persist and features:
        async with factory() as save_session, tenant_scope(save_session, tenant_id):
            await FeatureStoreRepository(save_session).save_features(features)
            await save_session.commit()

    logger.info(
        "run_batch_feature_engineering: tenant=%s building=%s window=%s..%s -> %d features",
        tenant_id,
        building_id,
        window_start,
        window_end,
        len(features),
    )
    return features
