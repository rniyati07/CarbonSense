from __future__ import annotations

import logging

from services.reporting.models import ActionItem, ActionPlan, ReportingRequest

logger = logging.getLogger(__name__)

# Effort level heuristics (payback months → effort)
_EFFORT_THRESHOLDS = {"Low": 6.0, "Medium": 24.0}


def _effort_level(payback_months: float) -> str:
    if payback_months <= _EFFORT_THRESHOLDS["Low"]:
        return "Low"
    if payback_months <= _EFFORT_THRESHOLDS["Medium"]:
        return "Medium"
    return "High"


def _confidence_note(lower: float, upper: float) -> str:
    band_width = upper - lower
    if band_width <= 0.10:
        return (
            f"High confidence (confidence band {lower:.0%}–{upper:.0%}): "
            "multiple detection layers corroborate this finding."
        )
    if band_width <= 0.25:
        return (
            f"Moderate confidence (confidence band {lower:.0%}–{upper:.0%}): "
            "this finding is supported but has some uncertainty."
        )
    return (
        f"Lower confidence (confidence band {lower:.0%}–{upper:.0%}): "
        "this is a statistical pattern only — the evidence has higher uncertainty "
        "than a rule-confirmed finding."
    )


class FallbackNarrator:
    def generate(self, request: ReportingRequest) -> ActionPlan:
        logger.warning(
            "LLM narrator failed twice; using deterministic fallback narrator",
            extra={"building_name": request.building_name},
        )

        # Pick the highest-confidence finding to anchor the narrative summary
        lead_finding = max(request.findings, key=lambda f: f.confidence)
        bundle = lead_finding.explainability_bundle
        cb = bundle.confidence_band

        is_ml_only = set(bundle.contributing_layers) == {"ml_ensemble"}

        # Build narrative summary from lead finding's top feature
        top_feature = bundle.top_features[0] if bundle.top_features else None
        if top_feature:
            feature_desc = top_feature.plain_language
        else:
            feature_desc = "an unusual consumption pattern was detected"

        if is_ml_only:
            mechanism_prefix = "A statistical pattern was detected:"
        elif bundle.rule_citations:
            rule_ref = bundle.rule_citations[0].citation
            mechanism_prefix = f"A domain rule was triggered ({rule_ref}):"
        else:
            mechanism_prefix = "An anomaly was detected:"

        conf_pct_lo = round(cb.lower * 100)
        conf_pct_hi = round(cb.upper * 100)
        narrative_summary = (
            f"{mechanism_prefix} {feature_desc}. "
            f"Confidence band: {conf_pct_lo}%–{conf_pct_hi}% "
            f"(method: {cb.method}). "
            f"{len(request.findings)} finding(s) analysed for {request.building_name}."
        )
        # Trim to ≤100 words
        words = narrative_summary.split()
        if len(words) > 100:
            narrative_summary = " ".join(words[:97]) + "..."

        # Build actions from optimization scenarios
        actions: list[ActionItem] = []
        for scenario in request.optimization_scenarios:
            if scenario.bounds_check != "passed":
                continue

            co2_saved = max(
                0.0,
                scenario.baseline_emissions_kg_co2 - scenario.optimized_emissions_kg_co2,
            )
            description = (
                f"Shift {scenario.scenario_model.replace('_', ' ')} to reduce consumption "
                f"from {scenario.baseline_kwh:.0f} kWh to {scenario.optimized_kwh:.0f} kWh "
                f"({scenario.pct_reduction:.1f}% reduction)."
            )
            # Trim to ≤50 words
            desc_words = description.split()
            if len(desc_words) > 50:
                description = " ".join(desc_words[:47]) + "..."

            # Build confidence note from the first justifying finding's bundle
            note = _confidence_note(cb.lower, cb.upper)
            for finding in request.findings:
                if finding.finding_id in scenario.justifying_finding_ids:
                    fc = finding.explainability_bundle.confidence_band
                    note = _confidence_note(fc.lower, fc.upper)
                    break

            model_name = scenario.scenario_model.replace("_v1", "").replace("_", " ").title()
            actions.append(
                ActionItem(
                    title=f"Optimise: {model_name}",
                    description=description,
                    justifying_finding_ids=scenario.justifying_finding_ids,
                    estimated_co2_saved_kg_per_year=co2_saved,
                    estimated_savings_inr_per_year=scenario.estimated_annual_savings_inr,
                    effort_level=_effort_level(scenario.payback_months),  # type: ignore[arg-type]
                    payback_months=scenario.payback_months,
                    confidence_note=note,
                )
            )

        # If no scenarios, synthesise one action from the lead finding itself
        if not actions and bundle.top_features:
            actions.append(
                ActionItem(
                    title="Investigate anomalous consumption pattern",
                    description=(
                        f"Review {bundle.top_features[0].feature.replace('_', ' ')} "
                        f"for {request.building_name}. Schedule site inspection."
                    ),
                    justifying_finding_ids=[lead_finding.finding_id],
                    estimated_co2_saved_kg_per_year=0.0,
                    estimated_savings_inr_per_year=0.0,
                    effort_level="Low",
                    payback_months=0.0,
                    confidence_note=_confidence_note(cb.lower, cb.upper),
                )
            )

        return ActionPlan(
            narrative_summary=narrative_summary,
            actions=actions,
            generated_by="fallback",
        )
