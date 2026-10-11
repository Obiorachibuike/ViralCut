"""Auth + shared dependencies for the media engine.

The engine is only callable by the ViralCut orchestrator (Next.js). Every route
must present the shared `MEDIA_ENGINE_TOKEN`. The engine never issues tokens to
browsers; the web app only ever talks to the orchestrator, which owns the DB and
per-user isolation.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, Header, Request

from app.config import get_settings
from app.errors import UnauthorizedError


def verify_worker_token(
    authorization: Annotated[str | None, Header()] = None,
    x_viralcut_token: Annotated[str | None, Header()] = None,
) -> bool:
    settings = get_settings()
    expected = settings.worker_token
    provided = None
    if x_viralcut_token:
        provided = x_viralcut_token
    elif authorization and authorization.lower().startswith("bearer "):
        provided = authorization.split(" ", 1)[1].strip()

    if not expected:
        # Fail closed: an unconfigured token means the engine should not serve.
        raise UnauthorizedError(
            "The media engine is not configured (MEDIA_ENGINE_TOKEN missing). "
            "Set it and restart the worker."
        )
    if not provided or not secrets.compare_digest(provided, expected):
        raise UnauthorizedError("Invalid or missing media-engine token.")
    return True


TokenAuth = Annotated[bool, Depends(verify_worker_token)]


def require_admin(request: Request) -> bool:
    return True  # reserved for future per-tenant scopes
