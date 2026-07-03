"""ENG-3d-1 — Feature Assembly service.

Assembles canonical FeatureSetV1 rows from the upstream layer outputs:
  - NormalizedReading (rolling statistics computed here)
  - FeatureSetV1STLFields (from the STL Residual Detection service, ENG-3c)
  - Rule-fire context (from the Domain Rule Engine, ENG-3b)

The FeatureAssembler owns the rolling-statistic computation logic because
that logic requires a time-ordered window of readings — it does not belong
in the Data Quality Gate (which processes one batch at a time) or in the
STL layer (which handles decomposition only).

Architecture constraints
------------------------
- This module MUST NOT import from services/stl_detection/ or
  services/rules_engine/ — it consumes their output DTOs through the
  protocol defined in their respective models modules, passed in by the
  caller.
- This module MUST NOT import from apps/api — training must never be
  reachable from the API layer.
- The resulting FeatureSetV1 list is passed to the ML Ensemble training
  pipeline (models/training/) or the serving service (models/serving/).
"""

from __future__ import annotations

import datetime
from uuid import UUID

import pandas as pd

from models.feature_store.feature_set_v1 import FEATURE_SCHEMA_VERSION, FeatureSetV1, FeatureSetV1STLFields
from services.ingestion.models import NormalizedReading


