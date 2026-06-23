FROM python:3.13-slim AS base

WORKDIR /app

RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash appuser

COPY pyproject.toml ./
RUN pip install --no-cache-dir . && rm -rf /root/.cache

COPY apps/ apps/
COPY orchestration/ orchestration/
COPY shared/ shared/
COPY services/ services/
COPY models/ models/

RUN chown -R appuser:appuser /app
USER appuser

ENTRYPOINT ["python", "-m", "apps.worker.main"]