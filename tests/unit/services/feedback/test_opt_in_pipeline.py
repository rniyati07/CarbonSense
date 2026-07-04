from __future__ import annotations

import json
import uuid
import pytest

from services.feedback.opt_in_pipeline import OptInPipeline


@pytest.mark.unit
class TestOptInPipeline:
    def test_calculate_aggregate_priors_consent_filtering(
        self,
        tenant_id: uuid.UUID,
        mock_connection: any,
    ) -> None:
        tenant_a = tenant_id
        tenant_b = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

        mock_connection.cursor_obj.query_responses = {
            "tenants": [[(tenant_a, True), (tenant_b, False)]],
            "normalized_readings": [[(0.42,)]],
        }

        def get_conn():
            return mock_connection

        pipeline = OptInPipeline(get_connection=get_conn)
        result = pipeline.calculate_aggregate_priors(
            building_type="office",
            climate_zone="Asia/Kolkata",
        )

        # Assert result only contains Tenant A's value
        assert result == 0.42

        # Verify audit logs were written for BOTH tenants
        queries = mock_connection.executed_queries
        
        has_audit_a = False
        has_audit_b = False
        for q in queries:
            sql, params = q
            if "INSERT INTO audit_log" in sql:
                if str(tenant_a) in str(params):
                    has_audit_a = True
                if str(tenant_b) in str(params):
                    has_audit_b = True

        assert has_audit_a is True
        assert has_audit_b is True

        # Verify no normalized readings ratio query was executed for Tenant B
        tenant_b_query_runs = False
        for q in queries:
            sql, params = q
            if "normalized_readings" in sql and str(tenant_b) in str(params):
                tenant_b_query_runs = True

        assert tenant_b_query_runs is False, (
            "SECURITY BREACH: Query executed for non-opted-in tenant's normalized readings!"
        )

    def test_calculate_aggregate_priors_multiple_opted_in_tenants(
        self,
        tenant_id: uuid.UUID,
        mock_connection: any,
    ) -> None:
        tenant_a = tenant_id
        tenant_b = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        tenant_c = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")

        mock_connection.cursor_obj.query_responses = {
            "tenants": [[(tenant_a, True), (tenant_b, True), (tenant_c, False)]],
            "normalized_readings": [[(0.3,)], [(0.5,)]],
        }

        def get_conn():
            return mock_connection

        pipeline = OptInPipeline(get_connection=get_conn)
        result = pipeline.calculate_aggregate_priors(
            building_type="office",
            climate_zone="Asia/Kolkata",
        )

        # Median of [0.3, 0.5] is 0.4
        assert result == 0.4

        # Verify no ratio query ran for tenant C
        queries = mock_connection.executed_queries
        tenant_c_query_runs = False
        for q in queries:
            sql, params = q
            if "normalized_readings" in sql and str(tenant_c) in str(params):
                tenant_c_query_runs = True
        
        assert tenant_c_query_runs is False

    def test_calculate_aggregate_priors_no_data(
        self,
        tenant_id: uuid.UUID,
        mock_connection: any,
    ) -> None:
        # Tenant A opted in but has no data (returns None)
        mock_connection.cursor_obj.query_responses = {
            "tenants": [[(tenant_id, True)]],
            "normalized_readings": [[(None,)]],
        }

        def get_conn():
            return mock_connection

        pipeline = OptInPipeline(get_connection=get_conn)
        result = pipeline.calculate_aggregate_priors(
            building_type="office",
            climate_zone="Asia/Kolkata",
        )

        assert result is None
