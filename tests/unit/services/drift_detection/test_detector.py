import datetime
import uuid

import pytest

from services.drift_detection.config import DriftDetectionConfig
from services.drift_detection.detector import detect_drift
from services.drift_detection.models import DriftStatus, TrendDirection
from services.ingestion.models import NormalizedReading


@pytest.fixture
def base_readings():
    tenant_id = uuid.uuid4()
    circuit_id = uuid.uuid4()
    now = datetime.datetime.now(datetime.UTC)

    # Create 15 readings with a stable ratio around 1.0
    readings = []
    for i in range(15):
        readings.append(
            NormalizedReading(
                tenant_id=tenant_id,
                circuit_id=circuit_id,
                ts=now - datetime.timedelta(days=15-i),
                kwh=10.0,
                rolling_baseline_kwh=10.0,
                data_quality_status="pass",
                schema_version="v1",
                source_system="db",
                ingestion_timestamp=now,
                normalization_version="v1"
            )
        )
    return readings


@pytest.mark.unit
def test_detect_drift_stable(base_readings):
    config = DriftDetectionConfig()
    result = detect_drift(
        tenant_id=base_readings[0].tenant_id,
        building_id=uuid.uuid4(),
        readings=base_readings,
        config=config,
        building_type="office",
    )

    assert result.status == DriftStatus.STABLE
    assert result.trend_direction == TrendDirection.NONE


@pytest.mark.unit
def test_detect_drift_increasing(base_readings):
    # Introduce an increasing trend (actual kwh > baseline)
    for i, r in enumerate(base_readings):
        r.kwh = 10.0 + (i * 0.5)

    config = DriftDetectionConfig()
    result = detect_drift(
        tenant_id=base_readings[0].tenant_id,
        building_id=uuid.uuid4(),
        readings=base_readings,
        config=config,
        building_type="office",
    )

    assert result.status == DriftStatus.DRIFTING
    assert result.trend_direction == TrendDirection.INCREASING


@pytest.mark.unit
def test_detect_drift_insufficient_data(base_readings):
    # Only 5 data points
    short_readings = base_readings[:5]

    config = DriftDetectionConfig()
    result = detect_drift(
        tenant_id=short_readings[0].tenant_id,
        building_id=uuid.uuid4(),
        readings=short_readings,
        config=config,
        building_type="office",
    )

    # Since only 5 valid readings exist, it defaults to STABLE
    assert result.status == DriftStatus.STABLE
    assert result.trend_direction == TrendDirection.NONE


@pytest.mark.unit
def test_detect_drift_ignores_quarantined(base_readings):
    # Introduce an increasing trend, but mark them quarantined
    for i, r in enumerate(base_readings):
        r.kwh = 10.0 + (i * 0.5)
        if i >= 5:
            r.data_quality_status = "quarantined"

    config = DriftDetectionConfig()
    result = detect_drift(
        tenant_id=base_readings[0].tenant_id,
        building_id=uuid.uuid4(),
        readings=base_readings,
        config=config,
        building_type="office",
    )

    # Since only 5 valid readings exist, it should return STABLE
    assert result.status == DriftStatus.STABLE
