# Root conftest for CarbonSense test suite.
# Shared fixtures (e.g., synthetic tenant, golden COMBED fixture) go here.

# ------------------------------------------------------------------ #
# Lightweight stub for confluent_kafka, used only when the real
# C-extension package (requires native librdkafka) is not installed.
#
# Unit tests that test ingestion logic (not Kafka transport) should not
# require the native extension to be installed. If the real package IS
# available (e.g. installed via `pip install -e ".[dev]"` in CI), it is
# used as-is — this stub never shadows a working installation, and it
# covers the full import surface (Consumer, Producer, KafkaError,
# Message) so it works as a drop-in for both producer- and
# consumer-side unit tests, which patch the class directly rather than
# relying on stub behavior. Any test that actually calls the real Kafka
# API should be tagged @pytest.mark.integration and skipped without a
# broker.
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

    class _Message:  # noqa: N801
        def value(self) -> bytes | None:
            return None

        def error(self) -> _KafkaError | None:
            return None

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

    class _Consumer:  # noqa: N801
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def subscribe(self, *args: object, **kwargs: object) -> None:
            raise RuntimeError(
                "confluent_kafka.Consumer.subscribe() called in unit test context. "
                "Use @pytest.mark.integration and ensure a Kafka broker is available."
            )

        def poll(self, timeout: float = 0) -> _Message | None:
            return None

        def close(self) -> None:
            pass

    stub.KafkaError = _KafkaError
    stub.Message = _Message
    stub.Producer = _Producer
    stub.Consumer = _Consumer
    return stub


try:
    import confluent_kafka as _confluent_kafka  # noqa: F401
except ImportError:
    sys.modules["confluent_kafka"] = _make_confluent_kafka_stub()
