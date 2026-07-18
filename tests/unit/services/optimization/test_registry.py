from __future__ import annotations

import pytest

from services.optimization.registry import (
    DuplicateScenarioError,
    ScenarioRegistry,
    default_registry,
)


class _FakeModel:
    def __init__(self, name: str, version: int = 1) -> None:
        self.name = name
        self.version = version

    def generate(self, context: object) -> object:
        raise NotImplementedError


class TestScenarioRegistry:
    def test_register_and_get(self) -> None:
        registry = ScenarioRegistry()
        model = _FakeModel("load_shift_v1")
        registry.register(model)
        assert registry.get("load_shift_v1") is model

    def test_get_unknown_returns_none(self) -> None:
        registry = ScenarioRegistry()
        assert registry.get("nonexistent") is None

    def test_get_all_returns_every_registered_model(self) -> None:
        registry = ScenarioRegistry()
        registry.register(_FakeModel("a"))
        registry.register(_FakeModel("b"))
        assert {m.name for m in registry.get_all()} == {"a", "b"}

    def test_duplicate_registration_raises(self) -> None:
        registry = ScenarioRegistry()
        registry.register(_FakeModel("load_shift_v1"))
        with pytest.raises(DuplicateScenarioError):
            registry.register(_FakeModel("load_shift_v1"))


class TestDefaultRegistry:
    def test_contains_all_three_trd_scenarios(self) -> None:
        registry = default_registry()
        names = {m.name for m in registry.get_all()}
        assert names == {"load_shift_v1", "setpoint_adjustment_v1", "solar_offset_v1"}

    def test_every_model_is_version_1(self) -> None:
        registry = default_registry()
        assert all(m.version == 1 for m in registry.get_all())
