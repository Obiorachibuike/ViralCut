from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter

from fastapi import Depends
from app.deps import verify_worker_token
from app.schemas import (
    CaptionsRequest,
    CaptionsResponse,
    ReframePlanRequest,
    RenderRequest,
    RenderResponse,
)
from transcription.base import Segment, Transcript
from video.captions import CaptionStyle, build_caption_lines, to_ass, to_srt, to_vtt
from video.reframe import Keyframe, plan_reframe, plan_to_dict
from video.render import RenderRequest as EngineRenderRequest, render_clip
from services.media import MediaProbe
from services.storage import create_storage
from pathlib import Path

logger = logging.getLogger("viralcut.routes.render")
router = APIRouter(prefix="/v1", tags=["render"], dependencies=[Depends(verify_worker_token)])


def _load_source(storage_key: str) -> tuple[Path, MediaProbe]:
    storage = create_storage()
    probe = MediaProbe()
    local = storage.copy_to_local(storage_key, probe_work_dir())
    return local, probe


def probe_work_dir() -> Path:
    from app.config import get_settings

    path = get_settings().work_dir / "render"
    path.mkdir(parents=True, exist_ok=True)
    return path


@router.post("/clips/render", response_model=RenderResponse)
async def render(body: RenderRequest) -> RenderResponse:
    storage = create_storage()
    work = probe_work_dir()

    local = storage.copy_to_local(body.storageKey, work)
    music_local = storage.copy_to_local(body.musicKey, work) if body.musicKey else None
    watermark_local = storage.copy_to_local(body.watermarkKey, work) if body.watermarkKey else None

    # Captions arrive as {index,startMs,endMs,text,words?}.
    segments = []
    for raw in body.captions:
        segments.append(
            Segment(
                index=int(raw.get("index", len(segments))),
                start_ms=int(raw["startMs"]),
                end_ms=int(raw["endMs"]),
                text=str(raw.get("text", "")),
            )
        )
    caption_lines = build_caption_lines(segments, uppercase=True) if body.captions else []

    # Captions are timed against the *clip*, which starts at body.startMs; shift.
    shifted = []
    for line in caption_lines:
        line.start_ms = max(0, line.start_ms - body.startMs)
        line.end_ms = max(0, line.end_ms - body.startMs)
        shifted.append(line)

    request = EngineRenderRequest(
        source_path=str(local),
        output_path=str(work / body.outputKey.split("/")[-1]),
        start_ms=body.startMs,
        end_ms=body.endMs,
        src_width=body.srcWidth,
        src_height=body.srcHeight,
        aspect=body.aspect,
        reframe_mode=body.reframeMode,
        keyframes=[k.model_dump() for k in body.keyframes],
        caption_lines=shifted,
        caption_style=CaptionStyle(body.captionStyle),
        caption_overrides=body.captionOverrides,
        muted=body.muted,
        volume=body.volume,
        music_path=str(music_local) if music_local else None,
        music_volume=body.musicVolume,
        watermark_text=body.watermarkText,
        watermark_path=str(watermark_local) if watermark_local else None,
        max_short_side=body.maxShortSide,
        preset=body.preset,
        crf=body.crf,
    )

    result = await asyncio.get_running_loop().run_in_executor(
        None, lambda: render_clip(request)
    )

    storage.put_file(body.outputKey, result.output_path, content_type="video/mp4")

    return RenderResponse(
        storageKey=body.outputKey,
        sizeBytes=result.size_bytes,
        width=result.width,
        height=result.height,
        durationMs=result.duration_ms,
        captionsBurned=result.captions_burned,
        plan=result.plan,
        warnings=result.warnings,
    )


@router.post("/reframe/plan")
async def reframe_plan(body: ReframePlanRequest) -> dict:
    boxes = [
        Keyframe(t_ms=k.tMs, x=k.x, y=k.y, w=k.w, h=k.h) for k in body.keyframes
    ]
    plan = plan_reframe(
        src_w=body.srcWidth,
        src_h=body.srcHeight,
        aspect=body.aspect,
        mode=body.reframeMode,
        boxes=boxes or None,
        max_short_side=body.maxShortSide,
    )
    return plan_to_dict(plan)


@router.post("/captions/generate", response_model=CaptionsResponse)
async def generate_captions(body: CaptionsRequest) -> CaptionsResponse:
    transcript = Transcript.from_dict(body.transcript)
    lines = build_caption_lines(
        transcript.segments,
        words_per_line=body.wordsPerLine,
        uppercase=body.uppercase,
    )
    return CaptionsResponse(
        lines=[
            {
                "index": l.index,
                "startMs": l.start_ms,
                "endMs": l.end_ms,
                "text": l.text,
                "speaker": l.speaker,
            }
            for l in lines
        ],
        ass=to_ass(lines, style=CaptionStyle(body.style), width=body.width, height=body.height,
                   watermark_text=body.watermarkText),
        srt=to_srt(lines),
        vtt=to_vtt(lines),
    )
