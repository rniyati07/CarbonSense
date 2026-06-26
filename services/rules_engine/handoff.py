from typing import Protocol, Sequence
from .models import Finding

class RootCauseHandoff(Protocol):
    def process_findings(self, findings: Sequence[Finding]) -> None: ...

class ExplainerRootCauseHandoff:
    """
    Passes rule-engine context to the Root-Cause Attribution layer.
    """
    def process_findings(self, findings: Sequence[Finding]) -> None:
        # In a real system, this would call the Root-Cause Attribution service
        # or push to a queue (e.g., temporal workflow signal or kafka event)
        # to ensure downstream SHAP/explainability features incorporate this context.
        pass

class InMemoryRootCauseHandoff:
    def __init__(self) -> None:
        self.processed: list[Finding] = []
        
    def process_findings(self, findings: Sequence[Finding]) -> None:
        self.processed.extend(findings)
