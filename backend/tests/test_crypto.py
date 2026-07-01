"""Unit tests for at-rest secret encryption."""

from app.core.crypto import decrypt_secret, encrypt_secret


def test_encrypt_decrypt_roundtrip() -> None:
    token = encrypt_secret("sup3r-s3cret")
    assert token != "sup3r-s3cret"
    assert decrypt_secret(token) == "sup3r-s3cret"


def test_ciphertext_is_nondeterministic() -> None:
    # Fernet embeds a random IV/timestamp, so two encryptions differ but both
    # decrypt to the same plaintext.
    a = encrypt_secret("same")
    b = encrypt_secret("same")
    assert a != b
    assert decrypt_secret(a) == decrypt_secret(b) == "same"
