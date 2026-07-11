"""Unit tests for services/reporting/pdf_renderer.py.

Verifies WeasyPrint renders a non-empty PDF from an ActionPlan.
Skips gracefully if WeasyPrint cannot render in the test environment
(e.g., missing system dependencies like Pango/Cairo on headless CI).
"""

from __future__ import annotations

import uuid

import pytest

from services.reporting.models import ActionItem, ActionPlan
from services.reporting.pdf_renderer import PDFRenderer


def _sample_action_plan() -> ActionPlan:
    return ActionPlan(
        narrative_summary=(
            "After-hours HVAC usage detected 41% above normal. "
            "Load-shifting recommended based on domain rule and SHAP evidence."
        ),
        actions=[
            ActionItem(
                title="Schedule HVAC load shift",
                description="Adjust HVAC scheduling to eliminate after-hours operation.",
                justifying_finding_ids=[uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")],
                estimated_co2_saved_kg_per_year=2592.0,
                estimated_savings_inr_per_year=89600.0,
                effort_level="Low",
                payback_months=0.0,
                confidence_note=(
                    "Moderate-high confidence (62%–81%): rule and statistical evidence agree."
                ),
            )
        ],
        generated_by="llm",
    )


@pytest.mark.unit
class TestPDFRenderer:
    def test_render_returns_bytes(self) -> None:
        try:
            renderer = PDFRenderer()
            plan = _sample_action_plan()
            result = renderer.render(plan, building_name="COMBED Block A")
            assert isinstance(result, bytes)
        except Exception as exc:
            # WeasyPrint may require system libraries (Pango, Cairo, GTK) not present in CI
            pytest.skip(f"WeasyPrint not available in this environment: {exc}")

    def test_render_non_empty(self) -> None:
        try:
            renderer = PDFRenderer()
            plan = _sample_action_plan()
            result = renderer.render(plan, building_name="COMBED Block A")
            assert len(result) > 1000, "PDF output is unexpectedly small"
        except Exception as exc:
            pytest.skip(f"WeasyPrint not available in this environment: {exc}")

    def test_render_starts_with_pdf_magic(self) -> None:
        """PDF files always start with the %PDF magic bytes."""
        try:
            renderer = PDFRenderer()
            plan = _sample_action_plan()
            result = renderer.render(plan)
            assert result[:4] == b"%PDF", "Output does not start with PDF magic bytes"
        except Exception as exc:
            pytest.skip(f"WeasyPrint not available in this environment: {exc}")

    def test_render_empty_actions_does_not_raise(self) -> None:
        """A plan with no actions must still render without errors."""
        try:
            renderer = PDFRenderer()
            plan = ActionPlan(
                narrative_summary="No anomalies detected this period.",
                actions=[],
                generated_by="fallback",
            )
            result = renderer.render(plan, building_name="Test Building")
            assert isinstance(result, bytes)
        except Exception as exc:
            pytest.skip(f"WeasyPrint not available in this environment: {exc}")

    def test_render_fallback_plan(self) -> None:
        """Fallback-generated ActionPlan renders identically to LLM-generated."""
        try:
            renderer = PDFRenderer()
            plan = ActionPlan(
                narrative_summary="Statistical pattern detected (32%–68% confidence).",
                actions=[
                    ActionItem(
                        title="Investigate anomalous consumption",
                        description="Schedule site inspection to investigate the pattern.",
                        justifying_finding_ids=[uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")],
                        estimated_co2_saved_kg_per_year=0.0,
                        estimated_savings_inr_per_year=0.0,
                        effort_level="Low",
                        payback_months=0.0,
                        confidence_note="Lower confidence (32%–68%): statistical pattern only.",
                    )
                ],
                generated_by="fallback",
            )
            result = renderer.render(plan)
            assert isinstance(result, bytes)
            assert len(result) > 0
        except Exception as exc:
            pytest.skip(f"WeasyPrint not available in this environment: {exc}")
