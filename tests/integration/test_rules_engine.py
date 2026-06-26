import datetime
import uuid
from services.rules_engine.models import Rule, RuleCitation, Finding
from services.rules_engine.registry import RuleRegistry
from services.rules_engine.service import DomainRuleEngineService
from services.rules_engine.repository import InMemoryFindingRepository, InMemoryRuleRegistryRepository
from services.rules_engine.handoff import InMemoryRootCauseHandoff

def test_integration_domain_rule_engine(tmp_path):
    # Setup YAML Rules
    d = tmp_path / "rules"
    d.mkdir()
    p = d / "test_rule.yaml"
    p.write_text('''
rule_id: test_rule
version: 2
effective_date: 2026-01-01
author: test
citation: "citation"
applies_to:
  circuit_type: hvac
severity: medium
condition: kwh > 100
    ''')
    
    # 1. Test version bump validation
    # If the DB has version 3, it should fail to load version 2.
    db_repo = InMemoryRuleRegistryRepository({"test_rule": 3})
    
    try:
        RuleRegistry(str(d), repository=db_repo)
        assert False, "Should have raised ValueError on version regression"
    except ValueError as e:
        assert "Version regression" in str(e)
        
    # Now simulate DB having version 1. It should load successfully.
    db_repo = InMemoryRuleRegistryRepository({"test_rule": 1})
    registry = RuleRegistry(str(d), repository=db_repo)
    assert len(registry.get_all_rules()) == 1

    # 2. Test full engine flow
    finding_repo = InMemoryFindingRepository()
    handoff = InMemoryRootCauseHandoff()
    
    service = DomainRuleEngineService(
        rule_registry=registry,
        finding_repository=finding_repo,
        root_cause_handoff=handoff
    )
    
    tenant_id = uuid.uuid4()
    building_id = uuid.uuid4()
    circuit_id = uuid.uuid4()
    
    readings = [
        {"ts": datetime.datetime(2026, 1, 1, 12, 0), "kwh": 120, "circuit_id": circuit_id, "data_quality_status": "pass"}
    ]
    circuit_types = {circuit_id: "hvac"}
    building_context = {}
    
    # Process
    findings = service.process_readings(tenant_id, building_id, building_context, readings, circuit_types)
    
    # Verify processing logic
    assert len(findings) == 1
    assert findings[0].layer_origin == "domain_rule"
    
    # Verify persistence
    assert len(finding_repo.findings) == 1
    assert finding_repo.findings[0].layer_origin == "domain_rule"
    
    # Verify handoff
    assert len(handoff.processed) == 1
    assert handoff.processed[0].layer_origin == "domain_rule"

import json
import uuid
import pytest
from pathlib import Path

@pytest.mark.integration
def test_integration_golden_fixture():
    # 1. Load real YAML rules from services/rules_engine/rules
    rules_dir = Path("services/rules_engine/rules").absolute()
    
    # We pass an empty in-memory repository to simulate no previously stored rules.
    # The registry will load the YAML files as authority for the test.
    db_repo = InMemoryRuleRegistryRepository()
    registry = RuleRegistry(str(rules_dir), repository=db_repo)
    
    # 2. Setup service
    finding_repo = InMemoryFindingRepository()
    handoff = InMemoryRootCauseHandoff()
    service = DomainRuleEngineService(
        rule_registry=registry,
        finding_repository=finding_repo,
        root_cause_handoff=handoff
    )
    
    # 3. Load golden fixture
    fixture_path = Path("tests/fixtures/rules_engine/golden_reading.json").absolute()
    with open(fixture_path, "r") as f:
        fixture_data = json.load(f)
        
    tenant_id = uuid.UUID(fixture_data["tenant_id"])
    building_id = uuid.UUID(fixture_data["building_id"])
    building_context = fixture_data["building_context"]
    
    # Parse circuit types
    circuit_types = {uuid.UUID(k): v for k, v in fixture_data["circuit_types"].items()}
    
    # Parse readings
    readings = []
    for r in fixture_data["readings"]:
        readings.append({
            "ts": datetime.datetime.fromisoformat(r["ts"]),
            "kwh": r["kwh"],
            "circuit_id": uuid.UUID(r["circuit_id"]),
            "data_quality_status": r["data_quality_status"]
        })
        
    # 4. Process readings
    findings = service.process_readings(tenant_id, building_id, building_context, readings, circuit_types)
    
    # 5. Assert findings match expectations
    expected_rules = set(fixture_data["expected_finding_rules"])
    actual_rules = {f.explainability_bundle.rule_citations[0].rule_id for f in findings}
    
    assert actual_rules == expected_rules, f"Expected {expected_rules}, but got {actual_rules}"
