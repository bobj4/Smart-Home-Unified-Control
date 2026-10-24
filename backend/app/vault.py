"""Encrypts integration credentials before they are stored (SEC: secrets at rest).

The key comes from the SECRETS_KEY environment variable (a Fernet key; make
one with `python -m scripts.make_secrets_key`). There is no fallback key:
without SECRETS_KEY nothing can be saved or read.
"""

import json
import os
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class VaultError(Exception):
    """SECRETS_KEY is missing or invalid, or a stored value cannot be read."""


def _fernet() -> Fernet:
    key = os.environ.get("SECRETS_KEY", "").strip()
    if not key:
        raise VaultError("SECRETS_KEY is not set")
    try:
        return Fernet(key.encode())
    except ValueError:
        raise VaultError("SECRETS_KEY is not a valid key") from None


def encrypt(data: dict[str, Any]) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def decrypt(token: str) -> dict[str, Any]:
    try:
        value = json.loads(_fernet().decrypt(token.encode()))
    except InvalidToken:
        raise VaultError(
            "stored credentials cannot be decrypted with SECRETS_KEY"
        ) from None
    if not isinstance(value, dict):
        raise VaultError("stored credentials are not valid")
    return value
