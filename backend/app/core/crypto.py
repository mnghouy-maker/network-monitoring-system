"""Symmetric encryption for secrets stored at rest (device SSH credentials).

Uses Fernet (AES-128-CBC + HMAC). The key comes from ``BACKUP_ENCRYPTION_KEY``;
if unset it is derived from ``SECRET_KEY`` for development convenience.
"""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet

from app.core.config import settings


@lru_cache
def _fernet() -> Fernet:
    key = settings.BACKUP_ENCRYPTION_KEY
    if not key:
        # Derive a valid 32-byte urlsafe-base64 Fernet key from SECRET_KEY.
        digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        key = base64.urlsafe_b64encode(digest).decode()
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    """Return an encrypted, storable token for ``plaintext``."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(token: str) -> str:
    """Decrypt a token produced by :func:`encrypt_secret`."""
    return _fernet().decrypt(token.encode()).decode()
