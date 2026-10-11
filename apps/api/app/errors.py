"""Error taxonomy.

Users get a short, actionable message; the full detail goes to server logs only.
Raw stack traces are never serialised into an API response.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("viralcut.errors")


class ViralCutError(Exception):
    """Base class. `code` is stable and machine-readable, `message` is safe to show."""

    code = "internal_error"
    status_code = 500

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
        log_detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details or {}
        self.log_detail = log_detail or message

    def to_response(self, error_id: str) -> dict[str, Any]:
        return {
            "error": {
                "id": error_id,
                "code": self.code,
                "message": self.message,
                **({"details": self.details} if self.details else {}),
            }
        }


class ValidationError(ViralCutError):
    code = "validation_error"
    status_code = 422


class NotFoundError(ViralCutError):
    code = "not_found"
    status_code = 404


class UnauthorizedError(ViralCutError):
    code = "unauthorized"
    status_code = 401


class SourceNotPermittedError(ViralCutError):
    """The URL is private, DRM-protected, paywalled or otherwise off-limits."""

    code = "source_not_permitted"
    status_code = 422


class SourceUnavailableError(ViralCutError):
    code = "source_unavailable"
    status_code = 422


class ProviderNotSupportedError(ViralCutError):
    code = "provider_not_supported"
    status_code = 422


class MediaError(ViralCutError):
    code = "media_processing_failed"
    status_code = 500


class TranscriptionError(ViralCutError):
    code = "transcription_failed"
    status_code = 500


class AnalysisError(ViralCutError):
    code = "analysis_failed"
    status_code = 500


class StorageError(ViralCutError):
    code = "storage_failed"
    status_code = 500


class QuotaExceededError(ViralCutError):
    code = "quota_exceeded"
    status_code = 402


class DependencyUnavailableError(ViralCutError):
    """An optional accelerator (whisper/pyannote/LongCat) is not installed."""

    code = "dependency_unavailable"
    status_code = 503


async def viralcut_exception_handler(request: Request, exc: ViralCutError) -> JSONResponse:
    error_id = uuid.uuid4().hex[:12]
    level = logging.WARNING if exc.status_code < 500 else logging.ERROR
    logger.log(
        level,
        "[%s] %s %s -> %s: %s",
        error_id,
        request.method,
        request.url.path,
        exc.code,
        exc.log_detail,
        exc_info=exc.status_code >= 500,
    )
    return JSONResponse(status_code=exc.status_code, content=exc.to_response(error_id))


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    error_id = uuid.uuid4().hex[:12]
    logger.exception("[%s] unhandled error on %s %s", error_id, request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "id": error_id,
                "code": "internal_error",
                "message": "Something went wrong on our side. The details have been logged.",
            }
        },
    )
