"""Unit tests for services/explainability/bundle_assembler.py.

Covers the three mandatory test scenarios:
1. Mixed-evidence finding (rule + ml_ensemble) → full bundle with rule_citations.
2. ML-ensemble-only finding → top_features present, rule_citations = [].
3. Invariant enforcement (rule_citations non-empty for ml-only → ValueError).
"""

from __future__ import annotations

from datetime import UTC
from uuid import uuid4

import pytest

from services.explainability.bundle_assembler import BundleAssembler
from services.explainability.models import (
    ConfidenceBand,
    EvidenceWindow,
    ExplainabilityBundle,
    RuleCitation,
    TopFeature,
)


@pytest.mark.unit
class TestBundleAssemblerMixedEvidence:
    """SCENARIO 1 — Rule fired + ML Ensemble: full bundle with rule_citations."""

    def test_mixed_evidence_produces_full_bundle(
        self,
        top_features_sample: list[TopFeature],
        rule_citations_hvac: list[RuleCitation],
        confidence_band_high: ConfidenceBand,
        evidence_window: EvidenceWindow,
    ) -> None:
        assembler = BundleAssembler()
        bundle = assembler.assemble(
            finding_id=uuid4(),
            contributing_layers=["domain_rule", "ml_ensemble"],
            top_features=top_features_sample,
            rule_citations=rule_citations_hvac,
            confidence_band=confidence_band_high,
            evidence_window=evidence_window,
        )
        assert isinstance(bundle, ExplainabilityBundle)
        assert "domain_rule" in bundle.contributing_layers
        assert "ml_ensemble" in bundle.contributing_layers
        assert len(bundle.top_features) > 0
        assert len(bundle.rule_citations) > 0

    def test_mixed_evidence_bundle_matches_trd_contract(
        self,
        top_features_sample: list[TopFeature],
        rule_citations_hvac: list[RuleCitation],
        confidence_band_high: ConfidenceBand,
        evidence_window: EvidenceWindow,
    ) -> None:
        """Assert the bundle fields match the TRD §3.7 JSON contract exactly."""
        fid = uuid4()
        assembler = BundleAssembler()
        bundle = assembler.assemble(
            finding_id=fid,
            contributing_layers=["domain_rule", "ml_ensemble", "stl_residual"],
            top_features=top_features_sample,
            rule_citations=rule_citations_hvac,
            confidence_band=confidence_band_high,
            evidence_window=evidence_window,
        )
        # Serialise and check the JSON shape
        data = bundle.model_dump()
        assert data["finding_id"] == fid
        assert "contributing_layers" in data
        assert "top_features" in data
        assert "rule_citations" in data
        assert "confidence_band" in data
        assert "evidence_window" in data
        # confidence_band shape
        assert data["confidence_band"]["method"] == "conformal_prediction"
        assert "lower" in data["confidence_band"]
        assert "upper" in data["confidence_band"]

    def test_rule_citation_fields_present(
        self,
        top_features_sample: list[TopFeature],
        rule_citations_hvac: list[RuleCitation],
        confidence_band_high: ConfidenceBand,
        evidence_window: EvidenceWindow,
    ) -> None:
        assembler = BundleAssembler()
        bundle = assembler.assemble(
            finding_id=uuid4(),
            contributing_layers=["domain_rule", "ml_ensemble"],
            top_features=top_features_sample,
            rule_citations=rule_citations_hvac,
            confidence_band=confidence_band_high,
            evidence_window=evidence_window,
        )
        rc = bundle.rule_citations[0]
        assert rc.rule_id == "hvac_after_hours_v3"
        assert rc.version == 3
        assert "ASHRAE" in rc.citation


