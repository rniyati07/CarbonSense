from __future__ import annotations

from pydantic_settings import BaseSettings


class KafkaSettings(BaseSettings):
    model_config = {"env_prefix": "KAFKA_"}

    bootstrap_servers: str = "localhost:9092"
    topic_data_arrived: str = "building.data.arrived"
