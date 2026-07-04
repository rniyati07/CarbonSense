"""ENG-3g-2 — Explainability Bundle assembler.

The BundleAssembler is the single, mandatory path through which a finding receives
an Explainability Bundle before it may be persisted to findings.explainability_bundle
or surfaced to a user.

HARD RULE (DATA_AND_MODEL_STRATEGY §4.4, TRD v2.0 §3.7):
  No service may write directly to `findings` without going through this assembler.
  A finding without a bundle is not trustworthy enough to show a user.
"""

from __future__ import annotations

from uuid import UUID

from services.explainability.models import (
    ConfidenceBand,
    EvidenceWindow,
    ExplainabilityBundle,
    RuleCitation,
    TopFeature,
)


class BundleAssembler:
    """Assembles a validated ExplainabilityBundle from pipeline-layer outputs.

    This is a stateless service class — all state comes in through :meth:`assemble`.
    Instantiate once and reuse.

    Example::

        assembler = BundleAssembler()
        bundle = assembler.assemble(
            finding_id=uuid4(),
            contributing_layers=["domain_rule", "ml_ensemble"],
            top_features=shap_explainer.explain(feature_row),
            rule_citations=[RuleCitation(...)],
            confidence_band=ConfidenceBand(lower=0.62, upper=0.81),
            evidence_window=EvidenceWindow(start=..., end=...),
        )
    """

    def assemble(
        self,
        *,
        finding_id: UUID,
        contributing_layers: list[str],
        top_features: list[TopFeature],
        rule_citations: list[RuleCitation],
        confidence_band: ConfidenceBand,
        evidence_window: EvidenceWindow,
    ) -> ExplainabilityBundle:
        """Assemble and validate a complete ExplainabilityBundle.

        Args:
            finding_id:          UUID of the finding this bundle describes.
            contributing_layers: Which pipeline layers fired, e.g.
                                 ["domain_rule", "ml_ensemble", "stl_residual"].
            top_features:        SHAP-ranked TopFeature list (from SHAPExplainer).
                                 Must be non-empty.
            rule_citations:      Domain rules that fired. Pass [] when no rule fired;
                                 do NOT omit the argument.
            confidence_band:     Calibrated confidence interval from ENG-3f.
            evidence_window:     Time range over which the anomaly was observed.

        Returns:
            A fully validated ExplainabilityBundle ready for persistence to
            findings.explainability_bundle.

        Raises:
            ValueError: If the bundle fails its contract invariants (enforced by
                        ExplainabilityBundle's model validators).
        """
        return ExplainabilityBundle(
            finding_id=finding_id,
            contributing_layers=contributing_layers,
            top_features=top_features,
            rule_citations=rule_citations,
            confidence_band=confidence_band,
            evidence_window=evidence_window,
        )

    def assemble_ml_only(
        self,
        *,
        finding_id: UUID,
        top_features: list[TopFeature],
        confidence_band: ConfidenceBand,
        evidence_window: EvidenceWindow,
        include_stl: bool = False,
    ) -> ExplainabilityBundle:
        """Convenience method for ML-ensemble-only (± STL) findings.

        Rule_citations is always [] for this path, and the model validator
        enforces that invariant at construction time.

        Args:
            finding_id:      UUID of the finding.
            top_features:    Non-empty SHAP feature list.
            confidence_band: Calibrated confidence interval.
            evidence_window: Anomaly time range.
            include_stl:     If True, contributing_layers includes "stl_residual".

        Returns:
            ExplainabilityBundle with rule_citations=[].
        """
        layers: list[str] = ["ml_ensemble"]
        if include_stl:
            layers.append("stl_residual")

        return self.assemble(
            finding_id=finding_id,
            contributing_layers=layers,
            top_features=top_features,
            rule_citations=[],  # HARD RULE: must be [] for ml-only findings
            confidence_band=confidence_band,
            evidence_window=evidence_window,
        )
