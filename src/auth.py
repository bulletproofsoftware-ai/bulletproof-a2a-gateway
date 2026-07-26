"""Simple API key authentication via X-API-Key header."""

import os
from typing import Set

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def _load_api_keys() -> Set[str]:
    """Load valid API keys from the API_KEYS environment variable (comma-separated)."""
    raw = os.environ.get("API_KEYS", "")
    if not raw:
        return set()
    return {k.strip() for k in raw.split(",") if k.strip()}


def _load_elevated_api_keys() -> Set[str]:
    """Keys permitted to invoke elevated-trust agents (comma-separated).

    Trust MUST be derived from the presented credential, never from a header
    the caller controls. ELEVATED_API_KEYS is a subset of API_KEYS; a key not
    listed here is standard trust no matter what it claims.
    """
    raw = os.environ.get("ELEVATED_API_KEYS", "")
    if not raw:
        return set()
    return {k.strip() for k in raw.split(",") if k.strip()}


def is_elevated_key(api_key: str) -> bool:
    """True if this validated key is authorised for elevated-trust agents."""
    return api_key in _load_elevated_api_keys()


async def require_api_key(
    api_key: str | None = Security(_api_key_header),
) -> str:
    """FastAPI dependency that validates the X-API-Key header.

    Returns the validated key on success; raises 401 or 403 otherwise.
    """
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )

    valid_keys = _load_api_keys()

    if not valid_keys:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No API keys configured on server",
        )

    if api_key not in valid_keys:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )

    return api_key
