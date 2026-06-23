from __future__ import annotations

import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from apps.worker.config import build_tls_config
from orchestration.temporal.activities.analysis_stubs import (
    confidence_calibration_activity,
    data_quality_gate_activity,
    feature_assembly_activity,
    ml_ensemble_activity,
    root_cause_attribution_activity,
    rule_engine_activity,
    stl_detection_activity,
)
from orchestration.temporal.activities.drift_detection_stub import drift_detection_activity
from orchestration.temporal.activities.hello_world import greet_activity
from orchestration.temporal.activities.retraining_stub import retraining_activity
from orchestration.temporal.workflows.analysis_pipeline import AnalysisPipelineWorkflow
from orchestration.temporal.workflows.drift_detection import DriftDetectionWorkflow
from orchestration.temporal.workflows.hello_world import HelloWorldWorkflow
from orchestration.temporal.workflows.retraining import RetrainingWorkflow
from shared.config.temporal import TemporalSettings


async def run_worker() -> None:
    settings = TemporalSettings()
    client = await Client.connect(
        settings.host,
        namespace=settings.namespace,
        tls=build_tls_config(settings),
    )
    worker = Worker(
        client,
        task_queue=settings.task_queue,
        workflows=[
            HelloWorldWorkflow,
            AnalysisPipelineWorkflow,
            DriftDetectionWorkflow,
            RetrainingWorkflow,
        ],
        activities=[
            greet_activity,
            data_quality_gate_activity,
            rule_engine_activity,
            stl_detection_activity,
            feature_assembly_activity,
            ml_ensemble_activity,
            confidence_calibration_activity,
            root_cause_attribution_activity,
            drift_detection_activity,
            retraining_activity,
        ],
    )
    await worker.run()


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
