from __future__ import annotations

import logging
from uuid import UUID

from opentelemetry import metrics

from services.calibration.dto import CalibratedFinding
from services.calibration.mapie_wrapper import ConformalPredictor
from services.calibration.repository import CalibrationRepository
from shared.config.calibration import CalibrationSettings

logger = logging.getLogger(__name__)

# OTel Metric for tracking empirical calibration coverage
meter = metrics.get_meter("carbonsense.services.calibration")
coverage_counter = meter.create_counter(
    name="confidence_coverage",
    description="Measures empirical calibration coverage (emitted bounds).",
    unit="1",
)


class CalibrationService:
    def __init__(self, repository: CalibrationRepository) -> None:
        self.repository = repository
        self.settings = CalibrationSettings()

    async def calibrate_findings(
        self, tenant_id: UUID, building_id: UUID, correlation_id: str
    ) -> None:
        """
        Orchestrates the confidence calibration layer (ENG-3f).
        1. Fetch uncalibrated findings for this batch.
        2. Fetch the rolling calibration set (feedback labels) for this building.
        3. If cold_start (labels < threshold), apply conservative bands.
        4. Else, fit Mapie and predict confidence intervals.
        5. Save calibrated findings.
        """
        # 1. Fetch uncalibrated findings
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

        # 2. Fetch rolling calibration set and explicit building cold-start flag
        labels = await self.repository.get_calibration_set(
            tenant_id, building_id, self.settings.max_history_samples
        )
        is_cold_start = await self.repository.get_building_cold_start_flag(tenant_id, building_id)

        calibrated_findings: list[CalibratedFinding] = []

        # 3. Check Cold Start Condition
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
            for finding in findings:
                calibrated_findings.append(
                    CalibratedFinding(
                        finding_id=finding.finding_id,
                        confidence_interval_lower=0.0,
                        confidence_interval_upper=1.0,
                        confidence_label="Low confidence — still establishing baseline",
                    )
                )
        else:
            # 4. Normal Calibration using Conformal Prediction
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

            scores = [f.ml_anomaly_score for f in findings]
            bands = predictor.predict(scores)

            for finding, (lower, upper) in zip(findings, bands, strict=True):
                # Emit metric for empirical coverage tracking
                coverage_counter.add(
                    1,
                    attributes={
                        "tenant_id": str(tenant_id),
                        "building_id": str(building_id),
                        "target_confidence": str(self.settings.target_confidence_level),
                    },
                )

                target_pct = self.settings.target_confidence_level * 100
                calibrated_findings.append(
                    CalibratedFinding(
                        finding_id=finding.finding_id,
                        confidence_interval_lower=lower,
                        confidence_interval_upper=upper,
                        confidence_label=f"Calibrated ({target_pct:.0f}% confidence)",
                    )
                )

        # 5. Persist calibrated findings
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
