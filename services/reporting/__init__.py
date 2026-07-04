"""TRD §5 — Explainability & Reporting Service package.

This service consumes the Explainability Bundle (ENG-3g-2) and the Optimization
Engine output (ENG-4) to generate a Carbon Action Plan via an LLM narrator
(Claude API) with retry-and-fallback, and renders it to PDF via WeasyPrint.

Public API
----------
- ReportService      — orchestrator (action plan + PDF)
- Narrator           — LLM narrator (Claude + retry + fallback)
- FallbackNarrator   — deterministic narrator (no LLM)
- PDFRenderer        — WeasyPrint PDF renderer
- ActionPlan         — the shared output schema (API + PDF, one source of truth)
- ActionItem         — a single recommended action
- ReportingRequest   — input payload
- OptimizationScenario, FindingWithBundle — supporting input models
"""

from services.reporting.fallback import FallbackNarrator
from services.reporting.models import (
    ActionItem,
    ActionPlan,
    FindingWithBundle,
    OptimizationScenario,
    ReportingRequest,
)
from services.reporting.narrator import SYSTEM_PROMPT, Narrator
from services.reporting.pdf_renderer import PDFRenderer
from services.reporting.report_service import ReportService

__all__ = [
    "ActionItem",
    "ActionPlan",
    "FallbackNarrator",
    "FindingWithBundle",
    "Narrator",
    "OptimizationScenario",
    "PDFRenderer",
    "ReportService",
    "ReportingRequest",
    "SYSTEM_PROMPT",
]
