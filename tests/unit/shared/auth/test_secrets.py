from __future__ import annotations

import pytest

from shared.auth.secrets import generate_client_secret, hash_client_secret, verify_client_secret


@pytest.mark.unit
class TestClientSecretHashing:
    def test_verify_succeeds_for_matching_secret(self) -> None:
        secret = generate_client_secret()
        stored_hash = hash_client_secret(secret)
        assert verify_client_secret(secret, stored_hash) is True

    def test_verify_fails_for_wrong_secret(self) -> None:
        stored_hash = hash_client_secret(generate_client_secret())
        assert verify_client_secret("totally-wrong-secret", stored_hash) is False

    def test_verify_fails_for_malformed_stored_hash(self) -> None:
        assert verify_client_secret("some-secret", "not-a-valid-hash-format") is False

    def test_two_secrets_generated_are_not_equal(self) -> None:
        assert generate_client_secret() != generate_client_secret()

    def test_hashing_the_same_secret_twice_yields_different_hashes(self) -> None:
        """Random per-secret salt -- two hashes of the same plaintext must
        differ, but both must still verify correctly."""
        secret = generate_client_secret()
        hash_one = hash_client_secret(secret)
        hash_two = hash_client_secret(secret)
        assert hash_one != hash_two
        assert verify_client_secret(secret, hash_one)
        assert verify_client_secret(secret, hash_two)
