from __future__ import annotations

from pydantic_settings import BaseSettings


class DatabaseSettings(BaseSettings):
    model_config = {"env_prefix": "APP_"}

    database_url: str = "postgresql+asyncpg://carbonsense_app:changeme@localhost:5432/carbonsense"
    pool_size: int = 10
    max_overflow: int = 20
