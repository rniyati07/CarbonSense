"""Unit tests for services/reporting/narrator.py.

Three required test scenarios (per user specification):
  1. Mixed-evidence finding → specific, cited prose
  2. Low-confidence ML-only finding → hedged, non-mechanism-specific prose
  3. JSON schema fails twice → deterministic fallback, complete and well-formed
  4. Retry path: first call fails, second succeeds (retry exercised)
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

from services.reporting.models import ActionPlan, ReportingRequest
from services.reporting.narrator import Narrator, SYSTEM_PROMPT
from tests.unit.services.reporting.conftest import FINDING_ID_MIXED, FINDING_ID_ML_ONLY


def _make_llm_client(response_text: str) -> MagicMock:
    """Create a mock anthropic.Anthropic client returning *response_text*."""
    client = MagicMock()
    msg = MagicMock()
    msg.content = [MagicMock(text=response_text)]
    client.messages.create.return_value = msg
    return client


def _make_failing_client() -> MagicMock:
    """Create a mock anthropic client whose call raises an exception."""
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("API unavailable")
    return client


def _make_bad_json_client() -> MagicMock:
    """Create a mock client returning invalid JSON (fails schema on every call)."""
    client = MagicMock()
    msg = MagicMock()
    msg.content = [MagicMock(text='{"error": "schema_validation_failed"}')]
    client.messages.create.return_value = msg
    return client


@pytest.mark.unit
class TestNarratorMixedEvidence:
    def test_mixed_evidence_produces_action_plan(
        self,
        mixed_evidence_request: ReportingRequest,
        valid_action_plan_json: str,
    ) -> None:
        client = _make_llm_client(valid_action_plan_json)
        narrator = Narrator(client)
        plan = narrator.generate(mixed_evidence_request)

        assert isinstance(plan, ActionPlan)
        assert plan.generated_by == "llm"

    def test_mixed_evidence_actions_cite_finding_ids(
        self,
        mixed_evidence_request: ReportingRequest,
        valid_action_plan_json: str,
    ) -> None:
        client = _make_llm_client(valid_action_plan_json)
        narrator = Narrator(client)
        plan = narrator.generate(mixed_evidence_request)

        # Every action must cite at least one finding_id from the input
        input_finding_ids = {f.finding_id for f in mixed_evidence_request.findings}
        for action in plan.actions:
            cited = set(action.justifying_finding_ids)
            assert cited & input_finding_ids, (
                f"Action '{action.title}' does not cite any input finding_id"
            )

    def test_mixed_evidence_narrative_non_empty(
        self,
        mixed_evidence_request: ReportingRequest,
        valid_action_plan_json: str,
    ) -> None:
        client = _make_llm_client(valid_action_plan_json)
        narrator = Narrator(client)
        plan = narrator.generate(mixed_evidence_request)
        assert len(plan.narrative_summary.split()) > 0

    def test_llm_called_with_system_prompt(
        self,
        mixed_evidence_request: ReportingRequest,
        valid_action_plan_json: str,
    ) -> None:
        client = _make_llm_client(valid_action_plan_json)
        narrator = Narrator(client)
        narrator.generate(mixed_evidence_request)

        call_kwargs = client.messages.create.call_args
        assert call_kwargs.kwargs.get("system") == SYSTEM_PROMPT


@pytest.mark.unit
class TestNarratorMLOnlyHedged:
    def test_ml_only_produces_action_plan(
        self,
        ml_only_request: ReportingRequest,
        hedged_action_plan_json: str,
    ) -> None:
        client = _make_llm_client(hedged_action_plan_json)
        narrator = Narrator(client)
        plan = narrator.generate(ml_only_request)

        assert isinstance(plan, ActionPlan)
        assert plan.generated_by == "llm"

    def test_ml_only_confidence_note_references_uncertainty(
        self,
        ml_only_request: ReportingRequest,
        hedged_action_plan_json: str,
    ) -> None:
        client = _make_llm_client(hedged_action_plan_json)
        narrator = Narrator(client)
        plan = narrator.generate(ml_only_request)

        # The confidence_note must reflect the wide confidence band
        for action in plan.actions:
            note_lower = action.confidence_note.lower()
            uncertainty_words = ["uncertainty", "lower confidence", "statistical", "pattern only"]
            assert any(w in note_lower for w in uncertainty_words), (
                f"confidence_note does not acknowledge uncertainty: {action.confidence_note!r}"
            )

    def test_ml_only_narrative_mentions_statistical(
        self,
        ml_only_request: ReportingRequest,
        hedged_action_plan_json: str,
    ) -> None:
        client = _make_llm_client(hedged_action_plan_json)
        narrator = Narrator(client)
        plan = narrator.generate(ml_only_request)

        summary_lower = plan.narrative_summary.lower()
        # Must be hedged — should mention "statistical" or "confidence"
        hedge_words = ["statistical", "confidence", "pattern", "uncertainty"]
        assert any(w in summary_lower for w in hedge_words), (
            f"narrative_summary not hedged for ml-only finding: {plan.narrative_summary!r}"
        )


@pytest.mark.unit
class TestNarratorFallback:
    def test_schema_fails_twice_returns_fallback(
        self,
        mixed_evidence_request: ReportingRequest,
    ) -> None:
        """Both LLM attempts fail → FallbackNarrator is used → complete ActionPlan."""
        client = _make_bad_json_client()
        narrator = Narrator(client)
        plan = narrator.generate(mixed_evidence_request)

        assert isinstance(plan, ActionPlan), "Must return ActionPlan, not raise"
        assert plan.generated_by == "fallback"

    def test_fallback_output_is_schema_valid(
        self,
        mixed_evidence_request: ReportingRequest,
    ) -> None:
        client = _make_bad_json_client()
        narrator = Narrator(client)
        plan = narrator.generate(mixed_evidence_request)

        # Verify the fallback ActionPlan is fully serialisable as valid JSON
        serialised = plan.model_dump_json()
        parsed = json.loads(serialised)
        assert "narrative_summary" in parsed
        assert "actions" in parsed
        assert isinstance(parsed["actions"], list)

    def test_fallback_narrative_non_empty(
        self,
        mixed_evidence_request: ReportingRequest,
    ) -> None:
        client = _make_bad_json_client()
        narrator = Narrator(client)
        plan = narrator.generate(mixed_evidence_request)
        assert len(plan.narrative_summary.strip()) > 0

    def test_fallback_actions_have_required_fields(
        self,
        mixed_evidence_request: ReportingRequest,
    ) -> None:
        client = _make_bad_json_client()
        narrator = Narrator(client)
        plan = narrator.generate(mixed_evidence_request)

        for action in plan.actions:
            assert action.title
            assert action.description
            assert len(action.justifying_finding_ids) > 0
            assert action.effort_level in ("Low", "Medium", "High")
            assert action.confidence_note

    def test_api_exception_triggers_fallback(
        self,
        mixed_evidence_request: ReportingRequest,
    ) -> None:
        """LLM API raises exception on both calls → fallback still returns ActionPlan."""
        client = _make_failing_client()
        narrator = Narrator(client)
        plan = narrator.generate(mixed_evidence_request)

        assert isinstance(plan, ActionPlan)
        assert plan.generated_by == "fallback"

    def test_retry_called_before_fallback(
        self,
        mixed_evidence_request: ReportingRequest,
    ) -> None:
        """The LLM must be called exactly 2 times before falling back."""
        client = _make_bad_json_client()
        narrator = Narrator(client)
        narrator.generate(mixed_evidence_request)
        assert client.messages.create.call_count == 2


@pytest.mark.unit
class TestNarratorRetry:
    def test_retry_succeeds_on_second_attempt(
        self,
        mixed_evidence_request: ReportingRequest,
        valid_action_plan_json: str,
    ) -> None:
        """First call returns invalid JSON; second call returns valid JSON."""
        client = MagicMock()
        bad_msg = MagicMock()
        bad_msg.content = [MagicMock(text='{"error": "schema_validation_failed"}')]
        good_msg = MagicMock()
        good_msg.content = [MagicMock(text=valid_action_plan_json)]
        client.messages.create.side_effect = [bad_msg, good_msg]

        narrator = Narrator(client)
        plan = narrator.generate(mixed_evidence_request)

        assert plan.generated_by == "llm"
        assert client.messages.create.call_count == 2

    def test_retry_message_contains_schema_emphasis(
        self,
        mixed_evidence_request: ReportingRequest,
        valid_action_plan_json: str,
    ) -> None:
        """Second call's user message contains the schema-emphasis suffix."""
        client = MagicMock()
        bad_msg = MagicMock()
        bad_msg.content = [MagicMock(text='{"bad": "json structure"}')]
        good_msg = MagicMock()
        good_msg.content = [MagicMock(text=valid_action_plan_json)]
        client.messages.create.side_effect = [bad_msg, good_msg]

        narrator = Narrator(client)
        narrator.generate(mixed_evidence_request)

        # Second call's user content must contain schema emphasis
        second_call_kwargs = client.messages.create.call_args_list[1]
        user_messages = second_call_kwargs.kwargs.get("messages", [])
        user_content = " ".join(m.get("content", "") for m in user_messages)
        assert "IMPORTANT" in user_content or "schema" in user_content.lower()
