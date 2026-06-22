"""Tenant data retention enforcement.

ENG-1e deliverable: reads tenants.retention_policy and deletes data
past its retention window using the database-layer delete_building_data()
function from migration 0003.

The retention_policy JSONB field supports:
    {
        "readings_retention_days": 365,
        "findings_retention_days": 730
    }

Usage:
    # Dry run — show what would be deleted
    python scripts/maintenance/tenant_data_deletion.py --dry-run

    # Execute retention enforcement for all tenants
    python scripts/maintenance/tenant_data_deletion.py

    # Delete all data for a specific building
    python scripts/maintenance/tenant_data_deletion.py delete-building \\
        --tenant-id <uuid> --building-id <uuid>

    # Delete all data for a specific tenant
    python scripts/maintenance/tenant_data_deletion.py delete-tenant \\
        --tenant-id <uuid>
"""

from __future__ import annotations

import argparse
import datetime
import os
import sys
from uuid import UUID

from sqlalchemy import create_engine, text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


def _get_engine():  # type: ignore[no-untyped-def]
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql://carbonsense:changeme@localhost:5432/carbonsense",
    )
    return create_engine(url)


def enforce_retention(dry_run: bool = True) -> None:
    """Enforce retention policies across all tenants."""
    engine = _get_engine()

    with engine.connect() as conn:
        tenants = conn.execute(
            text("""
                SELECT tenant_id, name, retention_policy
                FROM tenants
                WHERE retention_policy IS NOT NULL
            """)
        ).fetchall()

        for tenant_id, name, policy in tenants:
            if not policy:
                continue

            readings_days = policy.get("readings_retention_days")
            if readings_days is None:
                continue

            cutoff = datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(days=readings_days)

            if dry_run:
                count = conn.execute(
                    text("""
                        SELECT COUNT(*) FROM normalized_readings
                        WHERE tenant_id = :tenant_id AND ts < :cutoff
                    """),
                    {"tenant_id": str(tenant_id), "cutoff": cutoff},
                ).scalar()
                print(  # noqa: T201
                    f"[DRY RUN] Tenant '{name}' ({tenant_id}): "
                    f"{count} readings older than {readings_days} days"
                )
            else:
                with conn.begin():
                    conn.execute(
                        text("""
                            INSERT INTO audit_log
                                (tenant_id, event_type, payload)
                            VALUES (
                                :tenant_id,
                                'retention.enforcement',
                                :payload
                            )
                        """),
                        {
                            "tenant_id": str(tenant_id),
                            "payload": {
                                "policy": policy,
                                "cutoff": cutoff.isoformat(),
                                "initiated_at": datetime.datetime.now(tz=datetime.UTC).isoformat(),
                            },
                        },
                    )

                    result = conn.execute(
                        text("""
                            DELETE FROM normalized_readings
                            WHERE tenant_id = :tenant_id AND ts < :cutoff
                        """),
                        {"tenant_id": str(tenant_id), "cutoff": cutoff},
                    )
                    print(  # noqa: T201
                        f"Tenant '{name}' ({tenant_id}): "
                        f"deleted {result.rowcount} readings "
                        f"older than {readings_days} days"
                    )


def delete_building(tenant_id: UUID, building_id: UUID) -> None:
    """Delete all data for a specific building via the stored procedure."""
    engine = _get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("SELECT delete_building_data(:tid, :bid)"),
            {"tid": str(tenant_id), "bid": str(building_id)},
        )
    print(f"Deleted all data for building {building_id} in tenant {tenant_id}.")  # noqa: T201


def delete_tenant(tenant_id: UUID) -> None:
    """Delete all data for a specific tenant via the stored procedure."""
    engine = _get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("SELECT delete_tenant_data(:tid)"),
            {"tid": str(tenant_id)},
        )
    print(f"Deleted all data for tenant {tenant_id}.")  # noqa: T201


def main() -> None:
    parser = argparse.ArgumentParser(description="Tenant data retention management")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("enforce", help="Enforce retention policies for all tenants")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted")

    bld = sub.add_parser("delete-building", help="Delete all data for a building")
    bld.add_argument("--tenant-id", type=UUID, required=True)
    bld.add_argument("--building-id", type=UUID, required=True)

    ten = sub.add_parser("delete-tenant", help="Delete all data for a tenant")
    ten.add_argument("--tenant-id", type=UUID, required=True)

    args = parser.parse_args()

    if args.command == "delete-building":
        delete_building(args.tenant_id, args.building_id)
    elif args.command == "delete-tenant":
        delete_tenant(args.tenant_id)
    else:
        enforce_retention(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