@pytest.mark.unit
class TestBundleAssemblerMLOnly:
    """SCENARIO 2 — ML Ensemble only: top_features present, rule_citations = []."""

    def test_ml_only_rule_citations_empty_list(
        self,
        top_features_sample: list[TopFeature],
        confidence_band_wide: ConfidenceBand,
        evidence_window: EvidenceWindow,
    ) -> None:
        assembler = BundleAssembler()
        bundle = assembler.assemble_ml_only(
            finding_id=uuid4(),
            top_features=top_features_sample,
            confidence_band=confidence_band_wide,
            evidence_window=evidence_window,
        )
        # rule_citations MUST be [] — not omitted, not None
        assert bundle.rule_citations == [], (
            "ML-only finding must have rule_citations=[], not omitted"
        )

    def test_ml_only_top_features_present(
        self,
        top_features_sample: list[TopFeature],
        confidence_band_wide: ConfidenceBand,
        evidence_window: EvidenceWindow,
    ) -> None:
        assembler = BundleAssembler()
        bundle = assembler.assemble_ml_only(
            finding_id=uuid4(),
            top_features=top_features_sample,
            confidence_band=confidence_band_wide,
            evidence_window=evidence_window,
        )
        assert len(bundle.top_features) > 0

    def test_ml_only_contributing_layers_correct(
        self,
        top_features_sample: list[TopFeature],
        confidence_band_wide: ConfidenceBand,
        evidence_window: EvidenceWindow,
    ) -> None:
        assembler = BundleAssembler()
        bundle = assembler.assemble_ml_only(
            finding_id=uuid4(),
            top_features=top_features_sample,
            confidence_band=confidence_band_wide,
            evidence_window=evidence_window,
        )
        assert bundle.contributing_layers == ["ml_ensemble"]

    def test_ml_only_with_stl_includes_stl_layer(
        self,
        top_features_sample: list[TopFeature],
        confidence_band_wide: ConfidenceBand,
        evidence_window: EvidenceWindow,
    ) -> None:
        assembler = BundleAssembler()
        bundle = assembler.assemble_ml_only(
            finding_id=uuid4(),
            top_features=top_features_sample,
            confidence_band=confidence_band_wide,
            evidence_window=evidence_window,
            include_stl=True,
        )
        assert "stl_residual" in bundle.contributing_layers
        assert bundle.rule_citations == []

    def test_rule_citations_explicit_empty_list_via_assemble(
        self,
        top_features_sample: list[TopFeature],
        confidence_band_wide: ConfidenceBand,
        evidence_window: EvidenceWindow,
    ) -> None:
        """Using assemble() with rule_citations=[] for ml_ensemble-only must work."""
        assembler = BundleAssembler()
        bundle = assembler.assemble(
            finding_id=uuid4(),
            contributing_layers=["ml_ensemble"],
            top_features=top_features_sample,
            rule_citations=[],
            confidence_band=confidence_band_wide,
            evidence_window=evidence_window,
        )
        assert bundle.rule_citations == []


@pytest.mark.unit
class TestBundleAssemblerInvariants:
    """SCENARIO 3 — Invariant enforcement."""

    def test_ml_only_with_rule_citation_raises(
        self,
        top_features_sample: list[TopFeature],
        rule_citations_hvac: list[RuleCitation],
        confidence_band_wide: ConfidenceBand,
        evidence_window: EvidenceWindow,
    ) -> None:
        """ML-only finding with non-empty rule_citations must raise ValueError."""
        assembler = BundleAssembler()
        with pytest.raises(ValueError, match="rule_citations must be"):
            assembler.assemble(
                finding_id=uuid4(),
                contributing_layers=["ml_ensemble"],
                top_features=top_features_sample,
                rule_citations=rule_citations_hvac,  # NOT allowed for ml_ensemble-only
                confidence_band=confidence_band_wide,
                evidence_window=evidence_window,
            )

    def test_empty_top_features_raises(
        self,
        rule_citations_hvac: list[RuleCitation],
        confidence_band_high: ConfidenceBand,
        evidence_window: EvidenceWindow,
    ) -> None:
        assembler = BundleAssembler()
        with pytest.raises(ValueError):
            assembler.assemble(
                finding_id=uuid4(),
                contributing_layers=["domain_rule", "ml_ensemble"],
                top_features=[],
                rule_citations=rule_citations_hvac,
                confidence_band=confidence_band_high,
                evidence_window=evidence_window,
            )

    def test_invalid_layer_name_raises(
        self,
        top_features_sample: list[TopFeature],
        confidence_band_high: ConfidenceBand,
        evidence_window: EvidenceWindow,
    ) -> None:
        assembler = BundleAssembler()
        with pytest.raises(ValueError, match="Unknown contributing layers"):
            assembler.assemble(
                finding_id=uuid4(),
                contributing_layers=["nonexistent_layer"],
                top_features=top_features_sample,
                rule_citations=[],
                confidence_band=confidence_band_high,
                evidence_window=evidence_window,
            )

    def test_confidence_band_lower_gt_upper_raises(
        self,
        top_features_sample: list[TopFeature],
        evidence_window: EvidenceWindow,
    ) -> None:
        with pytest.raises(ValueError, match="lower"):
            ConfidenceBand(lower=0.9, upper=0.1)

    def test_evidence_window_start_after_end_raises(
        self,
        top_features_sample: list[TopFeature],
    ) -> None:
        from datetime import datetime

        with pytest.raises(ValueError, match="start"):
            EvidenceWindow(
                start=datetime(2026, 6, 2, tzinfo=UTC),
                end=datetime(2026, 6, 1, tzinfo=UTC),
            )
