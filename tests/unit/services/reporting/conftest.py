from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from services.explainability.models import (
    ConfidenceBand,
    EvidenceWindow,
    ExplainabilityBundle,
    RuleCitation,
    TopFeature,
)
from services.reporting.models import (
    FindingWithBundle,
    OptimizationScenario,
    ReportingRequest,
)

EVIDENCE_START = datetime(2026, 6, 1, 22, 0, 0, tzinfo=UTC)
EVIDENCE_END = datetime(2026, 6, 2, 5, 0, 0, tzinfo=UTC)

FINDING_ID_MIXED = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
FINDING_ID_ML_ONLY = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
BUILDING_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def _make_mixed_evidence_bundle(finding_id: UUID) -> ExplainabilityBundle:
    return ExplainabilityBundle(
        finding_id=finding_id,
        contributing_layers=["domain_rule", "ml_ensemble"],
        top_features=[
            TopFeature(
                feature="after_hours_kwh_ratio",
                shap_value=0.41,
                plain_language=(
                    "Energy use after declared business hours was 41% above"
                    " the building's normal pattern"
                ),
            ),
            TopFeature(
                feature="weekend_floor_load",
                shap_value=0.19,
                plain_language="Weekend baseline consumption was 19% above expected levels",
            ),
        ],
        rule_citations=[
            RuleCitation(
                rule_id="hvac_after_hours_v3",
                version=3,
                citation="ASHRAE Guideline 36 — HVAC scheduling FDD pattern",
            )
        ],
        confidence_band=ConfidenceBand(lower=0.62, upper=0.81),
        evidence_window=EvidenceWindow(start=EVIDENCE_START, end=EVIDENCE_END),
    )


def _make_ml_only_bundle(finding_id: UUID) -> ExplainabilityBundle:
    return ExplainabilityBundle(
        finding_id=finding_id,
        contributing_layers=["ml_ensemble"],
        top_features=[
            TopFeature(
                feature="autoencoder_reconstruction_error",
                shap_value=0.28,
                plain_language=(
                    "The pattern of energy use over this window was 28% more unusual"
                    " than the model's learned normal profile"
                ),
            ),
        ],
        rule_citations=[],  # HARD RULE: must be [] for ml-only
        confidence_band=ConfidenceBand(lower=0.32, upper=0.68),
        evidence_window=EvidenceWindow(start=EVIDENCE_START, end=EVIDENCE_END),
    )


@pytest.fixture()
def mixed_evidence_finding() -> FindingWithBundle:
    fid = FINDING_ID_MIXED
    return FindingWithBundle(
        finding_id=fid,
        building_id=BUILDING_ID,
        layer_origin="domain_rule,ml_ensemble",
        confidence=0.72,
        explainability_bundle=_make_mixed_evidence_bundle(fid),
    )


@pytest.fixture()
def ml_only_finding() -> FindingWithBundle:
    fid = FINDING_ID_ML_ONLY
    return FindingWithBundle(
        finding_id=fid,
        building_id=BUILDING_ID,
        layer_origin="ml_ensemble",
        confidence=0.45,
        explainability_bundle=_make_ml_only_bundle(fid),
    )


@pytest.fixture()
def optimization_scenario_for_mixed(
    mixed_evidence_finding: FindingWithBundle,
) -> OptimizationScenario:
    return OptimizationScenario(
        scenario_id=uuid4(),
        scenario_model="load_shift_v1",
        model_version=1,
        building_id=BUILDING_ID,
        justifying_finding_ids=[mixed_evidence_finding.finding_id],
        baseline_kwh=18400.0,
        optimized_kwh=15200.0,
        baseline_emissions_kg_co2=14904.0,
        optimized_emissions_kg_co2=12312.0,
        pct_reduction=17.4,
        estimated_annual_savings_inr=89600.0,
        payback_months=0.0,
    )


@pytest.fixture()
def mixed_evidence_request(
    mixed_evidence_finding: FindingWithBundle,
    optimization_scenario_for_mixed: OptimizationScenario,
) -> ReportingRequest:
    return ReportingRequest(
        findings=[mixed_evidence_finding],
        optimization_scenarios=[optimization_scenario_for_mixed],
        building_name="COMBED Block A",
        tenant_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
    )


@pytest.fixture()
def ml_only_request(ml_only_finding: FindingWithBundle) -> ReportingRequest:
    return ReportingRequest(
        findings=[ml_only_finding],
        optimization_scenarios=[],
        building_name="COMBED Block B",
        tenant_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
    )


@pytest.fixture()
def valid_action_plan_json() -> str:
    """A valid LLM response matching the ActionPlan schema."""
    return (
        '{"narrative_summary": "After-hours HVAC usage was detected 41% above normal'
        " (confidence 62%-81%). Based on the hvac_after_hours_v3 rule "
        '(ASHRAE Guideline 36) and supporting SHAP evidence, load-shifting is recommended.",'
        ' "actions": [{'
        '"title": "Schedule HVAC load shift",'
        ' "description": "Adjust HVAC scheduling to eliminate after-hours operation.'
        ' Evidence: hvac_after_hours_v3 rule and after_hours_kwh_ratio SHAP feature.",'
        f' "justifying_finding_ids": ["{FINDING_ID_MIXED}"],'
        ' "estimated_co2_saved_kg_per_year": 2592.0,'
        ' "estimated_savings_inr_per_year": 89600.0,'
        ' "effort_level": "Low",'
        ' "payback_months": 0.0,'
        ' "confidence_note": "Moderate-high confidence (62%-81%): '
        'rule and statistical evidence agree."'
        "}]}"
    )


@pytest.fixture()
def hedged_action_plan_json() -> str:
    """A valid LLM response for an ml_ensemble-only finding — hedged prose."""
    return (
        '{"narrative_summary": "A statistical pattern was detected (no rule citation).'
        " Confidence band is wide (32%-68%), indicating lower certainty"
        ' than a rule-confirmed finding.",'
        ' "actions": [{'
        '"title": "Schedule facility inspection",'
        ' "description": "A statistical anomaly was detected. No specific mechanism is confirmed.'
        ' Investigate directly to clarify causal factors.",'
        f' "justifying_finding_ids": ["{FINDING_ID_ML_ONLY}"],'
        ' "estimated_co2_saved_kg_per_year": 0.0,'
        ' "estimated_savings_inr_per_year": 0.0,'
        ' "effort_level": "Low",'
        ' "payback_months": 0.0,'
        ' "confidence_note": "Lower confidence (32%-68%): '
        'statistical pattern only, no confirming rule."'
        "}]}"
    )
