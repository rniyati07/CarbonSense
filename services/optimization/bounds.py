"""ENG-4d — Physical-plausibility bounds enforcement.

TRD v2.0 §4: "Savings estimates are clamped to a physically plausible range
and validated against reference cases before being returned; an out-of-bounds
result is rejected at the service layer and logged as a model-quality
incident, not silently clipped and returned -- per PRD §5.3, 'an implausible
scenario output is a trust failure, not a minor bug.'"

validate_scenario() is a pure function: it never mutates or clamps the input,
only judges it. OptimizationService is the single caller responsible for
acting on the verdict (reject + persist an incident on failure).
"""

from __future__ import annotations

from services.optimization.models import OptimizationScenario
from shared.config.optimization import OptimizationSettings


class BoundsViolation:
    """A single reason a scenario failed plausibility bounds."""

    def __init__(self, incident_type: str, message: str) -> None:
        self.incident_type = incident_type
        self.message = message


def validate_scenario(
    scenario: OptimizationScenario,
    settings: OptimizationSettings,
) -> list[BoundsViolation]:
    """Return every bounds violation found, or [] if the scenario passes.

    Checks, in order:
      - optimized_kwh must not exceed baseline_kwh (a "scenario" that
        increases consumption is not a savings scenario at all)
      - optimized_emissions_kg_co2 must not exceed baseline_emissions_kg_co2
      - pct_reduction must be internally consistent with baseline/optimized
        kWh (catches a scenario model computing pct_reduction independently
        of its own baseline/optimized figures and having them drift apart)
      - pct_reduction must fall within [min_plausible_pct_reduction,
        max_plausible_pct_reduction]
      - payback_months must not exceed max_plausible_payback_months
    """
    violations: list[BoundsViolation] = []

    if scenario.optimized_kwh > scenario.baseline_kwh:
        violations.append(
            BoundsViolation(
                "consumption_increase",
                f"optimized_kwh ({scenario.optimized_kwh}) exceeds "
                f"baseline_kwh ({scenario.baseline_kwh}) -- not a savings scenario.",
            )
        )

    if scenario.optimized_emissions_kg_co2 > scenario.baseline_emissions_kg_co2:
        violations.append(
            BoundsViolation(
                "emissions_increase",
                f"optimized_emissions_kg_co2 ({scenario.optimized_emissions_kg_co2}) "
                f"exceeds baseline_emissions_kg_co2 "
                f"({scenario.baseline_emissions_kg_co2}).",
            )
        )

    if scenario.baseline_kwh > 0:
        implied_pct = (
            (scenario.baseline_kwh - scenario.optimized_kwh) / scenario.baseline_kwh
        ) * 100.0
        if abs(implied_pct - scenario.pct_reduction) > 1.0:
            violations.append(
                BoundsViolation(
                    "pct_reduction_inconsistent",
                    f"pct_reduction ({scenario.pct_reduction:.2f}) does not match "
                    f"the reduction implied by baseline/optimized kWh "
                    f"({implied_pct:.2f}).",
                )
            )

    if not (
        settings.min_plausible_pct_reduction
        <= scenario.pct_reduction
        <= settings.max_plausible_pct_reduction
    ):
        violations.append(
            BoundsViolation(
                "pct_reduction_out_of_range",
                f"pct_reduction ({scenario.pct_reduction:.2f}) is outside the "
                f"physically plausible range "
                f"[{settings.min_plausible_pct_reduction}, "
                f"{settings.max_plausible_pct_reduction}].",
            )
        )

    if scenario.payback_months > settings.max_plausible_payback_months:
        violations.append(
            BoundsViolation(
                "payback_implausible",
                f"payback_months ({scenario.payback_months:.1f}) exceeds the "
                f"plausible ceiling ({settings.max_plausible_payback_months}).",
            )
        )

    return violations
