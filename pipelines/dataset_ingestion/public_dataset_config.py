"""ENG-6a — Public-dataset SourceConfigs.

Reuses services.ingestion.config.SourceConfig/ColumnMappingConfig exactly
as-is (DATA_AND_MODEL_STRATEGY §1: source-agnostic ingestion, no
dataset-specific normalization logic duplicated) -- integrating a new
public dataset is adding a column-alias mapping here, not writing a new
ingestion path. Every public dataset below is normalized to the same
long-format shape services/ingestion/normalization.py already expects:
one row per (meter/circuit identifier, timestamp, kwh reading).

Datasets
--------
COMBED (IIT Delhi instrumented building, DATA_AND_MODEL_STRATEGY §1):
    Published per-circuit CSVs; typical columns are a timestamp column
    and a power/energy reading column, with the circuit identity carried
    by the file/column name rather than a row value in the raw
    distribution. `combed_normalized` below is the alias set for the
    common post-processed long-format shape (a `meter_id` column added
    during export) most COMBED redistributions and course exports use --
    the same "long format, then column-alias-map it" approach already
    established for CSV upload (services/ingestion/config.py's own
    default source).

Building Data Genome 2 / ASHRAE Great Energy Predictor III:
    Both distribute (or are derived from) a long-format table:
    building_id, meter, timestamp, meter_reading. `bdg2` below maps
    those exact column names.
"""

from __future__ import annotations

from services.ingestion.config import ColumnMappingConfig, SourceConfig

COMBED_SOURCE_ID = "combed"
BDG2_SOURCE_ID = "bdg2"

_combed_mapping = ColumnMappingConfig(
    circuit_id_aliases=["meter_id", "meterId", "device_id", "sensor_id", "circuit_id", "panel"],
    timestamp_aliases=["timestamp", "ts", "time", "datetime", "reading_time", "Date & Time"],
    kwh_aliases=["kwh", "kWh", "energy_kwh", "consumption", "reading", "Power (kW)", "power_kw"],
    circuit_type_aliases=["circuit_type", "circuitType", "type", "meter_type", "device_type"],
)

_bdg2_mapping = ColumnMappingConfig(
    circuit_id_aliases=["meter_id", "building_id", "meter", "circuit_id"],
    timestamp_aliases=["timestamp", "ts", "time", "datetime"],
    kwh_aliases=["kwh", "meter_reading", "reading"],
    circuit_type_aliases=["circuit_type", "meter", "meter_type"],
)

PUBLIC_DATASET_SOURCES: dict[str, SourceConfig] = {
    COMBED_SOURCE_ID: SourceConfig(
        source_id=COMBED_SOURCE_ID,
        column_mapping=_combed_mapping,
        expected_columns=["meter_id", "timestamp", "kwh"],
        required_fields=["meter_id", "timestamp", "kwh"],
        expected_reporting_interval_minutes=60,
    ),
    BDG2_SOURCE_ID: SourceConfig(
        source_id=BDG2_SOURCE_ID,
        column_mapping=_bdg2_mapping,
        expected_columns=["meter_id", "timestamp", "kwh"],
        required_fields=["meter_id", "timestamp", "kwh"],
        expected_reporting_interval_minutes=60,
    ),
}


def get_public_dataset_source(source_id: str) -> SourceConfig:
    try:
        return PUBLIC_DATASET_SOURCES[source_id]
    except KeyError as exc:
        raise ValueError(
            f"Unknown public dataset source_id={source_id!r}; "
            f"known sources: {sorted(PUBLIC_DATASET_SOURCES)}"
        ) from exc
