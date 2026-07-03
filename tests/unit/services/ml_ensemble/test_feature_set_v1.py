"""ENG-3d-1 — FeatureSetV1 unit tests.

Covers:
- Schema version constant and validation
- All field types and defaults
- to_numeric_vector() ordering consistency
- base_feature_names() / feature_names() alignment with vector
- from_components() round-trip
- ENG-3c STLFields compatibility (FeatureSetV1STLFields unchanged)
"""

from __future__ import annotations

import datetime
from uuid import UUID, uuid4

import pytest

from models.feature_store.feature_set_v1 import (
    DAY_TYPE_ENCODING,
    FEATURE_SCHEMA_VERSION,
    FeatureSetV1,
    FeatureSetV1STLFields,
)
from tests.unit.services.ml_ensemble.conftest import CIRCUIT, TENANT


def _make_ts(hour: int = 9) -> datetime.datetime:
    return datetime.datetime(2026, 1, 5, hour, 0, 0, tzinfo=datetime.UTC)


def _minimal_feature(**kwargs: object) -> FeatureSetV1:
    defaults: dict = {
        "tenant_id": TENANT,
        "circuit_id": CIRCUIT,
        "ts": _make_ts(),
    }
    defaults.update(kwargs)
    return FeatureSetV1(**defaults)


class TestSchemaVersion:
    def test_constant_value(self) -> None:
        assert FEATURE_SCHEMA_VERSION == "feature_set_v1"

    def test_default_schema_version(self) -> None:
        f = _minimal_feature()
        assert f.feature_schema_version == "feature_set_v1"

    def test_wrong_schema_version_raises(self) -> None:
        with pytest.raises(ValueError, match="feature_schema_version mismatch"):
            FeatureSetV1(
                tenant_id=TENANT,
                circuit_id=CIRCUIT,
                ts=_make_ts(),
                feature_schema_version="feature_set_v2",
            )


class TestFieldDefaults:
    def test_all_numeric_fields_default_to_none(self) -> None:
        f = _minimal_feature()
        assert f.rolling_baseline_kwh is None
        assert f.peak_offpeak_split is None
        assert f.after_hours_kwh_ratio is None
        assert f.weekend_floor_load is None
        assert f.rolling_efficiency_ratio is None
        assert f.stl_residual_magnitude is None

    def test_day_type_default(self) -> None:
        f = _minimal_feature()
        assert f.day_type == "business_day"

    def test_rule_fire_indicators_default_empty(self) -> None:
        f = _minimal_feature()
        assert f.rule_fire_indicators == {}

    def test_low_data_quality_default_false(self) -> None:
        f = _minimal_feature()
        assert f.low_data_quality is False


class TestToNumericVector:
    def test_length_equals_7_plus_n_rule_ids(self) -> None:
        rule_ids = ["hvac_v1", "weekend_v1", "after_hours_v1"]
        f = _minimal_feature()
        vec = f.to_numeric_vector(rule_ids)
        assert len(vec) == 7 + len(rule_ids)

    def test_none_fields_encode_as_zero(self) -> None:
        f = _minimal_feature()
        vec = f.to_numeric_vector([])
        assert all(v == 0.0 for v in vec)

    def test_ordering_matches_base_feature_names(self) -> None:
        rule_ids = ["alpha", "beta"]
        f = FeatureSetV1(
            tenant_id=TENANT,
            circuit_id=CIRCUIT,
            ts=_make_ts(),
            rolling_baseline_kwh=10.0,
            peak_offpeak_split=0.6,
            after_hours_kwh_ratio=0.3,
            weekend_floor_load=0.1,
            rolling_efficiency_ratio=1.05,
            stl_residual_magnitude=0.5,
            day_type="weekend",
            rule_fire_indicators={"alpha": True, "beta": False},
        )
        vec = f.to_numeric_vector(rule_ids)
        names = FeatureSetV1.feature_names(rule_ids)
        assert len(vec) == len(names)
        assert vec[0] == pytest.approx(10.0)
        assert vec[1] == pytest.approx(0.6)
        assert vec[2] == pytest.approx(0.3)
        assert vec[3] == pytest.approx(0.1)
        assert vec[4] == pytest.approx(1.05)
        assert vec[5] == pytest.approx(0.5)
        assert vec[6] == float(DAY_TYPE_ENCODING["weekend"])
        assert vec[7] == 1.0   # alpha fired
        assert vec[8] == 0.0   # beta did not fire

    def test_rule_id_ordering_is_deterministic(self) -> None:
        """Same rule_ids list always produces the same vector ordering."""
        rule_ids = ["z_rule", "a_rule", "m_rule"]
        f = _minimal_feature(rule_fire_indicators={"a_rule": True, "z_rule": False, "m_rule": True})
        v1 = f.to_numeric_vector(rule_ids)
        v2 = f.to_numeric_vector(rule_ids)
        assert v1 == v2

    def test_missing_rule_id_in_indicators_defaults_to_zero(self) -> None:
        rule_ids = ["present", "absent"]
        f = _minimal_feature(rule_fire_indicators={"present": True})
        vec = f.to_numeric_vector(rule_ids)
        assert vec[7] == 1.0   # present fired
        assert vec[8] == 0.0   # absent: not in dict → 0

    def test_empty_rule_ids_produces_7_element_vector(self) -> None:
        f = _minimal_feature()
        assert len(f.to_numeric_vector([])) == 7


