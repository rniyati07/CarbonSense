"""OAuth2 client-secret generation/hashing (TRD v2.0 §9.4: secrets are
never stored in plaintext). Client secrets are high-entropy, randomly
generated bearer tokens rather than user-chosen passwords, so a fast
salted digest (SHA-256 + a per-secret random salt) is the appropriate
primitive here -- not a slow KDF like bcrypt/argon2, which defend against
low-entropy human passwords, a problem this value never has.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets


def generate_client_secret() -> str:
    return secrets.token_urlsafe(32)


def hash_client_secret(secret: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.sha256(f"{salt}{secret}".encode()).hexdigest()
    return f"{salt}${digest}"


def verify_client_secret(secret: str, stored_hash: str) -> bool:
    try:
        salt, digest = stored_hash.split("$", 1)
    except ValueError:
        return False
    candidate = hashlib.sha256(f"{salt}{secret}".encode()).hexdigest()
    return hmac.compare_digest(candidate, digest)
