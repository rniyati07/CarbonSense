"""ENG-3c — STL Residual Detection service (calendar-aware orchestration).

STLDetectionService is the main entry-point for the STL Residual Detection
layer.  It:

1.  Accepts a list of NormalizedReading objects and a list of CalendarEntry
    objects covering the same date range.

2.  Joins every reading to its CalendarEntry to obtain the day_type.
    A reading without a CalendarEntry raises CalendarLookupError —
    no silent fallback day_type is ever applied.

3.  Groups readings by day_type.  Each cohort is decomposed independently
    using statsmodels.tsa.seasonal.STL (via decomposition.py).

4.  Checks each cohort for cold-start (insufficient history).  Cold-start
    cohorts receive low_data_quality=True results; no residual scores are
    emitted.  This satisfies TRD §2.4 and the task cold-start requirement.

5.  Merges all cohort results back into the original timestamp order and
    returns a list[STLResidualResult].

Architecture invariants enforced here
--------------------------------------
- STL models are NEVER persisted, registered, or cached between calls.
- No dependency on ML Ensemble, Isolation Forest, Autoencoder,
  Confidence Calibration, or Drift Detection.
- No confidence values are produced.
- Output is fully reproducible: same inputs → same outputs.
- Calendar-awareness is enforced at the cohort-split step, not as an
  optional post-processing adjustment.

Dependencies
------------
- services.ingestion.models.NormalizedReading (consumed, not recreated)
- services.stl_detection.models.CalendarEntry / STLResidualResult
- services.stl_detection.decomposition (pure functions)
- services.stl_detection.config.STLDetectionConfig
- services.stl_detection.interfaces.CalendarRepository (injected)
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from uuid import UUID

import pandas as pd

from services.ingestion.models import NormalizedReading
from services.stl_detection.config import STLDetectionConfig
from services.stl_detection.decomposition import (
    check_cold_start,
    compute_residual_zscores,
    fit_stl,
    flag_anomalies,
)
from services.stl_detection.exceptions import (
    CalendarLookupError,
    InsufficientHistoryError,
)
from services.stl_detection.interfaces import CalendarRepository
from services.stl_detection.models import (
    CalendarEntry,
    DayType,
    STLResidualResult,
    STLWindowResult,
)


class STLDetectionService:
    """Calendar-aware STL Residual Detection for a single circuit/window.

    Parameters
    ----------
    config:
        STLDetectionConfig carrying all thresholds and STL parameters.
        Defaults to the standard configuration if not provided.
    calendar_repo:
        Implementation of CalendarRepository.  In production this will
        be wired to the TimescaleDB building_calendar table (ENG-1d).
        In tests, InMemoryCalendarRepository is injected.

    Usage
    -----
    ::

        service = STLDetectionService(config=..., calendar_repo=repo)
        results = service.analyse_circuit_window(readings, calendar_entries)
    """

    def __init__(
        self,
        config: STLDetectionConfig | None = None,
        calendar_repo: CalendarRepository | None = None,
    ) -> None:
        self._config = config or STLDetectionConfig()
        self._calendar_repo = calendar_repo

    @property
    def config(self) -> STLDetectionConfig:
        return self._config

    # ------------------------------------------------------------------ #
    # Primary public API
    # ------------------------------------------------------------------ #

    def analyse_circuit_window(
        self,
        readings: list[NormalizedReading],
        calendar_entries: list[CalendarEntry],
    ) -> list[STLResidualResult]:
        """Decompose a circuit's readings and return per-reading residual results.

        Parameters
        ----------
        readings:
            NormalizedReading objects for a single circuit within the
            analysis window, in any order.  Only readings with
            data_quality_status in {pass, degraded} should be passed;
            quarantined readings are not expected here (the pipeline
            gate upstream filters them).
        calendar_entries:
            CalendarEntry objects covering every date represented in
            readings.  One entry per date is required — CalendarLookupError
            is raised for any date without an entry.

        Returns
        -------
        list[STLResidualResult]
            One result per input reading, sorted by ascending timestamp.

        Raises
        ------
        CalendarLookupError
            When a reading's date has no matching CalendarEntry.
        """
        if not readings:
            return []

        # Build a date → CalendarEntry lookup for O(1) join
        calendar_map: dict[datetime.date, CalendarEntry] = {
            entry.date: entry for entry in calendar_entries
        }

        # Determine the building_id from the first calendar entry for error messages
        building_id_str = str(calendar_entries[0].building_id) if calendar_entries else "<unknown>"

        # Sort readings by timestamp for stable processing
        sorted_readings = sorted(readings, key=lambda r: r.ts)

        # ---------------------------------------------------------------- #
        # Step 1: Join each reading to its CalendarEntry (hard requirement)
        # ---------------------------------------------------------------- #
        reading_day_types: list[DayType] = []
        for reading in sorted_readings:
            reading_date = reading.ts.date()
            entry = calendar_map.get(reading_date)
            if entry is None:
                raise CalendarLookupError(
                    missing_date=reading_date.isoformat(),
                    building_id=building_id_str,
                )
            reading_day_types.append(entry.day_type)

        # ---------------------------------------------------------------- #
        # Step 2: Group readings by day_type (each cohort decomposed separately)
        # ---------------------------------------------------------------- #
        cohort_indices: dict[DayType, list[int]] = defaultdict(list)
        for idx, day_type in enumerate(reading_day_types):
            cohort_indices[day_type].append(idx)

        # ---------------------------------------------------------------- #
        # Step 3: Decompose each cohort independently
        # ---------------------------------------------------------------- #
        results: list[STLResidualResult | None] = [None] * len(sorted_readings)

        for day_type, indices in cohort_indices.items():
            cohort_readings = [sorted_readings[i] for i in indices]
            cohort_results = self._decompose_cohort(
                cohort_readings=cohort_readings,
                day_type=day_type,
            )
            for idx, result in zip(indices, cohort_results, strict=True):
                results[idx] = result

        # All slots must be filled — if any None remains it is a logic error
        assert all(r is not None for r in results), (
            "BUG: not all readings received a result after cohort decomposition."
        )

        return [r for r in results if r is not None]

    def analyse_circuit_window_with_repo(
        self,
        readings: list[NormalizedReading],
        building_id: UUID,
    ) -> list[STLResidualResult]:
        """Convenience overload: fetch calendar from injected CalendarRepository.

        Parameters
        ----------
        readings:
            NormalizedReading objects for a single circuit.
        building_id:
            The building owning the circuit (used for the calendar query).

        Returns
        -------
        list[STLResidualResult]

        Raises
        ------
        RuntimeError
            When no CalendarRepository was injected.
        CalendarLookupError
            When the repository returns no entry for a reading's date.
        """
        if self._calendar_repo is None:
            raise RuntimeError(
                "STLDetectionService was constructed without a CalendarRepository. "
                "Either inject one or call analyse_circuit_window() directly "
                "with a calendar_entries list."
            )

        if not readings:
            return []

        dates = sorted({r.ts.date() for r in readings})
        start_date = dates[0]
        end_date = dates[-1]

        calendar_entries = self._calendar_repo.get_calendar_entries(
            building_id=building_id,
            start_date=start_date,
            end_date=end_date,
        )
        return self.analyse_circuit_window(readings, calendar_entries)

    def build_window_result(
        self,
        tenant_id: UUID,
        building_id: UUID,
        circuit_id: UUID,
        readings: list[NormalizedReading],
        calendar_entries: list[CalendarEntry],
    ) -> STLWindowResult:
        """Run analysis and wrap in an STLWindowResult with summary metadata."""
        residual_results = self.analyse_circuit_window(readings, calendar_entries)

        if residual_results:
            window_start = residual_results[0].ts
            window_end = residual_results[-1].ts
        else:
            now = datetime.datetime.now(tz=datetime.UTC)
            window_start = now
            window_end = now

        return STLWindowResult(
            tenant_id=tenant_id,
            building_id=building_id,
            circuit_id=circuit_id,
            window_start=window_start,
            window_end=window_end,
            readings=residual_results,
        )

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _decompose_cohort(
        self,
        cohort_readings: list[NormalizedReading],
        day_type: DayType,
    ) -> list[STLResidualResult]:
        """Decompose one day-type cohort and return per-reading results.

        If the cohort is too small (cold-start), returns low_data_quality
        results for every reading in the cohort without raising an exception.
        """
        n = len(cohort_readings)
        is_low_quality, reason = check_cold_start(n, self._config)

        if is_low_quality:
            # Cold-start: emit low_data_quality for every reading in cohort
            # Do NOT fabricate residual values.
            return [
                STLResidualResult(
                    tenant_id=r.tenant_id,
                    circuit_id=r.circuit_id,
                    ts=r.ts,
                    kwh=r.kwh,
                    day_type=day_type,
                    low_data_quality=True,
                    low_data_quality_reason=reason,
                    # All residual/score fields remain None (default)
                )
                for r in cohort_readings
            ]

        # Build a pandas Series for STL: index = UTC datetime, values = kwh
        ts_list = [r.ts for r in cohort_readings]
        kwh_list = [r.kwh if r.kwh is not None else float("nan") for r in cohort_readings]
        series = pd.Series(kwh_list, index=pd.DatetimeIndex(ts_list, tz=datetime.UTC))
        series = series.sort_index()

        try:
            decomp = fit_stl(series, self._config)
        except InsufficientHistoryError as exc:
            # fit_stl raises this when len(series) < min_history; should not
            # normally happen here because check_cold_start already caught it,
            # but guard defensively to avoid emitting unreliable scores.
            fallback_reason = str(exc)
            return [
                STLResidualResult(
                    tenant_id=r.tenant_id,
                    circuit_id=r.circuit_id,
                    ts=r.ts,
                    kwh=r.kwh,
                    day_type=day_type,
                    low_data_quality=True,
                    low_data_quality_reason=fallback_reason,
                )
                for r in cohort_readings
            ]

        # Compute robust z-scores and anomaly flags
        zscores = compute_residual_zscores(decomp.residual)
        anomaly_mask = flag_anomalies(zscores, self._config)

        # Build a (datetime → array-index) map for alignment
        ts_to_idx: dict[datetime.datetime, int] = {
            ts: i for i, ts in enumerate(decomp.index.to_pydatetime())
        }

        result_list: list[STLResidualResult] = []
        for reading in cohort_readings:
            # Normalise the reading's ts to UTC for lookup
            reading_ts = reading.ts
            if reading_ts.tzinfo is None:
                reading_ts = reading_ts.replace(tzinfo=datetime.UTC)
            else:
                reading_ts = reading_ts.astimezone(datetime.UTC)

            idx = ts_to_idx.get(reading_ts)
            if idx is None:
                # Timestamp not found in decomposition output — treat as
                # low_data_quality rather than crashing.
                result_list.append(
                    STLResidualResult(
                        tenant_id=reading.tenant_id,
                        circuit_id=reading.circuit_id,
                        ts=reading.ts,
                        kwh=reading.kwh,
                        day_type=day_type,
                        low_data_quality=True,
                        low_data_quality_reason=(
                            "Timestamp not found in STL decomposition output "
                            f"(ts={reading_ts.isoformat()})."
                        ),
                    )
                )
                continue

            residual_val = float(decomp.residual[idx])
            zscore_val = float(zscores[idx])
            magnitude_val = abs(residual_val)
            is_anom = bool(anomaly_mask[idx])

            result_list.append(
                STLResidualResult(
                    tenant_id=reading.tenant_id,
                    circuit_id=reading.circuit_id,
                    ts=reading.ts,
                    kwh=reading.kwh,
                    day_type=day_type,
                    stl_trend=float(decomp.trend[idx]),
                    stl_seasonal=float(decomp.seasonal[idx]),
                    stl_residual=residual_val,
                    residual_zscore=zscore_val,
                    residual_magnitude=magnitude_val,
                    is_anomalous=is_anom,
                    low_data_quality=False,
                )
            )

        return result_list
