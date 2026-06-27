# Root conftest for CarbonSense test suite.
# Shared fixtures (e.g., synthetic tenant, golden COMBED fixture) go here.

# ------------------------------------------------------------------ #
# Lightweight stubs for optional C-extension / external dependencies
# that are not available in all CI environments.
#
# confluent_kafka requires a native C library (librdkafka).  Unit tests
# that test ingestion logic (not Kafka transport) should not require the
# native extension to be installed.  We install a minimal stub here so
# that imports succeed.  Any test that actually calls the real Kafka API
# should be tagged @pytest.mark.integration and skipped without a broker.
# ------------------------------------------------------------------ #
from __future__ import annotations

import sys
import types


def _make_confluent_kafka_stub() -> types.ModuleType:
    """Create a minimal stub module for confluent_kafka."""
    stub = types.ModuleType("confluent_kafka")

    class _KafkaError:  # noqa: N801
        _ALL_BROKERS_DOWN = -187

        def __init__(self, code: int = 0, reason: str = "") -> None:
            self.code = code
            self.reason = reason

    class _Producer:  # noqa: N801
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def produce(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError(
                "confluent_kafka.Producer.produce() called in unit test context. "
                "Use @pytest.mark.integration and ensure a Kafka broker is available."
            )

        def flush(self, timeout: float = 1.0) -> int:
            return 0

        def poll(self, timeout: float = 0) -> int:
            return 0

    stub.KafkaError = _KafkaError
    stub.Producer = _Producer
    return stub


if "confluent_kafka" not in sys.modules:
    sys.modules["confluent_kafka"] = _make_confluent_kafka_stub()
