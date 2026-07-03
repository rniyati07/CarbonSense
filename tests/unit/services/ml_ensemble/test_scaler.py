"""ENG-3d-1 — BuildingScaler unit tests.

Covers:
- Per-building ownership: scaler cannot be shared across tenants
- fit / transform / fit_transform contract
- save/load round-trip: sklearn scaler state, rule_ids, and identity fields
- is_fitted guard on transform-before-fit
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import numpy as np
import pytest

from services.ml_ensemble.scaler import BuildingScaler
from tests.unit.services.ml_ensemble.conftest import BUILDING, TENANT

OTHER_BUILDING: UUID = UUID("99999999-9999-9999-9999-999999999999")
RULE_IDS = ["hvac_v1", "after_hours_v2", "weekend_vampire_v1"]


def _make_matrix(n_samples: int = 20, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(10.0, 2.0, size=(n_samples, len(RULE_IDS) + 7))


class TestBuildingScalerOwnership:
    def test_scaler_stores_tenant_and_building_id(self) -> None:
        s = BuildingScaler(tenant_id=TENANT, building_id=BUILDING, rule_ids=RULE_IDS)
        assert s.tenant_id == TENANT
        assert s.building_id == BUILDING

    def test_rule_ids_stored_as_copy(self) -> None:
        rule_ids = ["a", "b"]
        s = BuildingScaler(tenant_id=TENANT, building_id=BUILDING, rule_ids=rule_ids)
        rule_ids.append("c")
        assert s.rule_ids == ["a", "b"]

    def test_different_buildings_have_independent_scalers(self) -> None:
        s1 = BuildingScaler(tenant_id=TENANT, building_id=BUILDING, rule_ids=RULE_IDS)
        s2 = BuildingScaler(tenant_id=TENANT, building_id=OTHER_BUILDING, rule_ids=RULE_IDS)
        matrix = _make_matrix()
        s1.fit(matrix * 2)
        s2.fit(matrix * 0.5)
        t1 = s1.transform(matrix)
        t2 = s2.transform(matrix)
        assert not np.allclose(t1, t2)


class TestFitTransform:
    def test_is_fitted_false_before_fit(self) -> None:
        s = BuildingScaler(tenant_id=TENANT, building_id=BUILDING, rule_ids=RULE_IDS)
        assert s.is_fitted is False

    def test_is_fitted_true_after_fit(self) -> None:
        s = BuildingScaler(tenant_id=TENANT, building_id=BUILDING, rule_ids=RULE_IDS)
        s.fit(_make_matrix())
        assert s.is_fitted is True

    def test_transform_before_fit_raises(self) -> None:
        s = BuildingScaler(tenant_id=TENANT, building_id=BUILDING, rule_ids=RULE_IDS)
        with pytest.raises(RuntimeError, match="fit"):
            s.transform(_make_matrix())

    def test_fit_returns_self(self) -> None:
        s = BuildingScaler(tenant_id=TENANT, building_id=BUILDING, rule_ids=RULE_IDS)
        ret = s.fit(_make_matrix())
        assert ret is s

    def test_transform_output_shape_preserved(self) -> None:
        matrix = _make_matrix(n_samples=50)
        s = BuildingScaler(tenant_id=TENANT, building_id=BUILDING, rule_ids=RULE_IDS)
        result = s.fit_transform(matrix)
        assert result.shape == matrix.shape

    def test_scaled_mean_near_zero(self) -> None:
        matrix = _make_matrix(n_samples=200)
        s = BuildingScaler(tenant_id=TENANT, building_id=BUILDING, rule_ids=RULE_IDS)
        scaled = s.fit_transform(matrix)
        assert np.abs(scaled.mean(axis=0)).max() < 0.1

    def test_scaled_std_near_one(self) -> None:
        matrix = _make_matrix(n_samples=200)
        s = BuildingScaler(tenant_id=TENANT, building_id=BUILDING, rule_ids=RULE_IDS)
        scaled = s.fit_transform(matrix)
        assert np.abs(scaled.std(axis=0) - 1.0).max() < 0.15


class TestSaveLoad:
    def test_save_creates_scaler_pkl(self, tmp_path: Path) -> None:
        s = BuildingScaler(tenant_id=TENANT, building_id=BUILDING, rule_ids=RULE_IDS)
        s.fit(_make_matrix())
        path = s.save(tmp_path)
        assert path.name == BuildingScaler.SCALER_FILE
        assert path.exists()

    def test_load_restores_identity(self, tmp_path: Path) -> None:
        s = BuildingScaler(tenant_id=TENANT, building_id=BUILDING, rule_ids=RULE_IDS)
        s.fit(_make_matrix())
        path = s.save(tmp_path)
        loaded = BuildingScaler.load(path)
        assert loaded.tenant_id == TENANT
        assert loaded.building_id == BUILDING
        assert loaded.rule_ids == RULE_IDS

    def test_load_restores_is_fitted(self, tmp_path: Path) -> None:
        s = BuildingScaler(tenant_id=TENANT, building_id=BUILDING, rule_ids=RULE_IDS)
        s.fit(_make_matrix())
        path = s.save(tmp_path)
        loaded = BuildingScaler.load(path)
        assert loaded.is_fitted is True

    def test_load_produces_same_transform(self, tmp_path: Path) -> None:
        matrix = _make_matrix(n_samples=100)
        s = BuildingScaler(tenant_id=TENANT, building_id=BUILDING, rule_ids=RULE_IDS)
        s.fit(matrix)
        original_output = s.transform(matrix)

        path = s.save(tmp_path)
        loaded = BuildingScaler.load(path)
        loaded_output = loaded.transform(matrix)
        assert np.allclose(original_output, loaded_output)

    def test_unfitted_scaler_serialises_and_loads_unfitted(self, tmp_path: Path) -> None:
        s = BuildingScaler(tenant_id=TENANT, building_id=BUILDING, rule_ids=RULE_IDS)
        path = s.save(tmp_path)
        loaded = BuildingScaler.load(path)
        assert loaded.is_fitted is False
