"""ENG-3c — STL Residual Detection data models.

Pydantic v2 models for the service's input and output contracts.

CalendarEntry
    Represents one row from the building_calendar table (ENG-1d).
    day_type is the four-value enumeration mandated by TRD §3.3 and
    DATA_AND_MODEL_STRATEGY §3.5.  The STL layer conditions decomposition
    on this field — never treats it as cosmetic metadata.

STLResidualResult
    Per-reading output from STLDetectionService.analyse_circuit_window.
    This is the primary output contract of ENG-3c.

    Fields feeding feature_set_v1 (ENG-3c-2 / ENG-3d-1):
        stl_residual, residual_zscore, residual_magnitude, day_type

    Fields for pipeline observability:
        is_anomalous, low_data_quality, low_data_quality_reason

    Fields passed to Confidence Calibration (ENG-3f) and
    Root-Cause Attribution (ENG-3g) as context:
        stl_trend, stl_seasonal (intermediate decomposition outputs)

STLWindowResult
    Aggregation wrapper around a list of STLResidualResult for one
    circuit/window.  Carries top-level metadata for the pipeline.

DayType
    Named enumeration of valid day-type values.  All calendar join logic
    MUST use these constants — no bare string comparisons in service code.
"""

from __future__ import annotations

import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class DayType(str, Enum):
    """Valid day-type classifications from building_calendar.

    TRD §3.3 / DATA_AND_MODEL_STRATEGY §3.5 mandate these exact four values.
    A holiday or declared_closure MUST NOT be evaluated using business_day
    STL decomposition parameters — this is enforced by grouping readings by
    DayType before fitting any STL model.
    """

    BUSINESS_DAY = "business_day"
    WEEKEND = "weekend"
    HOLIDAY = "holiday"
    DECLARED_CLOSURE = "declared_closure"


class CalendarEntry(BaseModel):
    """One row from the building_calendar table (ENG-1d).

    Attributes
    ----------
    building_id:
        Tenant-scoped building identifier.
    date:
        The calendar date this entry covers (UTC date, timezone-naive).
    day_type:
        Classification of this date for STL conditioning purposes.
        One of: business_day, weekend, holiday, declared_closure.
    """

    building_id: UUID
    date: datetime.date
    day_type: DayType


class STLResidualResult(BaseModel):
    """Per-reading output from STLDetectionService.

    When low_data_quality is True, residual fields (stl_trend,
    stl_seasonal, stl_residual, residual_zscore, residual_magnitude,
    is_anomalous) MUST be None / False respectively.  The service MUST NOT
    emit fabricated residual values for under-sampled cohorts.

    ENG-3c does NOT produce confidence values (confidence belongs to ENG-3f).
    """

    # Identity
    tenant_id: UUID
    circuit_id: UUID
    ts: datetime.datetime

    # Input passthrough
    kwh: float | None = None

    # Calendar classification (hard requirement — always populated)
    day_type: DayType

    # STL decomposition outputs (None when low_data_quality=True)
    stl_trend: float | None = None
    stl_seasonal: float | None = None
    stl_residual: float | None = None

    # Derived anomaly signals (None when low_data_quality=True)
    residual_zscore: float | None = None
    residual_magnitude: float | None = None  # abs(stl_residual)

    # Anomaly flag
    is_anomalous: bool = False

    # Cold-start / data-quality indicator
    low_data_quality: bool = False
    low_data_quality_reason: str | None = None

    @model_validator(mode="after")
    def validate_low_data_quality_consistency(self) -> STLResidualResult:
        """When low_data_quality is True, residual scores must be absent.

        Prevents callers from accidentally trusting residual values that
        were computed on an insufficient history window.
        """
        if self.low_data_quality:
            if self.residual_zscore is not None or self.residual_magnitude is not None:
                raise ValueError(
                    "residual_zscore and residual_magnitude must be None "
                    "when low_data_quality=True — do not emit unreliable scores."
                )
            if self.low_data_quality_reason is None:
                raise ValueError(
                    "low_data_quality_reason must be set when low_data_quality=True."
                )
        return self


class STLWindowResult(BaseModel):
    """Per-circuit/window aggregation of STL residual results.

    Carries the ordered list of per-reading results plus window-level
    metadata for use by the pipeline orchestrator and downstream layers.
    """

    tenant_id: UUID
    building_id: UUID
    circuit_id: UUID
    window_start: datetime.datetime
    window_end: datetime.datetime

    # Ordered by timestamp, matching the order of the input reading list
    readings: list[STLResidualResult] = Field(default_factory=list)

    # Summary counts for observability
    total_readings: int = 0
    anomalous_count: int = 0
    low_data_quality_count: int = 0

    @model_validator(mode="after")
    def compute_summary_counts(self) -> STLWindowResult:
        self.total_readings = len(self.readings)
        self.anomalous_count = sum(1 for r in self.readings if r.is_anomalous)
        self.low_data_quality_count = sum(1 for r in self.readings if r.low_data_quality)
        return self
