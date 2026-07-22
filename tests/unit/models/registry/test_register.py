from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from models.registry.register import register_model_version, registered_model_name


@pytest.mark.unit
class TestRegisteredModelName:
    def test_uses_double_underscore_not_slash(self) -> None:
        """MLflow rejects '/' and ':' in registered model names -- verified
        empirically against the installed MLflow version. This name must
        never regress to using '/'."""
        tenant_id, building_id = uuid4(), uuid4()
        name = registered_model_name(tenant_id, building_id, "isolation_forest")
        assert "/" not in name
        assert ":" not in name
        assert name == f"{tenant_id}__{building_id}__isolation_forest"

    def test_different_model_types_produce_different_names(self) -> None:
        tenant_id, building_id = uuid4(), uuid4()
        assert registered_model_name(
            tenant_id, building_id, "isolation_forest"
        ) != registered_model_name(tenant_id, building_id, "autoencoder")


@pytest.mark.unit
class TestRegisterModelVersion:
    def test_registers_a_raw_log_artifact_directory(self, tmp_path: Path) -> None:
        """The Autoencoder trainer logs its checkpoint via a plain
        mlflow.log_artifact() call, not a flavor-aware log_model() -- the
        one case that broke the naive mlflow.register_model() fluent API
        against this MLflow version (verified manually; see register.py's
        module docstring). This is the regression test for that fix."""
        import mlflow

        mlflow.set_tracking_uri(f"sqlite:///{tmp_path}/mlflow.db")
        mlflow.set_experiment("test-register-model-version")
        tenant_id, building_id = uuid4(), uuid4()

        with mlflow.start_run() as run:
            checkpoint = tmp_path / "autoencoder.pt"
            checkpoint.write_bytes(b"not a real checkpoint, just bytes for the test")
            mlflow.log_artifact(str(checkpoint), "autoencoder")
            run_id = run.info.run_id
            artifact_uri = mlflow.get_artifact_uri("autoencoder")

        version = register_model_version(
            run_id=run_id,
            artifact_path="autoencoder",
            tenant_id=tenant_id,
            building_id=building_id,
            model_type="autoencoder",
            artifact_uri=artifact_uri,
        )
        assert version == "1"

    def test_second_registration_for_same_name_increments_version(self, tmp_path: Path) -> None:
        import mlflow

        mlflow.set_tracking_uri(f"sqlite:///{tmp_path}/mlflow.db")
        mlflow.set_experiment("test-register-model-version-increment")
        tenant_id, building_id = uuid4(), uuid4()

        def _log_and_register() -> str:
            with mlflow.start_run() as run:
                checkpoint = tmp_path / f"{run.info.run_id}.pt"
                checkpoint.write_bytes(b"bytes")
                mlflow.log_artifact(str(checkpoint), "autoencoder")
                run_id = run.info.run_id
                artifact_uri = mlflow.get_artifact_uri("autoencoder")
            return register_model_version(
                run_id=run_id,
                artifact_path="autoencoder",
                tenant_id=tenant_id,
                building_id=building_id,
                model_type="autoencoder",
                artifact_uri=artifact_uri,
            )

        v1 = _log_and_register()
        v2 = _log_and_register()
        assert v1 == "1"
        assert v2 == "2"
