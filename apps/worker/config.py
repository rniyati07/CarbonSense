from __future__ import annotations

from pathlib import Path

from temporalio.client import TLSConfig

from shared.config.temporal import TemporalSettings


def build_tls_config(settings: TemporalSettings) -> TLSConfig | bool:
    if settings.tls_client_cert_path and settings.tls_client_key_path:
        return TLSConfig(
            client_cert=Path(settings.tls_client_cert_path).read_bytes(),
            client_private_key=Path(settings.tls_client_key_path).read_bytes(),
        )
    return False
