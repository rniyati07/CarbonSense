import datetime
from typing import Any
from uuid import UUID

from .models import Finding, ExplainabilityBundle, RuleCitation
from .registry import RuleRegistry
from .evaluator import evaluate_condition
from .repository import FindingRepository
from .handoff import RootCauseHandoff


class DictToObject:
    """Wrapper to allow dot-notation access to dict keys."""
    def __init__(self, d: dict):
        self._d = d

    def __getattr__(self, name: str) -> Any:
        if name in self._d:
            return self._d[name]
        raise AttributeError(f"No attribute {name}")


class DomainRuleEngineService:
    def __init__(
        self, 
        rule_registry: RuleRegistry, 
        finding_repository: FindingRepository | None = None,
        root_cause_handoff: RootCauseHandoff | None = None
    ):
        self.registry = rule_registry
        self.finding_repository = finding_repository
        self.root_cause_handoff = root_cause_handoff

    def _matches_applies_to(self, applies_to: dict[str, str], context: dict[str, Any]) -> bool:
        if not applies_to:
            return True
        for key, value in applies_to.items():
            ctx_val = context.get(key)
            if ctx_val != value:
                return False
        return True

    def process_readings(
        self,
        tenant_id: UUID,
        building_id: UUID,
        building_context: Any,
        readings: list[Any],
        circuit_types: dict[UUID, str]
    ) -> list[Finding]:
        """
        Evaluates rules against a batch of readings for a building.
        Returns a list of generated Findings.
        """
        findings = []
        rules = self.registry.get_all_rules()

        # Ensure building_context is an object that supports dot notation
        if isinstance(building_context, dict):
            b_obj = DictToObject(building_context)
        else:
            b_obj = building_context

        for reading in readings:
            # Convert reading object/dict to attribute-accessible values
            if isinstance(reading, dict):
                data_quality_status = reading.get("data_quality_status", "pass")
                circuit_id = reading.get("circuit_id")
                ts = reading.get("ts")
                kwh = reading.get("kwh")
            else:
                data_quality_status = getattr(reading, "data_quality_status", "pass")
                circuit_id = getattr(reading, "circuit_id", None)
                ts = getattr(reading, "ts", None)
                kwh = getattr(reading, "kwh", None)
            
            if data_quality_status == "quarantined":
                continue

            circuit_type = circuit_types.get(circuit_id) if circuit_id else None
            
            # Setup the context for evaluation
            context = {
                "ts": ts,
                "kwh": kwh,
                "building": b_obj,
                "circuit_type": circuit_type
            }

            for rule in rules:
                if not self._matches_applies_to(rule.applies_to, context):
                    continue

                if evaluate_condition(rule.condition, context):
                    # Rule fired! Create a Finding
                    bundle = ExplainabilityBundle(
                        contributing_layers=["domain_rule"],
                        rule_citations=[
                            RuleCitation(
                                rule_id=rule.rule_id,
                                version=rule.version,
                                citation=rule.citation
                            )
                        ],
                        evidence_window={
                            "start": ts,
                            "end": ts
                        }
                    )
                    
                    finding = Finding(
                        tenant_id=tenant_id,
                        building_id=building_id,
                        circuit_id=circuit_id,
                        layer_origin="domain_rule",
                        evidence_window_start=ts,
                        evidence_window_end=ts,
                        explainability_bundle=bundle
                    )
                    findings.append(finding)

        if self.finding_repository and findings:
            self.finding_repository.save_all(findings)
            
        if self.root_cause_handoff and findings:
            self.root_cause_handoff.process_findings(findings)

        return findings
