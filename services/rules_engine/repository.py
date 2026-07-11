import json
from collections.abc import Sequence
from typing import Any, Protocol

from .models import Finding


class FindingRepository(Protocol):
    def save_all(self, findings: Sequence[Finding]) -> None: ...


class DatabaseFindingRepository:
    def __init__(self, get_connection: Any):
        self._get_connection = get_connection

    def save_all(self, findings: Sequence[Finding]) -> None:
        if not findings:
            return

        conn = self._get_connection()
        try:
            for f in findings:
                # Basic representation of postgres insert
                # tstzrange requires string format
                conn.execute(
                    """
                    INSERT INTO findings (
                        finding_id, tenant_id, building_id, circuit_id, layer_origin,
                        evidence_window, confidence, status, explainability_bundle
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        tstzrange(%s, %s, '[]'), %s, %s, %s
                    )
                    """,
                    (
                        str(f.finding_id),
                        str(f.tenant_id),
                        str(f.building_id),
                        str(f.circuit_id) if f.circuit_id else None,
                        f.layer_origin,
                        f.evidence_window_start,
                        f.evidence_window_end,
                        f.confidence,
                        f.status,
                        json.dumps(f.explainability_bundle.model_dump(mode="json")),
                    ),
                )
            if hasattr(conn, "commit"):
                conn.commit()
        finally:
            conn.close()


class InMemoryFindingRepository:
    def __init__(self) -> None:
        self.findings: list[Finding] = []

    def save_all(self, findings: Sequence[Finding]) -> None:
        self.findings.extend(findings)


class RuleRegistryRepository(Protocol):
    def get_registered_version(self, rule_id: str) -> int | None: ...


class DatabaseRuleRegistryRepository:
    def __init__(self, get_connection: Any):
        self._get_connection = get_connection

    def get_registered_version(self, rule_id: str) -> int | None:
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT version FROM rule_registry "
                "WHERE rule_id = %s ORDER BY version DESC LIMIT 1",
                (rule_id,),
            )
            row = cursor.fetchone()
            return row[0] if row else None
        finally:
            conn.close()


class InMemoryRuleRegistryRepository:
    def __init__(self, versions: dict[str, int] | None = None) -> None:
        self.versions = versions or {}

    def get_registered_version(self, rule_id: str) -> int | None:
        return self.versions.get(rule_id)
