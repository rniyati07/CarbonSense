from __future__ import annotations

import datetime
from typing import List, Optional
from uuid import UUID

import pymannkendall as mk
import structlog

from services.ingestion.models import NormalizedReading
from services.drift_detection.config import DriftDetectionConfig
from services.drift_detection.models import DriftResult, DriftStatus, TrendDirection

def detect_drift(
    tenant_id: UUID,
    building_id: UUID,
    readings: List[NormalizedReading],
    config: DriftDetectionConfig,
    building_type: str,
    climate_zone: Optional[str] = None,
) -> DriftResult:
    """
    Detects if a building's energy efficiency ratio is drifting.
    
    The efficiency ratio is calculated as `actual_kwh / rolling_baseline_kwh`.
    Drift is determined using the Mann-Kendall trend test.
    """
    logger = structlog.get_logger(__name__).bind(
        tenant_id=str(tenant_id),
        building_id=str(building_id),
    )
    logger.info("Starting drift detection evaluation")
    
    threshold_config = config.get_threshold(building_type, climate_zone)
    now = datetime.datetime.now(datetime.timezone.utc)
    
    # Filter readings: must have both actual and baseline, and not be quarantined
    valid_ratios = []
    for r in readings:
        if r.data_quality_status == "quarantined":
            continue
        if r.kwh is not None and r.rolling_baseline_kwh is not None and r.rolling_baseline_kwh > 0:
            valid_ratios.append(r.kwh / r.rolling_baseline_kwh)
            
    if len(valid_ratios) < threshold_config.min_data_points:
        logger.info("Insufficient data for drift detection", valid_count=len(valid_ratios), required=threshold_config.min_data_points)
        # TRD allows only stable or drifting. Insufficient data implies we can't prove drift.
        return DriftResult(
            tenant_id=tenant_id,
            building_id=building_id,
            status=DriftStatus.STABLE,
            trend_direction=TrendDirection.NONE,
            magnitude=None,
            evaluated_at=now,
        )
        
    # Run Mann-Kendall trend test
    # mk.original_test returns a named tuple: (trend, h, p, z, Tau, s, var_s, slope, intercept)
    mk_result = mk.original_test(valid_ratios, alpha=threshold_config.p_value_threshold)
    
    if mk_result.trend == 'increasing':
        trend_direction = TrendDirection.INCREASING
        status = DriftStatus.DRIFTING
    elif mk_result.trend == 'decreasing':
        trend_direction = TrendDirection.DECREASING
        status = DriftStatus.DRIFTING
    else:
        trend_direction = TrendDirection.NONE
        status = DriftStatus.STABLE
        
    logger.info("Drift evaluation completed", status=status.value, trend=trend_direction.value, magnitude=mk_result.slope)
        
    return DriftResult(
        tenant_id=tenant_id,
        building_id=building_id,
        status=status,
        trend_direction=trend_direction,
        magnitude=mk_result.slope,
        evaluated_at=now,
    )
