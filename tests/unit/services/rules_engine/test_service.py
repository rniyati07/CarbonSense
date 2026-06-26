import datetime
import uuid
import pytest
from services.rules_engine.models import Rule
from services.rules_engine.registry import RuleRegistry
from services.rules_engine.service import DomainRuleEngineService

class DummyRegistry(RuleRegistry):
    def __init__(self):
        self.rules = {
            "r1": Rule(
                rule_id="r1",
                version=1,
                effective_date=datetime.date(2026,1,1),
                author="test",
                citation="cit",
                applies_to={"circuit_type": "hvac"},
                severity="medium",
                condition="kwh > building.declared_unoccupied_baseline"
            )
        }

@pytest.mark.unit
def test_process_readings():
    registry = DummyRegistry()
    service = DomainRuleEngineService(registry)
    
    building = {"declared_unoccupied_baseline": 50}
    tenant_id = uuid.uuid4()
    building_id = uuid.uuid4()
    circuit_id = uuid.uuid4()
    
    ts = datetime.datetime(2026, 1, 1, 12, 0)
    readings = [
        {"ts": ts, "kwh": 60, "circuit_id": circuit_id, "data_quality_status": "pass"}
    ]
    circuit_types = {circuit_id: "hvac"}
    
    findings = service.process_readings(tenant_id, building_id, building, readings, circuit_types)
    assert len(findings) == 1
    assert findings[0].explainability_bundle.rule_citations[0].rule_id == "r1"
    
    # Should not fire if kwh <= baseline
    readings = [
        {"ts": ts, "kwh": 40, "circuit_id": circuit_id, "data_quality_status": "pass"}
    ]
    findings = service.process_readings(tenant_id, building_id, building, readings, circuit_types)
    assert len(findings) == 0
