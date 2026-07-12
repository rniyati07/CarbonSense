"""ENG-2c-wiring — persists the fully-assembled finding + ExplainabilityBundle
that root_cause_attribution_activity produces.

Nothing currently INSERTs an ML/STL-sourced finding: rules_engine's own
DatabaseFindingRepository (services/rules_engine/repository.py) only
handles domain-rule-only findings, which can be bundled immediately since
they're deterministic. An ML/STL-sourced finding can't be validly
constructed as an ExplainabilityBundle until SHAP (top_features) and
Confidence Calibration (confidence_band) have both run -- by which point
the pipeline is at Root-Cause Attribution, the last layer before Human
Review. This repository is that layer's single INSERT point: unlike
Confidence Calibration's save_calibrated_findings() (which UPDATEs/patches
an already-existing row -- a pattern that assumes the row already exists),
here the row does not exist yet, so this always INSERTs the finding and
its complete bundle together, in one write, satisfying the
explainability_bundle NOT NULL constraint on the first attempt rather than
via a partial-then-patched insert.

Follows the same async-SQLAlchemy-session, tenant-scoped-caller pattern as
services/calibration/repository.py and services/drift_detection/repository.py.
"""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.rules_engine.models import Finding


class ExplainabilityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_finding(self, finding: Finding) -> None:
        """INSERT a finding with its complete ExplainabilityBundle.

        finding.explainability_bundle must already be a fully-assembled,
        valid ExplainabilityBundle (see BundleAssembler) -- this method
        does no validation of its own beyond what the Pydantic model
        already enforced at construction time.
        """
        stmt = text(
            """
            INSERT INTO findings (
                finding_id, tenant_id, building_id, circuit_id, layer_origin,
                evidence_window, confidence, status, explainability_bundle
            ) VALUES (
                :finding_id, :tenant_id, :building_id, :circuit_id, :layer_origin,
                tstzrange(:window_start, :window_end, '[]'), :confidence, :status,
                :explainability_bundle
            )
            """
        )
        await self._session.execute(
            stmt,
            {
                "finding_id": str(finding.finding_id),
                "tenant_id": str(finding.tenant_id),
                "building_id": str(finding.building_id),
                "circuit_id": str(finding.circuit_id) if finding.circuit_id else None,
                "layer_origin": finding.layer_origin,
                "window_start": finding.evidence_window_start,
                "window_end": finding.evidence_window_end,
                "confidence": finding.confidence,
                "status": finding.status,
                "explainability_bundle": json.dumps(
                    finding.explainability_bundle.model_dump(mode="json")
                ),
            },
        )

    async def save_findings(self, findings: list[Finding]) -> None:
        """Convenience batch wrapper around save_finding()."""
        for finding in findings:
            await self.save_finding(finding)
