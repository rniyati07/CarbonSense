"""ENG-6a/ROADMAP ENG-6a — MLflow Model Registry registration.

Closes the TODO(ENG-6a) left in models/training/isolation_forest.py and
models/training/autoencoder.py: both trainers already log a complete run
(model + scaler + rule_ids artifacts) via mlflow.start_run()/log_model();
this is the one call neither could make on its own, since registering a
model version is a platform-level Model Registry concern (TRD v2.0 §6.1),
not something either trainer should own individually.

URI convention (TRD v2.0 §6.1): `models:/{tenant_id}/{building_id}/{layer}/{version}`.
`layer` is the model_type ("isolation_forest" | "autoencoder") -- the two
ensemble members are independently versioned, evaluated, and promoted
(LocalModelRegistry.load_isolation_forest/load_autoencoder already look
them up separately by model_type tag), so each gets its own registered-
model name rather than sharing one generic "ml_ensemble" name. `version`
is MLflow's own auto-incremented version number for that registered name,
not something callers assign.

MLflow registered-model names reject '/' and ':' outright (verified
against the installed MLflow version -- not a style choice), so the name
segments are joined with '__' rather than '/' -- the encoded identity is
identical to TRD's convention, just delimited with a separator MLflow's
registry will actually accept.

Requires a database-backed MLflow tracking store (the default
sqlite:///./local_model_registry/mlflow.db configured in
shared/config/ml_registry.py) -- MLflow's Model Registry API is not
available against a plain filesystem store.

Uses MlflowClient.create_model_version() directly rather than the
fluent mlflow.register_model() convenience wrapper -- verified empirically
against the installed MLflow version that register_model() requires a
"Logged Model" entity (only created by flavor-aware log_model() calls,
e.g. mlflow.sklearn.log_model()) and raises "Unable to find a
logged_model with artifact_path..." for a plain mlflow.log_artifact()
directory, which is exactly how the Autoencoder trainer logs its
artifact (a raw torch.save() checkpoint, not a pyfunc/pytorch flavor
model -- see models/training/autoencoder.py). create_model_version()
predates that requirement and registers directly from a run artifact
URI regardless of how it was logged, so one registration path works for
both trainers.
"""

from __future__ import annotations

import contextlib
import logging
from uuid import UUID

from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

logger = logging.getLogger(__name__)


def registered_model_name(tenant_id: UUID, building_id: UUID, model_type: str) -> str:
    return f"{tenant_id}__{building_id}__{model_type}"


def register_model_version(
    run_id: str,
    artifact_path: str,
    tenant_id: UUID,
    building_id: UUID,
    model_type: str,
    artifact_uri: str | None = None,
) -> str:
    """Register a logged run's model artifact as a new version.

    artifact_uri: pass mlflow.get_artifact_uri(artifact_path) from inside
    the caller's active `with mlflow.start_run()` block if available
    (both trainers already compute this) -- falls back to constructing
    `runs:/{run_id}/{artifact_path}` otherwise, which is equivalent.

    Returns the registered version number (as a string, matching MLflow's
    own ModelVersion.version representation).
    """
    client = MlflowClient()
    name = registered_model_name(tenant_id, building_id, model_type)
    source = artifact_uri or f"runs:/{run_id}/{artifact_path}"

    with contextlib.suppress(MlflowException):
        client.create_registered_model(name)  # already exists from the 2nd training run onward

    version = client.create_model_version(name=name, source=source, run_id=run_id)
    logger.info(
        "register_model_version: registered %s version=%s (run_id=%s)",
        name,
        version.version,
        run_id,
    )
    return str(version.version)
