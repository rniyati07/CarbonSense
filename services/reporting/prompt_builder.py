"""TRD §5 — Prompt builder for the LLM narrator.

Constructs the structured user-message JSON payload sent to Claude.
The system prompt is defined once in narrator.py — this module only builds the
per-request user payload so the system prompt never drifts.
"""

from __future__ import annotations

import json
from uuid import UUID

from services.reporting.models import FindingWithBundle, OptimizationScenario, ReportingRequest


def _uuid_str(uuid: UUID) -> str:
    return str(uuid)


def _finding_payload(f: FindingWithBundle) -> dict:
    b = f.explainability_bundle
    return {
        "finding_id": _uuid_str(f.finding_id),
        "layer_origin": f.layer_origin,
        "confidence": f.confidence,
        "contributing_layers": b.contributing_layers,
        "top_features": [
            {
                "feature": tf.feature,
                "shap_value": tf.shap_value,
                "plain_language": tf.plain_language,
            }
            for tf in b.top_features
        ],
        "rule_citations": [
            {
                "rule_id": rc.rule_id,
                "version": rc.version,
                "citation": rc.citation,
            }
            for rc in b.rule_citations
        ],
        "confidence_band": {
            "lower": b.confidence_band.lower,
            "upper": b.confidence_band.upper,
            "method": b.confidence_band.method,
        },
        "evidence_window": {
            "start": b.evidence_window.start.isoformat(),
            "end": b.evidence_window.end.isoformat(),
        },
    }


def _scenario_payload(s: OptimizationScenario) -> dict:
    return {
        "scenario_id": _uuid_str(s.scenario_id),
        "scenario_model": s.scenario_model,
        "justifying_finding_ids": [_uuid_str(fid) for fid in s.justifying_finding_ids],
        "baseline_kwh": s.baseline_kwh,
        "optimized_kwh": s.optimized_kwh,
        "baseline_emissions_kg_co2": s.baseline_emissions_kg_co2,
        "optimized_emissions_kg_co2": s.optimized_emissions_kg_co2,
        "pct_reduction": s.pct_reduction,
        "estimated_annual_savings_inr": s.estimated_annual_savings_inr,
        "payback_months": s.payback_months,
    }


def build_user_message(request: ReportingRequest) -> str:
    """Build the structured JSON user message from *request*.

    Returns:
        A JSON string to pass as the user message in the Claude API call.
    """
    payload = {
        "building": request.building_name,
        "findings": [_finding_payload(f) for f in request.findings],
        "optimization_scenarios": [
            _scenario_payload(s) for s in request.optimization_scenarios
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


SCHEMA_EMPHASIS_SUFFIX = """

IMPORTANT — OUTPUT FORMAT REMINDER:
You must respond with ONLY valid JSON matching this exact schema, no prose before or after:
{
  "narrative_summary": "<string, <=100 words>",
  "actions": [
    {
      "title": "<string>",
      "description": "<string, <=50 words>",
      "justifying_finding_ids": ["<uuid>"],
      "estimated_co2_saved_kg_per_year": <number>,
      "estimated_savings_inr_per_year": <number>,
      "effort_level": "Low" | "Medium" | "High",
      "payback_months": <number>,
      "confidence_note": "<string>"
    }
  ]
}
If you cannot produce this, return exactly: {"error": "schema_validation_failed"}
"""
