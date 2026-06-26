import os
import yaml
from typing import Dict

from .models import Rule

class RuleRegistry:
    def __init__(self, rules_dir: str):
        self.rules_dir = rules_dir
        self.rules: Dict[str, Rule] = {}
        self.load_rules()

    def load_rules(self) -> None:
        """
        Loads all YAML rules from the rules directory and validates them.
        """
        if not os.path.exists(self.rules_dir):
            return

        for filename in os.listdir(self.rules_dir):
            if filename.endswith(('.yaml', '.yml')):
                filepath = os.path.join(self.rules_dir, filename)
                with open(filepath, 'r') as f:
                    data = yaml.safe_load(f)
                    # Validate and instantiate Rule model
                    if data:
                        rule = Rule(**data)
                        self.rules[rule.rule_id] = rule

    def get_rule(self, rule_id: str) -> Rule | None:
        return self.rules.get(rule_id)
        
    def get_all_rules(self) -> list[Rule]:
        return list(self.rules.values())
