from __future__ import annotations

from pydantic_settings import BaseSettings


class AuthSettings(BaseSettings):
    """TRD v2.0 §7.2: OAuth2 client-credentials + short-lived JWTs, every
    token carrying a tenant_id claim. jwt_secret has no safe default in
    production -- the "changeme" value is a local-dev convenience only,
    matching DatabaseSettings' own "changeme" password default.
    """

    model_config = {"env_prefix": "AUTH_"}

    # 32+ bytes to clear HS256's RFC 7518 §3.2 minimum-key-length recommendation
    # even as a placeholder -- avoids InsecureKeyLengthWarning noise in every
    # local run/test while still being obviously not a real production secret.
    jwt_secret: str = "changeme-dev-only-secret-please-override-me"  # noqa: S105
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 900

    rate_limit_freemium_per_minute: int = 60
    rate_limit_paid_sme_per_minute: int = 300
    rate_limit_enterprise_per_minute: int = 1200
    rate_limit_integrator_per_minute: int = 600
