from __future__ import annotations

import datetime
import json
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from services.explainability.models import (
    ConfidenceBand,
    EvidenceWindow,
    ExplainabilityBundle,
    RuleCitation,
    TopFeature,
)
from services.explainability.repository import ExplainabilityRepository
from services.rules_engine.models import Finding


def _make_ml_finding() -> Finding:
    finding_id = uuid4()
    now = datetime.datetime.now(datetime.UTC)
    bundle = ExplainabilityBundle(
        finding_id=finding_id,
        contributing_layers=["ml_ensemble"],
        top_features=[
            TopFeature(feature="after_hours_kwh_ratio", shap_value=0.41, plain_language="x")
        ],
        rule_citations=[],
        confidence_band=ConfidenceBand(lower=0.6, upper=0.8),
        evidence_window=EvidenceWindow(start=now, end=now + datetime.timedelta(hours=1)),
    )
    return Finding(
        finding_id=finding_id,
        tenant_id=uuid4(),
        building_id=uuid4(),
        circuit_id=uuid4(),
        layer_origin="ml_ensemble",
        evidence_window_start=now,
        evidence_window_end=now + datetime.timedelta(hours=1),
        confidence=0.7,
        status="open",
        explainability_bundle=bundle,
    )


def _make_rule_finding() -> Finding:
    finding_id = uuid4()
    now = datetime.datetime.now(datetime.UTC)
    bundle = ExplainabilityBundle(
        finding_id=finding_id,
        contributing_layers=["domain_rule"],
        top_features=[],
        rule_citations=[
            RuleCitation(rule_id="hvac_after_hours_v3", version=3, citation="ASHRAE GL36")
        ],
        confidence_band=None,
        evidence_window=EvidenceWindow(start=now, end=now),
    )
    return Finding(
        finding_id=finding_id,
        tenant_id=uuid4(),
        building_id=uuid4(),
        circuit_id=uuid4(),
        layer_origin="domain_rule",
        evidence_window_start=now,
        evidence_window_end=now,
        confidence=None,
        status="open",
        explainability_bundle=bundle,
    )


class TestExplainabilityRepository:
    @pytest.mark.asyncio
    async def test_save_finding_issues_single_insert(self) -> None:
        session = AsyncMock()
        repo = ExplainabilityRepository(session)
        finding = _make_ml_finding()

        await repo.save_finding(finding)

        session.execute.assert_awaited_once()
        params = session.execute.call_args.args[1]
        assert params["finding_id"] == str(finding.finding_id)
        assert params["tenant_id"] == str(finding.tenant_id)
        assert params["confidence"] == 0.7
        assert params["status"] == "open"

    @pytest.mark.asyncio
    async def test_save_finding_serializes_complete_bundle(self) -> None:
        session = AsyncMock()
        repo = ExplainabilityRepository(session)
        finding = _make_ml_finding()

        await repo.save_finding(finding)

        params = session.execute.call_args.args[1]
        bundle = json.loads(params["explainability_bundle"])
        assert bundle["contributing_layers"] == ["ml_ensemble"]
        assert bundle["top_features"][0]["feature"] == "after_hours_kwh_ratio"
        assert bundle["confidence_band"] == {
            "lower": 0.6,
            "upper": 0.8,
            "method": "conformal_prediction",
        }

    @pytest.mark.asyncio
    async def test_save_finding_handles_domain_rule_only_bundle(self) -> None:
        """The relaxed bundle invariant (domain-rule-only findings may omit
        top_features/confidence_band) must round-trip through this
        repository without error -- a regression guard against this
        repository re-imposing a stricter shape than the model itself."""
        session = AsyncMock()
        repo = ExplainabilityRepository(session)
        finding = _make_rule_finding()

        await repo.save_finding(finding)  # must not raise

        params = session.execute.call_args.args[1]
        assert params["confidence"] is None

    @pytest.mark.asyncio
    async def test_save_findings_batch_calls_save_finding_per_item(self) -> None:
        session = AsyncMock()
        repo = ExplainabilityRepository(session)
        findings = [_make_ml_finding(), _make_rule_finding()]

        await repo.save_findings(findings)

        assert session.execute.await_count == 2
