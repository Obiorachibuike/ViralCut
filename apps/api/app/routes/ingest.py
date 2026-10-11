from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter

from fastapi import Depends
from app.deps import verify_worker_token
from app.errors import SourceNotPermittedError, SourceUnavailableError
from app.schemas import DownloadRequest, DownloadResponse, ResolveUrlRequest, ResolveUrlResponse
from providers.registry import get_registry as provider_registry
from services.storage import create_storage, key_for

logger = logging.getLogger("viralcut.routes.ingest")
router = APIRouter(prefix="/v1/ingest", tags=["ingest"], dependencies=[Depends(verify_worker_token)])


@router.post("/resolve-url", response_model=ResolveUrlResponse)
async def resolve_url(body: ResolveUrlRequest) -> ResolveUrlResponse:
    registry = provider_registry()
    resolution = registry.resolve(body.url)
    return ResolveUrlResponse(
        kind=resolution.kind.value,
        provider=resolution.provider,
        permitted=resolution.permitted,
        externalId=resolution.external_id,
        title=resolution.title,
        reason=resolution.reason,
        isPrivate=resolution.is_private,
        requiresLogin=resolution.requires_login,
        drmProtected=resolution.drm_protected,
        isLive=resolution.is_live,
        providers=registry.describe(),
    )


@router.post("/download", response_model=DownloadResponse)
async def download(body: DownloadRequest) -> DownloadResponse:
    registry = provider_registry()
    resolution = registry.resolve(body.url)
    if not resolution.permitted:
        raise SourceNotPermittedError(
            resolution.reason or "That source cannot be processed by ViralCut.",
            details={"provider": resolution.provider},
        )

    provider = registry.for_url(body.url)
    with tempfile.TemporaryDirectory(prefix="viralcut-dl-") as tmp:
        dest = str(Path(tmp) / "media.mp4")
        try:
            provider.fetch(resolution, dest)
        except PermissionError as err:
            raise SourceNotPermittedError(str(err)) from err
        except Exception as err:
            logger.exception("download failed for %s", body.url)
            raise SourceUnavailableError(
                "Download failed. The video may be unavailable or the platform rate-limited us. Retry.",
                log_detail=f"{err.__class__.__name__}: {err}",
            ) from err

        size = Path(dest).stat().st_size
        key = key_for("sources", body.run_id, "media.mp4")
        create_storage().put_file(key, dest, content_type="video/mp4")

    return DownloadResponse(
        storageKey=key,
        sizeBytes=size,
        kind=resolution.kind.value,
        provider=resolution.provider,
    )
