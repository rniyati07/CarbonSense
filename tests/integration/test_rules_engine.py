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
