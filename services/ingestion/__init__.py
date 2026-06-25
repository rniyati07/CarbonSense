"""ENG-3a — Data Quality Gate.

Validates, normalizes, and classifies incoming meter data before it
enters the analysis pipeline. Publishes building.data.arrived on
pass/degraded batches; quarantined-only batches generate a tenant-scoped
alert instead.
"""

from services.ingestion.alert_store import AlertStore, InMemoryAlertStore
from services.ingestion.bounds_repository import BoundsRepository, InMemoryBoundsRepository
from services.ingestion.config import DataQualityGateConfig
from services.ingestion.event_publisher import DataQualityEventPublisher
from services.ingestion.models import (
    BatchQualityResult,
    CircuitInfo,
    NormalizedReading,
    RawIngestionBatch,
)
from services.ingestion.quality_gate import DataQualityGate

__all__ = [
    "AlertStore",
    "BatchQualityResult",
    "BoundsRepository",
    "CircuitInfo",
    "DataQualityEventPublisher",
    "DataQualityGate",
    "DataQualityGateConfig",
    "InMemoryAlertStore",
    "InMemoryBoundsRepository",
    "NormalizedReading",
    "RawIngestionBatch",
]
