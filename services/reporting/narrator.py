"""TRD §5 — LLM narrator with exact system prompt, retry, and deterministic fallback.

Pattern: structured JSON-in / JSON-out (the NarratorAgent pattern from v1), now fed
by the Explainability Bundle instead of summary statistics (TRD v2.0 §5.1).

Flow:
  1. Call Claude API with system prompt + structured user payload.
  2. Parse and validate response against ActionPlan schema.
  3. On failure: retry once with SCHEMA_EMPHASIS_SUFFIX appended to the user message.
  4. On second failure: delegate to FallbackNarrator (deterministic, no LLM).

The system prompt is a frozen constant; it is the exact text specified in TRD v2.0
§5.2 and the user request. It MUST NOT be paraphrased or parameterised.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from services.reporting.fallback import FallbackNarrator
from services.reporting.models import ActionPlan, ReportingRequest
from services.reporting.prompt_builder import SCHEMA_EMPHASIS_SUFFIX, build_user_message

logger = logging.getLogger(__name__)

# System prompt — exact text per TRD v2.0 §5.2. DO NOT PARAPHRASE OR MODIFY WITHOUT A CHANGE-REVIEW.
SYSTEM_PROMPT: str = """\
You are CarbonSense's reporting assistant. You convert structured building-energy
findings into a plain-language Carbon Action Plan for a facility manager who is not
a data scientist.

You will receive a JSON payload containing:
- One or more findings, each with an Explainability Bundle (contributing layers,
  top SHAP features with plain-language descriptions, rule citations if any,
  a confidence band, and an evidence window).
- One or more optimization scenarios, each explicitly linked to the finding_id(s)
  that justify it.

HARD RULES — these are not stylistic preferences, they are correctness requirements:
1. Every action you recommend MUST cite the specific finding(s) and feature(s) or
   rule(s) from the input that justify it. Do not generalize beyond what the input
   evidence supports.
2. Never state a causal claim ("this is happening because...") that is not directly
   supported by a top_feature or rule_citation in the input. If the input's evidence
   is weak or the confidence_band is wide, say so explicitly in plain language
   ("this finding has lower confidence because...") rather than writing confidently
   regardless of the underlying uncertainty.
3. Do not invent specific numbers. Only use kWh, cost, and CO2 figures present in
   the input payload.
4. If a finding's contributing_layers includes only "ml_ensemble" with no rule
   citation, describe it as a statistical pattern, not a confirmed mechanism — do
   not narrate a specific equipment failure unless a rule or feature explicitly
   supports that level of specificity.

OUTPUT FORMAT — respond with ONLY valid JSON matching this schema, no preamble:
{
  "narrative_summary": "<=100 words, plain language, references confidence honestly",
  "actions": [
    {
      "title": "string",
      "description": "<=50 words, plain language",
      "justifying_finding_ids": ["uuid", ...],
      "estimated_co2_saved_kg_per_year": number,
      "estimated_savings_inr_per_year": number,
      "effort_level": "Low" | "Medium" | "High",
      "payback_months": number,
      "confidence_note": "string describing confidence honestly, derived from confidence_band"
    }
  ]
}

If you cannot produce valid JSON matching this schema from the given input, return
exactly: {"error": "schema_validation_failed"}"""


class Narrator:
    """LLM narrator — structured JSON-in/JSON-out with retry and fallback.

    Args:
        client: An ``anthropic.Anthropic`` client instance. Injected for
                testability; in production pass ``anthropic.Anthropic()``.
        model:  Claude model identifier. Defaults to ``claude-3-5-haiku-20241022``.
        max_tokens: Maximum tokens in the LLM response.
    """

    DEFAULT_MODEL = "claude-3-5-haiku-20241022"
    DEFAULT_MAX_TOKENS = 2048

    def __init__(
        self,
        client: Any,  # anthropic.Anthropic — typed as Any to avoid hard import at module level
        *,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self._fallback = FallbackNarrator()

    def generate(self, request: ReportingRequest) -> ActionPlan:
        """Generate a Carbon Action Plan for *request*.

        Returns an ActionPlan with generated_by="llm" on success, or
        generated_by="fallback" when both LLM attempts fail schema validation.

        Never raises. The fallback path is always available as a last resort.
        """
        user_message = build_user_message(request)

        # Attempt 1 — standard call
        attempt1 = self._call_llm(user_message)
        result = self._parse_action_plan(attempt1)
        if result is not None:
            return result

        logger.warning(
            "Narrator: LLM response failed schema validation on attempt 1; retrying",
            extra={"model": self._model},
        )

        # Attempt 2 — retry with schema emphasis
        user_message_retry = user_message + SCHEMA_EMPHASIS_SUFFIX
        attempt2 = self._call_llm(user_message_retry)
        result = self._parse_action_plan(attempt2)
        if result is not None:
            return result

        logger.error(
            "Narrator: LLM response failed schema validation on attempt 2; "
            "falling back to deterministic narrator",
            extra={"model": self._model},
        )

        # Fallback — deterministic, always returns a complete ActionPlan
        return self._fallback.generate(request)

    def _call_llm(self, user_message: str) -> str:
        """Call the Claude API and return the raw text response.

        Returns an empty string on any API error (triggers fallback path).
        """
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            return response.content[0].text if response.content else ""
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Narrator: LLM API call failed: %s",
                exc,
                extra={"model": self._model},
            )
            return ""

    def _parse_action_plan(self, raw_text: str) -> ActionPlan | None:
        """Parse *raw_text* as an ActionPlan.

        Returns None if the text is empty, is not valid JSON, signals a schema
        error, or fails Pydantic validation.
        """
        if not raw_text.strip():
            return None

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            logger.debug("Narrator: response is not valid JSON")
            return None

        # The LLM may return {"error": "schema_validation_failed"} per the system prompt
        if isinstance(data, dict) and data.get("error") == "schema_validation_failed":
            logger.debug("Narrator: LLM self-reported schema validation failure")
            return None

        try:
            return ActionPlan(**data)
        except (ValidationError, TypeError) as exc:
            logger.debug("Narrator: ActionPlan validation failed: %s", exc)
            return None
