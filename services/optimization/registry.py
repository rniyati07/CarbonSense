"""ENG-4b — Versioned, extensible scenario registry.

Mirrors services/rules_engine/registry.py's role (the authoritative,
injectable catalog a service iterates over) but for code-defined scenario
models rather than declarative YAML rules -- a scenario's logic (LP
formulation, heuristics) is not expressible as a YAML condition string the
way a rule fire condition is.

To add a new scenario model: implement the ScenarioModel Protocol in a new
module under services/optimization/scenarios/, then add one line to
default_registry() below. Nothing in service.py or any existing scenario
module needs to change.
"""

from __future__ import annotations

from services.optimization.interfaces import ScenarioModel


class DuplicateScenarioError(Exception):
    """Raised when two scenario models register the same name."""


class ScenarioRegistry:
    def __init__(self) -> None:
        self._models: dict[str, ScenarioModel] = {}

    def register(self, model: ScenarioModel) -> None:
        if model.name in self._models:
            raise DuplicateScenarioError(
                f"Scenario model {model.name!r} is already registered "
                f"(version {self._models[model.name].version})."
            )
        self._models[model.name] = model

    def get(self, name: str) -> ScenarioModel | None:
        return self._models.get(name)

    def get_all(self) -> list[ScenarioModel]:
        return list(self._models.values())


def default_registry() -> ScenarioRegistry:
    """The production scenario catalog (TRD v2.0 §4): load_shift_v1,
    setpoint_adjustment_v1, solar_offset_v1. Extend by adding a new
    scenarios/ module and one more .register() call here."""
    from services.optimization.scenarios.load_shift import LoadShiftV1
    from services.optimization.scenarios.setpoint_adjustment import SetpointAdjustmentV1
    from services.optimization.scenarios.solar_offset import SolarOffsetV1

    registry = ScenarioRegistry()
    registry.register(LoadShiftV1())
    registry.register(SetpointAdjustmentV1())
    registry.register(SolarOffsetV1())
    return registry
