from __future__ import annotations

from fastapi import APIRouter

from ai.analysis import analysis_status
from ai.prompts import available_versions
from app.config import get_settings
from app.schemas import HealthResponse
from services.media import MediaProbe, resolve_ffprobe
from transcription.factory import transcriber_status
from diarization.pyannote import pyannote_available

router = APIRouter(tags=["health"])


@router.get("/v1/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    settings = get_settings()
    probe: MediaProbe | None = None
    try:
        probe = MediaProbe()
    except Exception:
        probe = None

    filters = {}
    if probe is not None:
        filters = {name: probe.supports_filter(name) for name in ("ass", "drawtext", "overlay", "amix")}

    return HealthResponse(
        status="ok" if probe is not None else "degraded",
        service="viralcut-media-engine",
        ffmpeg=probe is not None,
        ffprobe=(resolve_ffprobe(ffmpeg=probe.ffmpeg) is not None) if probe else None,
        filters=filters,
        transcription=transcriber_status(),
        diarization=pyannote_available(),
        ai=analysis_status(),
        longcat=_longcat_status(),
        storage=settings.storage_backend,
        promptVersions=available_versions(),
    )


def _longcat_status() -> dict:
    from ai.longcat import LongCatClient

    return LongCatClient().health()
