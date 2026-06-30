"""ENG-3b: Domain Rule Engine — rule_registry table.

TRD v2.0 §3.2: "Rules change via reviewed pull request and an explicit version
bump in a rule_registry table (rule_id, version, effective_date, author,
citation); ML models change on a data-driven retraining cadence (§6). Conflating
these two version histories … would make 'was this finding from a rule or a model,
and which version of either' an unanswerable question during an audit."

This migration adds the persistent, queryable rule_registry table that is the
authoritative source of rule versioning, completely independent of ML model
versioning or deployment cadence.

Adds:
  - rule_registry table with (rule_id, version) composite primary key
  - GRANT to carbonsense_app role

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE rule_registry (
            rule_id       TEXT        NOT NULL,
            version       INTEGER     NOT NULL,
            effective_date DATE       NOT NULL,
            author        TEXT        NOT NULL,
            citation      TEXT        NOT NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (rule_id, version)
        )
    """)

    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON rule_registry TO carbonsense_app")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rule_registry CASCADE")