class TestFeatureNames:
    def test_base_feature_names_has_7_entries(self) -> None:
        names = FeatureSetV1.base_feature_names()
        assert len(names) == 7

    def test_feature_names_appends_rule_prefixed_names(self) -> None:
        rule_ids = ["hvac_v1"]
        names = FeatureSetV1.feature_names(rule_ids)
        assert "rule_fire_hvac_v1" in names
        assert len(names) == 8


class TestFromComponents:
    def test_stl_fields_propagated(self) -> None:
        stl = FeatureSetV1STLFields(
            stl_residual=-2.0,
            residual_zscore=-3.1,
            residual_magnitude=2.0,
            day_type="holiday",
            low_data_quality=False,
        )
        f = FeatureSetV1.from_components(
            tenant_id=TENANT,
            circuit_id=CIRCUIT,
            ts=_make_ts(),
            rolling_baseline_kwh=10.0,
            peak_offpeak_split=0.5,
            after_hours_kwh_ratio=0.2,
            weekend_floor_load=None,
            rolling_efficiency_ratio=1.0,
            stl_fields=stl,
            rule_fire_indicators={"hvac_v1": True},
        )
        assert f.stl_residual_magnitude == pytest.approx(2.0)
        assert f.day_type == "holiday"
        assert f.low_data_quality is False

    def test_low_data_quality_propagated_from_stl(self) -> None:
        stl = FeatureSetV1STLFields(
            stl_residual=None,
            residual_zscore=None,
            residual_magnitude=None,
            day_type="business_day",
            low_data_quality=True,
        )
        f = FeatureSetV1.from_components(
            tenant_id=TENANT,
            circuit_id=CIRCUIT,
            ts=_make_ts(),
            rolling_baseline_kwh=None,
            peak_offpeak_split=None,
            after_hours_kwh_ratio=None,
            weekend_floor_load=None,
            rolling_efficiency_ratio=None,
            stl_fields=stl,
            rule_fire_indicators={},
        )
        assert f.low_data_quality is True

    def test_none_stl_fields_gives_defaults(self) -> None:
        f = FeatureSetV1.from_components(
            tenant_id=TENANT,
            circuit_id=CIRCUIT,
            ts=_make_ts(),
            rolling_baseline_kwh=None,
            peak_offpeak_split=None,
            after_hours_kwh_ratio=None,
            weekend_floor_load=None,
            rolling_efficiency_ratio=None,
            stl_fields=None,
            rule_fire_indicators=None,
        )
        assert f.day_type == "business_day"
        assert f.low_data_quality is False
        assert f.stl_residual_magnitude is None


class TestSTLFieldsCompatibility:
    """Verify FeatureSetV1STLFields is unchanged — ENG-3c compatibility."""

    def test_from_stl_result_duck_typing(self) -> None:
        class FakeResult:
            stl_residual = 1.5
            residual_zscore = 2.1
            residual_magnitude = 1.5

            class day_type:  # noqa: N801
                value = "business_day"

            low_data_quality = False

        fields = FeatureSetV1STLFields.from_stl_result(FakeResult())
        assert fields.stl_residual == pytest.approx(1.5)
        assert fields.day_type == "business_day"
        assert fields.low_data_quality is False
