"""Anonymous, per-device authentication.

There are no user accounts or passwords. Each installation (a browser's
IndexedDB, or an ESP32's flash) generates a random installation_id once,
registers it against POST /api/devices/register, and receives an opaque
device token back. Every subsequent request authenticates with:

    Authorization: Device <token>

The server never stores the raw token — only an HMAC-SHA256 hash of it,
keyed by DEVICE_SIGNING_SECRET — so a leaked database dump does not hand
out usable tokens.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets

from fastapi import Header, HTTPException, status

from .config import settings
from .database import get_repository
from .models import Device

log = logging.getLogger("smart-glasses.auth")

# Fallback secret so the process can still run without DEVICE_SIGNING_SECRET
# set (demo mode). Generated once per process start — see config.py, which
# already warns loudly that this invalidates tokens across restarts.
_fallback_secret = secrets.token_hex(32)

# Fixed installation_id used for the single shared device when
# DISABLE_DEVICE_AUTH=true (prototyping only).
_SHARED_DEV_INSTALLATION_ID = "prototype-shared-device"


def _signing_key() -> bytes:
    key = settings.device_signing_secret or _fallback_secret
    return key.encode("utf-8")


def generate_device_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hmac.new(_signing_key(), token.encode("utf-8"), hashlib.sha256).hexdigest()


def parse_auth_header(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Device "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Header 'Authorization: Device <token>' wajib disertakan.",
        )
    token = authorization.removeprefix("Device ").strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token perangkat kosong.")
    return token


async def get_current_device(authorization: str | None = Header(default=None)) -> Device:
    """FastAPI dependency: resolves the caller's Device from its token.

    When DISABLE_DEVICE_AUTH=true (prototyping only — see config.py), this
    skips token verification entirely and returns one fixed shared device,
    auto-created on first use. Every client then shares the same
    conversation history; there is no per-device isolation in this mode.
    """
    repo = get_repository()

    if settings.disable_device_auth:
        device = await repo.get_device_by_installation_id(_SHARED_DEV_INSTALLATION_ID)
        if device is None:
            device = await repo.create_device(_SHARED_DEV_INSTALLATION_ID, "Prototype (auth dimatikan)", "")
        await repo.update_device_last_seen(device.id)
        return device

    token = parse_auth_header(authorization)
    device = await repo.get_device_by_token_hash(hash_token(token))
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token perangkat tidak dikenali. Daftarkan ulang lewat POST /api/devices/register.",
        )
    await repo.update_device_last_seen(device.id)
    return device
