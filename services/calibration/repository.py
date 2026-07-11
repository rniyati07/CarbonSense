from __future__ import annotations

import json
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.calibration.dto import CalibratedFinding, FeedbackLabel, UncalibratedFinding


class CalibrationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_building_cold_start_flag(self, tenant_id: UUID, building_id: UUID) -> bool:
        """
        Fetch the explicit cold_start boolean flag for a building.
        """
        stmt = text(
            """
            SELECT cold_start
            FROM buildings
            WHERE tenant_id = :tenant_id
              AND building_id = :building_id
            """
        )
        result = await self._session.execute(
            stmt, {"tenant_id": str(tenant_id), "building_id": str(building_id)}
        )
        row = result.fetchone()
        return bool(row[0]) if row else True

    async def get_uncalibrated_findings(
        self, tenant_id: UUID, building_id: UUID, correlation_id: str
    ) -> Sequence[UncalibratedFinding]:
        """
        Fetch uncalibrated findings (ML anomaly scores, STL residuals, Rule-fire context)
        produced by ENG-3b, ENG-3c, and ENG-3d.

        Since these upstream contracts exist on parallel branches and their exact
        SQLAlchemy ORM models are not present here, we use raw SQL to fulfill
        the minimum temporary contract exactly as documented.
        """
        # We query the unified `findings` table where confidence is null (uncalibrated)
        # Note: Depending on the upstream branch implementation, this may join with
        # `feature_set_v1` or equivalent tables. We provide the minimal contract.
        stmt = text(
            """
            SELECT finding_id, circuit_id, confidence, layer_origin, explainability_bundle
            FROM findings
            WHERE tenant_id = :tenant_id
              AND building_id = :building_id
              AND confidence IS NULL
            """
        )
        result = await self._session.execute(
            stmt, {"tenant_id": str(tenant_id), "building_id": str(building_id)}
        )

        findings = []
        for row in result.fetchall():
            bundle = row[4] or {}
            findings.append(
                UncalibratedFinding(
                    finding_id=row[0],
                    circuit_id=row[1],
                    ml_anomaly_score=bundle.get("ml_anomaly_score", 0.0),
                    stl_residual=bundle.get("stl_residual"),
                    rule_flags=bundle.get("rule_flags", []),
                )
            )
        return findings

    async def get_calibration_set(
        self, tenant_id: UUID, building_id: UUID, max_samples: int
    ) -> Sequence[FeedbackLabel]:
        """
        Fetch the rolling calibration set (feedback_labels) for a specific building.
        Oldest labels expire automatically via the LIMIT / ORDER BY.
        Never pools tenants or buildings (TRD v2.0).
        """
        stmt = text(
            """
            SELECT f.feedback_id, f.action, fd.explainability_bundle
            FROM feedback_labels f
            JOIN findings fd ON f.finding_id = fd.finding_id
            WHERE f.tenant_id = :tenant_id
              AND fd.building_id = :building_id
            ORDER BY f.created_at DESC
            LIMIT :max_samples
            """
        )
        result = await self._session.execute(
            stmt,
            {
                "tenant_id": str(tenant_id),
                "building_id": str(building_id),
                "max_samples": max_samples,
            },
        )

        labels = []
        for row in result.fetchall():
            bundle = row[2] or {}
            labels.append(
                FeedbackLabel(
                    action=row[1],
                    ml_anomaly_score=bundle.get("ml_anomaly_score", 0.0),
                )
            )
        return labels

    async def save_calibrated_findings(
        self, tenant_id: UUID, findings: Sequence[CalibratedFinding]
    ) -> None:
        """
        Persist the calibrated confidence intervals and labels back to the database.

        INTERFACE FIX (pre-ENG-4 integration audit): this previously wrote a
        `calibration: {lower_bound, upper_bound, label}` key, which does not
        match the canonical ExplainabilityBundle contract (TRD v2.0 3.7,
        services/explainability/models.py ConfidenceBand) of
        `confidence_band: {lower, upper, method}`. Fixed to write the
        canonical key/shape so a later SHAP/bundle-assembly pass (ENG-3g)
        finds calibration output where it actually looks for it.

        ARCHITECTURAL GAP, not fixed here (needs a Product/Architecture
        decision, not a unilateral patch): per TRD v2.0 3.6-3.7, calibration
        runs *before* Root-Cause Attribution assembles the Explainability
        Bundle, and `findings.explainability_bundle` is NOT NULL in the
        canonical schema -- so a row this repository can update by
        `jsonb_set`-patching an existing bundle. But the ExplainabilityBundle
        contract now requires top_features/confidence_band together for any
        ml_ensemble/stl_residual finding (see explainability/models.py's
        enforce_probabilistic_fields_for_ml_or_stl validator, added during
        this same integration pass) -- meaning an ML/STL-sourced finding
        cannot legally exist in `findings` yet at the point calibration runs,
        unless it was already bundled with a placeholder confidence_band.
        This repository's raw-SQL jsonb_set patch works structurally (it
        does not fail), but resolving *how* an ML/STL finding gets its first,
        pre-calibration bundle is out of scope for an integration pass and
        needs an explicit design decision before ENG-4.

        Also note: `CalibratedFinding.confidence_label` (the human-readable
        "Low confidence -- still establishing baseline" / "Calibrated (90%
        confidence)" string) is no longer persisted here -- the canonical
        ConfidenceBand contract has no slot for free-text labels, only
        lower/upper/method. Flagged, not silently dropped: whether that label
        text should be derived downstream (e.g. by the Reporting Service's
        prompt from lower/upper/method directly) or added as a real field on
        the canonical contract is a product decision, not one this
        integration pass makes unilaterally.
        """
        if not findings:
            return

        stmt = text(
            """
            UPDATE findings
            SET confidence = :confidence,
                explainability_bundle = jsonb_set(
                    explainability_bundle,
                    '{confidence_band}',
                    :confidence_band_json::jsonb
                )
            WHERE finding_id = :finding_id
              AND tenant_id = :tenant_id
            """
        )
        for finding in findings:
            confidence_band_json = json.dumps(
                {
                    "lower": finding.confidence_interval_lower,
                    "upper": finding.confidence_interval_upper,
                    "method": "conformal_prediction",
                }
            )
            # We map confidence_interval_upper as the primary point-estimate for 'confidence'
            # (or the midpoint depending on product choice, we'll use upper bound)
            await self._session.execute(
                stmt,
                {
                    "confidence": finding.confidence_interval_upper,
                    "confidence_band_json": confidence_band_json,
                    "finding_id": str(finding.finding_id),
                    "tenant_id": str(tenant_id),
                },
            )
