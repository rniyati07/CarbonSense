from __future__ import annotations

from pydantic_settings import BaseSettings


class KafkaSettings(BaseSettings):
    model_config = {"env_prefix": "KAFKA_"}

    bootstrap_servers: str = "localhost:9092"
    topic_data_arrived: str = "building.data.arrived"
    topic_model_drift_detected: str = "model.drift.detected"
    topic_customer_notification: str = "customer.notification.created"
    topic_retraining_eligible: str = "model.retraining.eligible"
