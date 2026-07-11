"""ENG-3g — Explainability service package.

Provides SHAP-based root-cause attribution (ENG-3g-1) and the Explainability Bundle
assembler (ENG-3g-2) per TRD v2.0 §3.7.

Public API
----------
- ExplainabilityBundle  — the contract persisted to findings.explainability_bundle
- TopFeature, RuleCitation, ConfidenceBand, EvidenceWindow — bundle sub-models
- SHAPExplainer         — computes SHAP values against the ML Ensemble
- BundleAssembler       — mandatory gateway for creating validated bundles
- feature_registry      — deterministic feature-name → plain-language templates
"""

from services.explainability.bundle_assembler import BundleAssembler
from services.explainability.models import (
    ConfidenceBand,
    EvidenceWindow,
    ExplainabilityBundle,
    RuleCitation,
    TopFeature,
)
from services.explainability.shap_explainer import SHAPExplainer

__all__ = [
    "BundleAssembler",
    "ConfidenceBand",
    "EvidenceWindow",
    "ExplainabilityBundle",
    "RuleCitation",
    "SHAPExplainer",
    "TopFeature",
]
