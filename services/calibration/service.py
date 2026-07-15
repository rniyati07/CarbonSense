from __future__ import annotations

import logging
from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar
from uuid import UUID

from opentelemetry import metrics

from services.calibration.dto import CalibratedFinding, CalibratedScore
from services.calibration.mapie_wrapper import ConformalPredictor
from services.calibration.repository import CalibrationRepository
from services.ml_ensemble.models import EnsembleScoreRecord
from shared.config.calibration import CalibrationSettings

logger = logging.getLogger(__name__)

# OTel Metric for tracking empirical calibration coverage
meter = metrics.get_meter("carbonsense.services.calibration")
coverage_counter = meter.create_counter(
    name="confidence_coverage",
    description="Measures empirical calibration coverage (emitted bounds).",
    unit="1",
)

_K = TypeVar("_K", bound=Hashable)


@dataclass(frozen=True)
class _CalibratedItem(Generic[_K]):
    """Internal, entry-point-agnostic result of the shared calibration core."""

    key: _K
    lower: float
    upper: float
    is_cold_start: bool


class CalibrationService:
    def __init__(self, repository: CalibrationRepository) -> None:
        self.repository = repository
        self.settings = CalibrationSettings()

    # ------------------------------------------------------------------ #
    # Shared calibration core (ENG-2c-wiring refactor)
    #
    # Both entry points below -- calibrate_findings() (existing, DB-polling)
    # and calibrate_ensemble_scores() (new, takes scores as a parameter) --
    # differ only in how they obtain (key, score) pairs and what they do
    # with the result. The cold-start gating and ConformalPredictor logic
    # itself exists exactly once, here.
    # ------------------------------------------------------------------ #
    async def _calibrate_scores(
        self,
        tenant_id: UUID,
        building_id: UUID,
        scored_items: Sequence[tuple[_K, float]],
    ) -> list[_CalibratedItem[_K]]:
        if not scored_items:
            return []

        labels = await self.repository.get_calibration_set(
            tenant_id, building_id, self.settings.max_history_samples
        )
        is_cold_start = await self.repository.get_building_cold_start_flag(tenant_id, building_id)

        if is_cold_start or len(labels) < self.settings.min_calibration_samples:
            logger.info(
                "Cold start: active flag or insufficient calibration labels.",
                extra={
                    "tenant_id": str(tenant_id),
                    "building_id": str(building_id),
                    "is_cold_start": is_cold_start,
                    "label_count": len(labels),
                    "threshold": self.settings.min_calibration_samples,
                },
            )
            return [
                _CalibratedItem(key=key, lower=0.0, upper=1.0, is_cold_start=True)
                for key, _ in scored_items
            ]

        logger.info(
            "Normal calibration running.",
            extra={
                "tenant_id": str(tenant_id),
                "building_id": str(building_id),
                "label_count": len(labels),
            },
        )
        predictor = ConformalPredictor(
            target_confidence_level=self.settings.target_confidence_level
        )
        predictor.fit(labels)

        scores = [score for _, score in scored_items]
        bands = predictor.predict(scores)

        results: list[_CalibratedItem[_K]] = []
        for (key, _), (lower, upper) in zip(scored_items, bands, strict=True):
            coverage_counter.add(
                1,
                attributes={
                    "tenant_id": str(tenant_id),
                    "building_id": str(building_id),
                    "target_confidence": str(self.settings.target_confidence_level),
                },
            )
            results.append(_CalibratedItem(key=key, lower=lower, upper=upper, is_cold_start=False))
        return results

    # ------------------------------------------------------------------ #
    # Entry point 1 (existing): DB-polling, persists calibrated findings.
    # ------------------------------------------------------------------ #
    async def calibrate_findings(
        self, tenant_id: UUID, building_id: UUID, correlation_id: str
    ) -> None:
        """
        Orchestrates the confidence calibration layer (ENG-3f) against
        findings already sitting in the `findings` table with confidence
        IS NULL (domain-rule-only findings -- see the module-level note in
        services/explainability/repository.py for why ML/STL-sourced
        findings can't reach this table yet).
        """
        findings = await self.repository.get_uncalibrated_findings(
            tenant_id, building_id, correlation_id
        )
        if not findings:
            logger.info(
                "No uncalibrated findings found.",
                extra={
                    "tenant_id": str(tenant_id),
                    "building_id": str(building_id),
                    "correlation_id": correlation_id,
                },
            )
            return

        scored_items = [(f.finding_id, f.ml_anomaly_score) for f in findings]
        calibrated = await self._calibrate_scores(tenant_id, building_id, scored_items)

        target_pct = self.settings.target_confidence_level * 100
        calibrated_findings = [
            CalibratedFinding(
                finding_id=item.key,
                confidence_interval_lower=item.lower,
                confidence_interval_upper=item.upper,
                confidence_label=(
                    "Low confidence — still establishing baseline"
                    if item.is_cold_start
                    else f"Calibrated ({target_pct:.0f}% confidence)"
                ),
            )
            for item in calibrated
        ]

        await self.repository.save_calibrated_findings(tenant_id, calibrated_findings)
        logger.info(
            "Saved %d calibrated findings.",
            len(calibrated_findings),
            extra={
                "tenant_id": str(tenant_id),
                "building_id": str(building_id),
                "correlation_id": correlation_id,
            },
        )

    # ------------------------------------------------------------------ #
    # Entry point 2 (ENG-2c-wiring, new): scores passed directly by the
    # workflow, no DB read for the scores themselves, no persistence --
    # the caller (confidence_calibration_activity) carries the result
    # forward to Root-Cause Attribution rather than writing it to
    # `findings`, since no Finding exists yet at this point in the
    # pipeline (see services/explainability/repository.py).
    # ------------------------------------------------------------------ #
    async def calibrate_ensemble_scores(
        self,
        tenant_id: UUID,
        building_id: UUID,
        scores: Sequence[EnsembleScoreRecord],
    ) -> list[CalibratedScore]:
        """Calibrate confidence for ML Ensemble scores flagged anomalous.

        Only records with ensemble_is_anomalous=True are calibrated --
        non-anomalous readings don't become findings and don't need a
        confidence band.
        """
        anomalous = [s for s in scores if s.ensemble_is_anomalous]
        if not anomalous:
            return []

        scored_items = [((s.circuit_id, s.ts), _anomaly_score(s)) for s in anomalous]
        calibrated = await self._calibrate_scores(tenant_id, building_id, scored_items)

        return [
            CalibratedScore(
                circuit_id=item.key[0],
                ts=item.key[1],
                confidence_lower=item.lower,
                confidence_upper=item.upper,
                is_cold_start=item.is_cold_start,
            )
            for item in calibrated
        ]


def _anomaly_score(record: EnsembleScoreRecord) -> float:
    """PROPOSED (not yet ratified): if_score and ae_reconstruction_error are
    on different, incompatible scales (if_score ~ signed
    IsolationForest.decision_function output; ae_reconstruction_error is a
    non-negative, unbounded MSE) and no combination formula is specified
    anywhere in PRD/TRD/ROADMAP/DATA_AND_MODEL_STRATEGY. Prefers if_score
    when available, falling back to ae_reconstruction_error. Confirm with
    ML Lead/Product before treating this as settled, per
    DATA_AND_MODEL_STRATEGY.md's own convention for exactly this kind of
    undocumented parameter.
    """
    if record.if_score is not None:
        return record.if_score
    return record.ae_reconstruction_error or 0.0
