from __future__ import annotations

from pydantic_settings import BaseSettings


class LocalModelRegistrySettings(BaseSettings):
    """Configuration for models.serving.local_registry.LocalModelRegistry.

    Defaults to a sqlite-backed local MLflow tracking store, not the plain
    filesystem store -- the installed MLflow version rejects plain
    './mlruns'-style filesystem tracking outright ("filesystem tracking
    backend is in maintenance mode"), and the existing training test suite
    (tests/unit/services/ml_ensemble/conftest.py) already standardized on
    sqlite for exactly this reason.
    """

    model_config = {"env_prefix": "ML_REGISTRY_"}

    tracking_uri: str = "sqlite:///./local_model_registry/mlflow.db"
