"""Unit tests for services/reporting/fallback.py.

The FallbackNarrator is a first-class, independently tested code path.
Tests assert that it produces a complete, schema-valid ActionPlan from any
valid ReportingRequest without invoking any LLM.
"""

from __future__ import annotations

import json

import pytest

from services.reporting.fallback import FallbackNarrator
from services.reporting.models import ActionPlan, ReportingRequest


@pytest.mark.unit
class TestFallbackNarratorMixedEvidence:
    def test_produces_action_plan(self, mixed_evidence_request: ReportingRequest) -> None:
        fallback = FallbackNarrator()
        plan = fallback.generate(mixed_evidence_request)
        assert isinstance(plan, ActionPlan)

    def test_generated_by_is_fallback(self, mixed_evidence_request: ReportingRequest) -> None:
        fallback = FallbackNarrator()
        plan = fallback.generate(mixed_evidence_request)
        assert plan.generated_by == "fallback"

    def test_narrative_summary_non_empty(self, mixed_evidence_request: ReportingRequest) -> None:
        fallback = FallbackNarrator()
        plan = fallback.generate(mixed_evidence_request)
        assert len(plan.narrative_summary.strip()) > 0

    def test_narrative_summary_at_most_100_words(
        self, mixed_evidence_request: ReportingRequest
    ) -> None:
        fallback = FallbackNarrator()
        plan = fallback.generate(mixed_evidence_request)
        words = plan.narrative_summary.split()
        assert len(words) <= 100, f"narrative_summary has {len(words)} words, must be <=100"

    def test_actions_have_all_required_fields(
        self, mixed_evidence_request: ReportingRequest
    ) -> None:
        fallback = FallbackNarrator()
        plan = fallback.generate(mixed_evidence_request)
        for action in plan.actions:
            assert action.title
            assert action.description
            assert len(action.justifying_finding_ids) > 0
            assert action.effort_level in ("Low", "Medium", "High")
            assert action.confidence_note
            assert action.estimated_co2_saved_kg_per_year >= 0
            assert action.estimated_savings_inr_per_year >= 0
            assert action.payback_months >= 0

    def test_actions_description_at_most_50_words(
        self, mixed_evidence_request: ReportingRequest
    ) -> None:
        fallback = FallbackNarrator()
        plan = fallback.generate(mixed_evidence_request)
        for action in plan.actions:
            words = action.description.split()
            assert len(words) <= 50, (
                f"action.description '{action.title}' has {len(words)} words, must be <=50"
            )

    def test_action_justifying_finding_ids_from_input(
        self, mixed_evidence_request: ReportingRequest
    ) -> None:
        """All justifying_finding_ids in fallback output must be from the input."""
        fallback = FallbackNarrator()
        plan = fallback.generate(mixed_evidence_request)
        input_ids = {f.finding_id for f in mixed_evidence_request.findings} | {
            s.justifying_finding_ids[0] for s in mixed_evidence_request.optimization_scenarios
        }
        for action in plan.actions:
            for fid in action.justifying_finding_ids:
                assert fid in input_ids, f"fallback cited finding_id {fid} not present in input"

    def test_schema_valid_json(self, mixed_evidence_request: ReportingRequest) -> None:
        fallback = FallbackNarrator()
        plan = fallback.generate(mixed_evidence_request)
        serialised = plan.model_dump_json()
        parsed = json.loads(serialised)
        assert "narrative_summary" in parsed
        assert "actions" in parsed


@pytest.mark.unit
class TestFallbackNarratorMLOnly:
    def test_ml_only_produces_plan(self, ml_only_request: ReportingRequest) -> None:
        fallback = FallbackNarrator()
        plan = fallback.generate(ml_only_request)
        assert isinstance(plan, ActionPlan)
        assert plan.generated_by == "fallback"

    def test_ml_only_no_scenarios_still_produces_action(
        self, ml_only_request: ReportingRequest
    ) -> None:
        """With no optimization scenarios, fallback synthesises a generic action."""
        fallback = FallbackNarrator()
        plan = fallback.generate(ml_only_request)
        assert len(plan.actions) > 0

    def test_ml_only_confidence_note_reflects_wide_band(
        self, ml_only_request: ReportingRequest
    ) -> None:
        fallback = FallbackNarrator()
        plan = fallback.generate(ml_only_request)
        for action in plan.actions:
            note_lower = action.confidence_note.lower()
            assert (
                "lower confidence" in note_lower
                or "uncertainty" in note_lower
                or "statistical" in note_lower
            )
