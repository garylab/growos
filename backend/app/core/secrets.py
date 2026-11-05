"""Encryption of provider credentials at rest.

A Fernet key is derived from APP_SECRET_KEY with PBKDF2. Credentials are stored as an encrypted JSON blob
and only decrypted in memory when an adapter needs them. API responses never include decrypted values,
only a masked preview (e.g. "sk-...q8Fz").
"""
from __future__ import annotations

import base64
import hashlib
import json
from functools import lru_cache
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    secret = get_settings().app_secret_key.encode()
    key = hashlib.pbkdf2_hmac("sha256", secret, b"growos-credentials-v1", 200_000, dklen=32)
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_credentials(data: dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps(data, separators=(",", ":")).encode()).decode()


def decrypt_credentials(blob: str | None) -> dict[str, Any]:
    if not blob:
        return {}
    try:
        return json.loads(_fernet().decrypt(blob.encode()).decode())
    except InvalidToken as exc:  # key rotated or data corrupted
        raise ValueError("Stored credentials cannot be decrypted with the current APP_SECRET_KEY") from exc


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:3]}…{value[-4:]}"
