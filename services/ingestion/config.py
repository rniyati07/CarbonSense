from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ColumnMappingConfig(BaseModel):
    circuit_id_aliases: list[str] = Field(
        default=["meter_id", "meterId", "device_id", "sensor_id", "circuit_id"]
    )
    timestamp_aliases: list[str] = Field(
        default=["timestamp", "ts", "time", "datetime", "reading_time"]
    )
    kwh_aliases: list[str] = Field(
        default=["kwh", "kWh", "energy_kwh", "consumption", "reading"]
    )
    circuit_type_aliases: list[str] = Field(
        default=["circuit_type", "circuitType", "type", "meter_type", "device_type"]
    )


class SourceConfig(BaseModel):
    source_id: str
    column_mapping: ColumnMappingConfig = Field(default_factory=ColumnMappingConfig)
    expected_columns: list[str] = Field(
        default=["meter_id", "timestamp", "kwh", "circuit_type"]
    )
    expected_types: dict[str, str] = Field(
        default={"meter_id": "string", "timestamp": "string", "kwh": "numeric", "circuit_type": "string"}
    )
    required_fields: list[str] = Field(default=["meter_id", "timestamp", "kwh"])
    expected_reporting_interval_minutes: int = 60


class OutlierConfig(BaseModel):
    method: str = "rolling_zscore"
    zscore_threshold: float = 3.0
    window_size: int = 24


class GapConfig(BaseModel):
    max_interpolation_gap_minutes: int = 120
    degraded_interpolation_ratio: float = 0.10


class StuckAtValueThresholds(BaseModel):
    variance_threshold: float = 1e-6
    window_size: int = 6
    duration_threshold_hours: int = 6


class SensorFaultConfig(BaseModel):
    stuck_thresholds: dict[str, StuckAtValueThresholds] = Field(default_factory=lambda: {
        "main_feed": StuckAtValueThresholds(
            variance_threshold=1e-6, window_size=6, duration_threshold_hours=4,
        ),
        "hvac": StuckAtValueThresholds(
            variance_threshold=1e-5, window_size=6, duration_threshold_hours=6,
        ),
        "lighting": StuckAtValueThresholds(
            variance_threshold=1e-5, window_size=8, duration_threshold_hours=8,
        ),
        "plug_load": StuckAtValueThresholds(
            variance_threshold=1e-4, window_size=8, duration_threshold_hours=12,
        ),
    })
    default_stuck_thresholds: StuckAtValueThresholds = Field(
        default_factory=StuckAtValueThresholds
    )
    expected_intervals: dict[str, int] = Field(default_factory=lambda: {
        "smart_meter_api": 15,
        "csv_upload": 60,
        "batch_upload": 60,
    })
    default_expected_interval_minutes: int = 60
    dropout_tolerance_factor: float = 3.0


class BoundsEntry(BaseModel):
    min_kwh: float = 0.0
    max_kwh: float = 1000.0


class BoundsConfig(BaseModel):
    version: str = "1.0.0"
    circuit_type_bounds: dict[str, BoundsEntry] = Field(default_factory=lambda: {
        "main_feed": BoundsEntry(min_kwh=0.0, max_kwh=5000.0),
        "hvac": BoundsEntry(min_kwh=0.0, max_kwh=2000.0),
        "lighting": BoundsEntry(min_kwh=0.0, max_kwh=500.0),
        "plug_load": BoundsEntry(min_kwh=0.0, max_kwh=200.0),
    })
    default_bounds: BoundsEntry = Field(
        default_factory=lambda: BoundsEntry(min_kwh=0.0, max_kwh=5000.0)
    )

    @classmethod
    def from_json_file(cls, path: Path) -> BoundsConfig:
        with open(path) as f:
            data: dict[str, Any] = json.load(f)
        return cls.model_validate(data)


class DataQualityGateConfig(BaseModel):
    config_version: str = "1.0.0"
    normalization_version: str = "v1.0.0"
    sources: dict[str, SourceConfig] = Field(
        default_factory=lambda: {"default": SourceConfig(source_id="default")}
    )
    outlier: OutlierConfig = Field(default_factory=OutlierConfig)
    gap: GapConfig = Field(default_factory=GapConfig)
    sensor_fault: SensorFaultConfig = Field(default_factory=SensorFaultConfig)
    bounds: BoundsConfig = Field(default_factory=BoundsConfig)

    def get_source(self, source_id: str) -> SourceConfig:
        if source_id in self.sources:
            return self.sources[source_id]
        return self.sources.get("default", SourceConfig(source_id=source_id))

    @classmethod
    def from_json(cls, path: Path) -> DataQualityGateConfig:
        with open(path) as f:
            data: dict[str, Any] = json.load(f)
        return cls.model_validate(data)