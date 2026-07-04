"""ENG-3g-1 — Feature-name to plain-language template registry.

Provides a DETERMINISTIC, LLM-FREE mapping from feature_set_v1 feature
names to plain-language descriptions suitable for a facility manager.

All templates are static and version-tracked here — they are never generated
by an LLM call. This guarantees that the same feature name + SHAP value
always produces the same plain_language string, making Explainability Bundles
reproducible and audit-traceable (TRD v2.0 §3.7, DATA_AND_MODEL_STRATEGY §5.6).

Adding a new feature: add an entry to _FEATURE_TEMPLATES. Each template may
contain {pct} (abs percentage from shap_value × 100) and {direction} placeholders.
"""

from __future__ import annotations
_FEATURE_TEMPLATES: dict[str, str] = {
    # After-hours consumption patterns
    "after_hours_kwh_ratio": (
        "Energy use after declared business hours was {pct}% {direction}"
        " the building's normal pattern"
    ),
    # Weekend load
    "weekend_floor_load": (
        "Weekend baseline consumption was {pct}% {direction} expected levels,"
        " suggesting equipment did not power down as scheduled"
    ),
    "weekend_kwh_ratio": (
        "Weekend energy consumption was {pct}% {direction} the expected idle baseline"
    ),
    # STL residual
    "stl_residual_z": (
        "The statistical anomaly score (STL residual) for this period was {pct}% stronger"
        " than the building's own seasonal norm"
    ),
    "stl_residual_magnitude": (
        "The deviation from the building's seasonal-decomposition baseline was {pct}%"
        " {direction} normal for this time of year"
    ),
    # Rolling statistics
    "rolling_24h_kwh_mean": (
        "The 24-hour rolling average consumption was {pct}% {direction}"
        " the building's historical baseline for comparable periods"
    ),
    "rolling_72h_kwh_mean": (
        "The 72-hour rolling average consumption was {pct}% {direction}"
        " the building's expected level for this day type"
    ),
    "rolling_kwh_stddev": (
        "Consumption variability over the recent window was {pct}% {direction}"
        " the building's normal variance, indicating an unusual operating pattern"
    ),
    # Peak hour patterns
    "peak_hour_ratio": (
        "The ratio of peak-hour to off-peak energy use was {pct}% {direction}"
        " the building's typical peak-hour loading profile"
    ),
    "peak_kwh": (
        "Peak-hour energy consumption was {pct}% {direction} the building's"
        " expected peak-period load"
    ),
    "off_peak_kwh": (
        "Off-peak energy consumption was {pct}% {direction} the expected"
        " low-occupancy baseline, suggesting equipment active outside operating hours"
    ),
    # Rule fire indicators
    "rule_fire_indicator": (
        "A domain rule (such as after-hours HVAC scheduling) contributed {pct}%"
        " of the anomaly signal for this finding"
    ),
    "hvac_rule_fire": (
        "The HVAC scheduling rule fired with {pct}% contribution — consumption"
        " exceeded the declared unoccupied baseline during off-hours"
    ),
    # Autoencoder reconstruction error
    "autoencoder_reconstruction_error": (
        "The pattern of energy use over this window was {pct}% more unusual than"
        " the model's learned normal profile, flagging an abnormal consumption shape"
    ),
    "reconstruction_error": (
        "The statistical pattern of consumption was {pct}% {direction} the model's"
        " expected profile for this circuit and time period"
    ),
    # Calendar / day-type features
    "is_business_hours": (
        "This period occurred during declared business hours; the {pct}% anomaly"
        " signal is relative to occupied-period norms"
    ),
    "day_type_encoded": (
        "The day type classification contributed {pct}% to the anomaly score —"
        " consumption did not match the expected pattern for this day type"
    ),
    # Baseline deviation
    "kwh_vs_baseline": (
        "Actual consumption was {pct}% {direction} the rolling baseline for"
        " this circuit and time of day"
    ),
    "baseline_deviation_pct": (
        "Energy use deviated {pct}% from the circuit's established baseline"
        " for comparable time windows"
    ),
    # Circuit load ratio
    "circuit_load_ratio": (
        "This circuit carried {pct}% {direction} its expected share of building load,"
        " indicating either an equipment fault or an unscheduled operation"
    ),
}

# Fallback template for unknown features (safe default — never drops the feature)
_FALLBACK_TEMPLATE = (
    "Feature '{feature}' contributed {pct}% to the anomaly signal"
    " (no plain-language description registered for this feature)"
)

# Registry version — bump when templates are added or substantially revised
REGISTRY_VERSION = "feature_registry_v1"


def render(feature_name: str, shap_value: float) -> str:
    pct = round(abs(shap_value) * 100)
    direction = "above" if shap_value >= 0 else "below"

    template = _FEATURE_TEMPLATES.get(feature_name)
    if template is None:
        return _FALLBACK_TEMPLATE.format(feature=feature_name, pct=pct)

    # Not every template uses all keys; use a safe format that ignores extras
    return template.format(pct=pct, direction=direction, feature=feature_name)


def list_registered_features() -> list[str]:
    """Return all feature names with registered templates."""
    return sorted(_FEATURE_TEMPLATES.keys())


def is_registered(feature_name: str) -> bool:
    """Return True if *feature_name* has a registered template."""
    return feature_name in _FEATURE_TEMPLATES


def _pct(shap_value: float) -> int:
    """Internal helper: abs(shap_value) as an integer percentage."""
    return round(abs(shap_value) * 100)


# Expose pct helper for tests
pct = _pct