class FeatureAssembler:
    """Assembles FeatureSetV1 rows from upstream layer outputs.

    Usage
    -----
    ::

        assembler = FeatureAssembler(
            rolling_window_hours=168,  # 7 days
            peak_hours=frozenset(range(9, 21)),
            business_hours=(8, 18),
        )
        features = assembler.assemble(
            readings=readings,
            stl_fields_by_ts={ts: stl_fields},
            rule_fires_by_ts={ts: {"hvac_after_hours_v3": True}},
        )
    """

    def __init__(
        self,
        rolling_window_hours: int = 168,
        peak_hours: frozenset[int] | None = None,
        business_hour_start: int = 8,
        business_hour_end: int = 18,
        business_days: frozenset[int] | None = None,
    ) -> None:
        """Initialise the assembler with rolling-window and calendar parameters.

        Parameters
        ----------
        rolling_window_hours:
            Number of hours in the trailing window for rolling statistics.
            IMPLEMENTATION DEFAULT: 7 days (168 h).
            DATA_AND_MODEL_STRATEGY §3.2 specifies 7-day and 30-day variants.
        peak_hours:
            Set of hours (0–23) classified as peak hours for peak_offpeak_split.
            Defaults to {9,10,...,20} (09:00–20:00).
        business_hour_start / business_hour_end:
            Hour boundaries (inclusive/exclusive) for after_hours_kwh_ratio.
        business_days:
            ISO weekday numbers (1=Mon … 7=Sun) treated as business days.
            Defaults to {1,2,3,4,5}.
        """
        self._rolling_window_hours = rolling_window_hours
        self._peak_hours = peak_hours if peak_hours is not None else frozenset(range(9, 21))
        self._business_hour_start = business_hour_start
        self._business_hour_end = business_hour_end
        self._business_days = business_days if business_days is not None else frozenset(range(1, 6))

    def assemble(
        self,
        readings: list[NormalizedReading],
        stl_fields_by_ts: dict[datetime.datetime, FeatureSetV1STLFields] | None = None,
        rule_fires_by_ts: dict[datetime.datetime, dict[str, bool]] | None = None,
    ) -> list[FeatureSetV1]:
        """Assemble a FeatureSetV1 list from readings and upstream outputs.

        Parameters
        ----------
        readings:
            NormalizedReading objects for a single circuit, in any order.
            Only pass/degraded readings should be included.
        stl_fields_by_ts:
            Mapping from UTC timestamp to FeatureSetV1STLFields produced by
            STLDetectionService.  Keys must match reading timestamps exactly.
            Pass None or empty dict for cold-start buildings without STL output.
        rule_fires_by_ts:
            Mapping from UTC timestamp to a dict of rule_id → bool indicating
            which rules fired for this reading.  Pass None if no rules fired.

        Returns
        -------
        list[FeatureSetV1]
            One FeatureSetV1 per input reading, sorted by ascending timestamp.
        """
        if not readings:
            return []

        stl_map = stl_fields_by_ts or {}
        rule_map = rule_fires_by_ts or {}

        sorted_readings = sorted(readings, key=lambda r: r.ts)
        rolling_stats = self._compute_rolling_stats(sorted_readings)

        results: list[FeatureSetV1] = []
        for reading, stats in zip(sorted_readings, rolling_stats, strict=True):
            ts_key = reading.ts
            stl_fields = stl_map.get(ts_key)
            rule_fires = rule_map.get(ts_key, {})

            features = FeatureSetV1.from_components(
                tenant_id=reading.tenant_id,
                circuit_id=reading.circuit_id,
                ts=reading.ts,
                rolling_baseline_kwh=stats.get("rolling_baseline_kwh"),
                peak_offpeak_split=stats.get("peak_offpeak_split"),
                after_hours_kwh_ratio=stats.get("after_hours_kwh_ratio"),
                weekend_floor_load=stats.get("weekend_floor_load"),
                rolling_efficiency_ratio=stats.get("rolling_efficiency_ratio"),
                stl_fields=stl_fields,
                rule_fire_indicators=rule_fires,
            )
            results.append(features)

        return results

    # ------------------------------------------------------------------ #
    # Internal rolling-statistic computation
    # ------------------------------------------------------------------ #

    def _compute_rolling_stats(
        self, sorted_readings: list[NormalizedReading]
    ) -> list[dict[str, float | None]]:
        """Compute rolling statistics for each reading using a trailing window.

        Returns a list of stat dicts parallel to sorted_readings.
        """
        if not sorted_readings:
            return []

        kwh_values = [r.kwh if r.kwh is not None else 0.0 for r in sorted_readings]
        timestamps = [r.ts for r in sorted_readings]

        series = pd.Series(kwh_values, index=pd.DatetimeIndex(timestamps, tz=datetime.UTC))
        series = series.sort_index()

        window_str = f"{self._rolling_window_hours}h"
        rolling_mean = series.rolling(window_str, min_periods=1).mean()

        stats: list[dict[str, float | None]] = []
        for i, reading in enumerate(sorted_readings):
            kwh = reading.kwh
            baseline = float(rolling_mean.iloc[i]) if not rolling_mean.isna().iloc[i] else None

            peak_offpeak = self._compute_peak_offpeak_split(reading, kwh)
            after_hours = self._compute_after_hours_ratio(reading, kwh)
            weekend_floor = self._compute_weekend_floor_load(sorted_readings, i)

            efficiency_ratio: float | None = None
            if kwh is not None and baseline is not None and baseline > 0.0:
                efficiency_ratio = kwh / baseline

            stats.append(
                {
                    "rolling_baseline_kwh": baseline,
                    "peak_offpeak_split": peak_offpeak,
                    "after_hours_kwh_ratio": after_hours,
                    "weekend_floor_load": weekend_floor,
                    "rolling_efficiency_ratio": efficiency_ratio,
                }
            )

        return stats

    def _compute_peak_offpeak_split(
        self, reading: NormalizedReading, kwh: float | None
    ) -> float | None:
        if kwh is None or kwh == 0.0:
            return None
        hour = reading.ts.hour
        return 1.0 if hour in self._peak_hours else 0.0

    def _compute_after_hours_ratio(
        self, reading: NormalizedReading, kwh: float | None
    ) -> float | None:
        if kwh is None:
            return None
        hour = reading.ts.hour
        is_business_hours = (
            self._business_hour_start <= hour < self._business_hour_end
            and reading.ts.isoweekday() in self._business_days
        )
        return 1.0 if not is_business_hours else 0.0

    def _compute_weekend_floor_load(
        self, sorted_readings: list[NormalizedReading], current_idx: int
    ) -> float | None:
        current = sorted_readings[current_idx]
        if current.ts.isoweekday() not in (6, 7):
            return None

        after_hours = [
            r.kwh
            for r in sorted_readings
            if r.kwh is not None
            and r.ts.isoweekday() in (6, 7)
            and not (self._business_hour_start <= r.ts.hour < self._business_hour_end)
        ]

        if not after_hours:
            return None

        weekday_after = [
            r.kwh
            for r in sorted_readings
            if r.kwh is not None
            and r.ts.isoweekday() in self._business_days
            and not (self._business_hour_start <= r.ts.hour < self._business_hour_end)
        ]

        baseline = sum(weekday_after) / len(weekday_after) if weekday_after else 1.0
        if baseline == 0.0:
            return None

        floor = sum(after_hours) / len(after_hours)
        return floor / baseline


def assemble_feature_vector_matrix(
    features: list[FeatureSetV1],
    rule_ids: list[str],
) -> "list[list[float]]":
    """Convert a list of FeatureSetV1 rows into a 2D list of numeric vectors.

    Parameters
    ----------
    features:
        List of FeatureSetV1 instances from FeatureAssembler.assemble().
    rule_ids:
        Ordered rule_id list — must match the BuildingScaler's rule_ids.

    Returns
    -------
    list[list[float]]
        One inner list per FeatureSetV1 row.  Suitable for np.array() conversion.
    """
    return [f.to_numeric_vector(rule_ids) for f in features]


def collect_rule_ids(features: list[FeatureSetV1]) -> list[str]:
    """Derive a sorted, deduplicated list of rule_ids from a feature set.

    Used at training time to determine the canonical rule_ids ordering
    before fitting the BuildingScaler.

    The list is sorted alphabetically for determinism.
    """
    all_ids: set[str] = set()
    for f in features:
        all_ids.update(f.rule_fire_indicators.keys())
    return sorted(all_ids)


FEATURE_SCHEMA_VERSION_EXPORTED = FEATURE_SCHEMA_VERSION
