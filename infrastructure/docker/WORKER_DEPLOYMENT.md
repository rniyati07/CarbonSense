# Temporal Worker Deployment

## Local Development

```bash
cd infrastructure/docker
docker compose up -d
```

This starts:

| Service | Port | Purpose |
|---------|------|---------|
| `temporal` | 7233 | Temporal server (SQLite-backed, auto-setup) |
| `temporal-ui` | 8080 | Temporal Web UI — schedule visibility, workflow replay, history |
| `kafka` | 9092 | Kafka broker (KRaft mode, no ZooKeeper) |
| `worker` | — | CarbonSense Temporal worker |

## Worker Configuration

All configuration is via environment variables (see `shared/config/temporal.py` and `shared/config/kafka.py`):

| Variable | Default | Description |
|----------|---------|-------------|
| `TEMPORAL_HOST` | `localhost:7233` | Temporal server address |
| `TEMPORAL_NAMESPACE` | `carbonsense` | Temporal namespace |
| `TEMPORAL_TASK_QUEUE` | `analysis-pipeline` | Task queue for all workflows |
| `TEMPORAL_TLS_CLIENT_CERT_PATH` | — | mTLS cert for Temporal Cloud |
| `TEMPORAL_TLS_CLIENT_KEY_PATH` | — | mTLS key for Temporal Cloud |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Kafka broker address |

## Building the Worker Image

```bash
# From the repository root
docker build -f infrastructure/docker/worker.Dockerfile -t carbonsense-worker .
```

## Production (Temporal Cloud)

For Temporal Cloud, set TLS environment variables:

```bash
docker run \
  -e TEMPORAL_HOST=<namespace>.tmprl.cloud:7233 \
  -e TEMPORAL_NAMESPACE=<namespace> \
  -e TEMPORAL_TLS_CLIENT_CERT_PATH=/certs/client.pem \
  -e TEMPORAL_TLS_CLIENT_KEY_PATH=/certs/client.key \
  -e KAFKA_BOOTSTRAP_SERVERS=<kafka-broker>:9092 \
  -v /path/to/certs:/certs:ro \
  carbonsense-worker
```

## Running Integration Tests

```bash
# Start infrastructure only (no worker)
cd infrastructure/docker
docker compose up -d temporal kafka

# Run integration tests
pytest -m integration tests/
```