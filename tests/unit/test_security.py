"""Unit Tests for Security, Key Hashing, Password & JWT Utilities."""

from datetime import timedelta
import pytest
from api.app.core.security import (
    create_access_token,
    decode_access_token,
    generate_api_key,
    get_password_hash,
    hash_api_key,
    verify_password,
)


def test_password_hashing_and_verification():
    """Verify that bcrypt password hashing and verification are robust."""
    password = "SuperSecretPassword123!"
    hashed = get_password_hash(password)

    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False


def test_jwt_creation_and_decoding():
    """Verify that JWT creation, payload encoding and decoding work correctly."""
    data = {
        "sub": "018f3a21-9980-7c22-bca8-f918903e1e91",
        "email": "admin@analytics.internal",
        "role": "SuperAdmin",
    }
    token = create_access_token(data, expires_delta=timedelta(minutes=15))
    assert isinstance(token, str)

    decoded = decode_access_token(token)
    assert decoded["sub"] == data["sub"]
    assert decoded["email"] == data["email"]
    assert decoded["role"] == "SuperAdmin"
    assert "exp" in decoded


def test_api_key_generation_and_hashing():
    """Verify write key format, non-secret prefix and SHA-256 hash."""
    raw_key, prefix, key_hash = generate_api_key("live")

    # Format verification
    assert raw_key.startswith("apk_live_")
    assert prefix.startswith("apk_live_")
    assert len(prefix) == len("apk_live_") + 8

    # Hash determinism
    assert hash_api_key(raw_key) == key_hash
    assert len(key_hash) == 64  # SHA-256 hex string

    # Test environment separation
    raw_test_key, test_prefix, _ = generate_api_key("test")
    assert raw_test_key.startswith("apk_test_")
    assert test_prefix.startswith("apk_test_")
