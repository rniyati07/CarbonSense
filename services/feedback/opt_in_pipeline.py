from __future__ import annotations

import json
import logging
import statistics
import uuid
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class OptInPipeline:
    """Computes de-identified aggregate statistics across consented tenants.

    Maintains tenant-isolation boundaries by querying each tenant individually
    (using their RLS contexts) and then aggregating the statistics in Python.
    """

    def __init__(self, get_connection: Callable[[], Any]) -> None:
        self.get_connection = get_connection

    def calculate_aggregate_priors(
        self,
        building_type: str,
        climate_zone: str,
    ) -> float | None:
        """Computes the median after_hours_kwh_ratio across opted-in tenants.

        Filters by building_type and climate_zone. Logs search/consent audits.
        """
        conn = self.get_connection()
        try:
            is_sqlalchemy = hasattr(conn, "execute") and not hasattr(conn, "cursor")

            # 1. Fetch all tenants global-level details. The canonical schema
            # (database/migrations/versions/0001_canonical_schema.py) enables
            # RLS on buildings, submeter_circuits, normalized_readings,
            # findings, feedback_labels, audit_log, and building_calendar --
            # but not on tenants itself, so it is safe to query directly here.
            if is_sqlalchemy:
                from sqlalchemy import text

                res = conn.execute(
                    text("SELECT tenant_id, cross_tenant_aggregate_opt_in FROM tenants")
                )
                tenant_rows = res.fetchall()
            else:
                cursor = conn.cursor()
                cursor.execute("SELECT tenant_id, cross_tenant_aggregate_opt_in FROM tenants")
                tenant_rows = cursor.fetchall()
        finally:
            conn.close()

        opted_in_ratios: list[float] = []

        for tenant_row in tenant_rows:
            tenant_id = tenant_row[0]
            opt_in = bool(tenant_row[1])

            # Write the check log to the audit_log table. Since audit_log has
            # RLS enabled, app.current_tenant_id must be set to this tenant
            # before the write.
            conn = self.get_connection()
            try:
                if is_sqlalchemy:
                    conn.execute(
                        text("SET LOCAL app.current_tenant_id = :tid"),
                        {"tid": str(tenant_id)},
                    )
                    conn.execute(
                        text(
                            "INSERT INTO audit_log (tenant_id, event_type, payload) "
                            "VALUES (:tid, 'cross_tenant_consent_check', :payload)"
                        ),
                        {
                            "tid": str(tenant_id),
                            "payload": json.dumps({
                                "opt_in_consent": opt_in,
                                "checked_at": str(uuid.uuid4()),
                                "pipeline": "cold_start_prior_aggregation",
                            }),
                        },
                    )
                else:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SET LOCAL app.current_tenant_id = %s", (str(tenant_id),)
                    )
                    cursor.execute(
                        "INSERT INTO audit_log (tenant_id, event_type, payload) "
                        "VALUES (%s, %s, %s)",
                        (
                            str(tenant_id),
                            "cross_tenant_consent_check",
                            json.dumps({
                                "opt_in_consent": opt_in,
                                "checked_at": str(uuid.uuid4()),
                                "pipeline": "cold_start_prior_aggregation",
                            }),
                        ),
                    )
                # CONFIRMED BUG (pre-ENG-4 integration audit): this commit was
                # previously nested inside the `else` branch above, so a
                # SQLAlchemy Connection never committed the audit_log write --
                # the consent-check record that TRD v2.0 3.8 requires to exist
                # *before* any cross-tenant aggregation would silently roll
                # back on conn.close(). Both connection types must commit.
                if hasattr(conn, "commit"):
                    conn.commit()
            except Exception as audit_err:
                logger.warning(
                    "Failed to write to audit_log for tenant %s: %s", tenant_id, audit_err
                )
                if hasattr(conn, "rollback"):
                    conn.rollback()
            finally:
                conn.close()

            # Skip queries for opted-out tenants
            if not opt_in:
                logger.info("Skipped tenant %s as they are not opted in.", tenant_id)
                continue

            # Query data per-tenant (in their RLS context)
            conn = self.get_connection()
            try:
                if is_sqlalchemy:
                    conn.execute(
                        text("SET LOCAL app.current_tenant_id = :tid"),
                        {"tid": str(tenant_id)},
                    )
                    res = conn.execute(
                        text(
                            "SELECT "
                            "SUM(CASE WHEN nr.is_peak_hour = FALSE THEN nr.kwh ELSE 0 END) "
                            "/ NULLIF(SUM(nr.kwh), 0) "
                            "FROM normalized_readings nr "
                            "JOIN submeter_circuits sc ON nr.circuit_id = sc.circuit_id "
                            "JOIN buildings b ON sc.building_id = b.building_id "
                            "WHERE b.building_type = :btype AND b.climate_zone = :czone"
                        ),
                        {"btype": building_type, "czone": climate_zone},
                    )
                    ratio = res.scalar()
                else:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SET LOCAL app.current_tenant_id = %s", (str(tenant_id),)
                    )
                    cursor.execute(
                        "SELECT "
                        "SUM(CASE WHEN nr.is_peak_hour = FALSE THEN nr.kwh ELSE 0 END) "
                        "/ NULLIF(SUM(nr.kwh), 0) "
                        "FROM normalized_readings nr "
                        "JOIN submeter_circuits sc ON nr.circuit_id = sc.circuit_id "
                        "JOIN buildings b ON sc.building_id = b.building_id "
                        "WHERE b.building_type = %s AND b.climate_zone = %s",
                        (building_type, climate_zone),
                    )
                    row = cursor.fetchone()
                    ratio = row[0] if row else None

                if ratio is not None:
                    opted_in_ratios.append(float(ratio))
            finally:
                conn.close()

        # Combine aggregates (compute median across opted-in tenants)
        if not opted_in_ratios:
            return None

        return statistics.median(opted_in_ratios)
