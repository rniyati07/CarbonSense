"""TRD §5 — Reporting Service orchestrator.

ReportService is the public entry point for the Reporting Service. It orchestrates:
  1. The Narrator (LLM + retry + fallback) to produce an ActionPlan.
  2. The PDFRenderer to produce a PDF from that same ActionPlan.

Usage::

    import anthropic
    from services.reporting import ReportService

    service = ReportService(anthropic_client=anthropic.Anthropic())
    plan = service.generate_action_plan(request)
    pdf_bytes = service.generate_pdf(request, building_name="COMBED Block A")
"""

from __future__ import annotations

import logging
from typing import Any

from services.reporting.models import ActionPlan, ReportingRequest
from services.reporting.narrator import Narrator
from services.reporting.pdf_renderer import PDFRenderer

logger = logging.getLogger(__name__)


class ReportService:
    """Orchestrates action plan generation and PDF rendering.

    Args:
        anthropic_client: An ``anthropic.Anthropic`` instance. Injected for
                          testability.
        narrator_model:   Claude model identifier forwarded to Narrator.
    """

    def __init__(
        self,
        *,
        anthropic_client: Any,
        narrator_model: str = Narrator.DEFAULT_MODEL,
    ) -> None:
        self._narrator = Narrator(anthropic_client, model=narrator_model)
        self._renderer = PDFRenderer()

    def generate_action_plan(self, request: ReportingRequest) -> ActionPlan:
        """Generate a Carbon Action Plan for *request*.

        Returns an ActionPlan with generated_by="llm" on success or
        generated_by="fallback" when the LLM path fails twice.
        """
        return self._narrator.generate(request)

    def generate_pdf(self, request: ReportingRequest, building_name: str | None = None) -> bytes:
        """Generate a PDF Carbon Action Plan for *request*.

        Calls generate_action_plan() first, then renders the same ActionPlan
        object to PDF — guaranteeing one source of truth.

        Args:
            request:       The reporting request.
            building_name: Overrides request.building_name in the PDF header.

        Returns:
            PDF bytes.
        """
        action_plan = self.generate_action_plan(request)
        name = building_name or request.building_name
        return self._renderer.render(action_plan, building_name=name)
