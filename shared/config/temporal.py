from __future__ import annotations

from pydantic_settings import BaseSettings


class TemporalSettings(BaseSettings):
    model_config = {"env_prefix": "TEMPORAL_"}

    host: str = "localhost:7233"
    namespace: str = "carbonsense"
    task_queue: str = "analysis-pipeline"
    tls_client_cert_path: str | None = None
    tls_client_key_path: str | None = None
