import os
from services.rules_engine.registry import RuleRegistry

def test_registry_loads_rules(tmp_path):
    d = tmp_path / "rules"
    d.mkdir()
    p = d / "rule1.yaml"
    p.write_text('''
rule_id: test_rule
version: 1
effective_date: 2026-01-01
author: test
citation: "citation"
applies_to:
  circuit_type: hvac
severity: medium
condition: kwh > 100
    ''')
    registry = RuleRegistry(str(d))
    assert len(registry.get_all_rules()) == 1
    rule = registry.get_rule("test_rule")
    assert rule is not None
    assert rule.applies_to == {"circuit_type": "hvac"}
