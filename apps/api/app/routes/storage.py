"""Signed-URL access to stored media.

The publisher runs in Node and never holds storage credentials, so it asks the
engine for a short-lived URL instead. Works identically for the local backend
(which signs with an HMAC) and R2 (which issues a real presigned URL).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.deps import verify_worker_token
from app.errors import NotFoundError, ValidationError
from services.storage import create_storage

router = APIRouter(prefix="/v1", tags=["storage"], dependencies=[Depends(verify_worker_token)])


@router.get("/storage/url")
async def signed_url(
    key: str = Query(min_length=1, max_length=1024),
    expires_in: int = Query(default=900, ge=60, le=86_400),
) -> dict:
    if key.startswith("/") or ".." in key.split("/"):
        raise ValidationError("Invalid storage key.")

    storage = create_storage()
    if not storage.exists(key):
        raise NotFoundError("That object does not exist in storage.")

    return {
        "key": key,
        "url": storage.signed_url(key, expires_in=expires_in),
        "expiresIn": expires_in,
        "sizeBytes": storage.size(key),
    }
