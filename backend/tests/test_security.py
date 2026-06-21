"""Unit tests for password hashing and JWT handling."""

import pytest

from app.core.security import (
    ACCESS_TOKEN_TYPE,
    REFRESH_TOKEN_TYPE,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("s3cr3t-password")
    assert hashed != "s3cr3t-password"
    assert verify_password("s3cr3t-password", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_access_token_contains_expected_claims() -> None:
    token = create_access_token("user-123", extra_claims={"role": "admin"})
    claims = decode_token(token)
    assert claims is not None
    assert claims["sub"] == "user-123"
    assert claims["type"] == ACCESS_TOKEN_TYPE
    assert claims["role"] == "admin"


def test_refresh_token_type() -> None:
    token = create_refresh_token("user-123")
    claims = decode_token(token)
    assert claims is not None
    assert claims["type"] == REFRESH_TOKEN_TYPE


def test_decode_invalid_token_returns_none() -> None:
    assert decode_token("not-a-real-token") is None


@pytest.mark.parametrize("bad", ["", "a.b", "a.b.c"])
def test_decode_malformed_tokens(bad: str) -> None:
    assert decode_token(bad) is None
