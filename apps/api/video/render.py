"""Clip rendering: cut -> reframe -> captions -> music -> watermark -> encode.

Everything here is real FFmpeg work. Nothing is stubbed: if a step cannot run,
the render fails with an actionable error rather than producing a bad file.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.config import get_settings
from app.errors import MediaError
from services.media import MediaProbe
from video.captions import CaptionLine, CaptionStyle, to_ass
from video.ffmpeg import escape_filter_path, run_ffmpeg
from video.reframe import (
    Keyframe,
    ReframeMode,
    ReframePlan,
    crop_filter,
    plan_reframe,
    scale_pad_filter,
    split_screen_filter,
)

logger = logging.getLogger("viralcut.video.render")


@dataclass(slots=True)
class RenderRequest:
    source_path: str
    output_path: str
    start_ms: int
    end_ms: int
    src_width: int
    src_height: int
    aspect: str = "9:16"
    reframe_mode: str = "AUTO"
    keyframes: list[dict[str, Any]] = field(default_factory=list)
    caption_lines: list[CaptionLine] = field(default_factory=list)
    caption_style: CaptionStyle = CaptionStyle.CREATOR
    caption_overrides: dict[str, Any] = field(default_factory=dict)
    muted: bool = False
    volume: float = 1.0
    music_path: str | None = None
    music_volume: float = 0.18
    watermark_text: str | None = None
    watermark_path: str | None = None
    #: Resolution tier cap. 1080 on a 9:16 clip means 1080x1920, matching how
    #: creators read "1080p". Use `max_height` to cap the literal height.
    max_short_side: int | None = None
    max_height: int | None = None
    fps: int = 30
    crf: int = 20
    preset: str = "medium"
    audio_bitrate: str = "192k"


@dataclass(slots=True)
class RenderResult:
    output_path: str
    duration_ms: int
    width: int
    height: int
    size_bytes: int
    plan: dict[str, Any]
    captions_burned: bool
    warnings: list[str] = field(default_factory=list)


def build_filtergraph(
    request: RenderRequest,
    plan: ReframePlan,
    ass_path: Path | None,
    *,
    watermark_image_index: int | None = None,
) -> tuple[str, bool]:
    """Compose the video filter chain.

    Returns (filtergraph, is_complex). `is_complex` is True when an image
    watermark forces a multi-input `-filter_complex` graph instead of `-vf`.
    """
    chain: list[str] = []

    if plan.mode is ReframeMode.SPLIT_SCREEN:
        chain.append(split_screen_filter(request.src_width, request.src_height, plan))
    else:
        chain.append(crop_filter(plan, request.src_width, request.src_height))
        chain.append(scale_pad_filter(plan))

    if ass_path is not None:
        # ASS is applied after the crop so caption geometry matches the output canvas.
        chain.append(f"ass='{escape_filter_path(str(ass_path))}'")

    if watermark_image_index is not None:
        pad = max(16, plan.out_width // 40)
        graph = (
            ",".join(chain)
            + f"[vbase];[{watermark_image_index}:v]scale={plan.out_width // 5}:-2[wm];"
            + f"[vbase][wm]overlay=W-w-{pad}:{pad}[vout]"
        )
        return graph, True

    chain.append(f"fps={request.fps}")
    return ",".join(chain), False




def render_clip(
    request: RenderRequest,
    *,
    probe: MediaProbe | None = None,
    on_progress: Callable[[int], None] | None = None,
    timeout: int | None = None,
) -> RenderResult:
    probe = probe or MediaProbe()
    settings = get_settings()
    timeout = timeout or settings.transcode_timeout_seconds

    source = Path(request.source_path)
    if not source.exists():
        raise MediaError("The source video is missing; re-ingest the video and try again.")
    if request.end_ms <= request.start_ms:
        raise MediaError("The clip range is empty.")

    warnings: list[str] = []
    boxes = [
        Keyframe(t_ms=int(k["tMs"]), x=float(k["x"]), y=float(k["y"]),
                 w=float(k["w"]), h=float(k["h"]))
        for k in request.keyframes
    ]
    plan = plan_reframe(
        src_w=request.src_width,
        src_h=request.src_height,
        aspect=request.aspect,
        mode=request.reframe_mode,
        boxes=boxes or None,
        max_short_side=request.max_short_side,
        max_height=request.max_height,
    )

    output = Path(request.output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    duration_ms = request.end_ms - request.start_ms

    # ---------------------------------------------------------------- inputs
    # Input order is fixed so filtergraph indices stay predictable:
    #   0 = source video, 1 = watermark image (optional), last = music (optional)
    argv: list[str] = [
        probe.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        # Fast seek to the cut point; -to bounds the decode window.
        "-ss", f"{request.start_ms / 1000:.3f}",
        "-to", f"{request.end_ms / 1000:.3f}",
        "-i", str(source),
    ]
    next_input = 1

    watermark_index: int | None = None
    if request.watermark_path:
        watermark_file = Path(request.watermark_path)
        if watermark_file.exists():
            argv += ["-i", str(watermark_file)]
            watermark_index = next_input
            next_input += 1
        else:
            warnings.append("watermark image not found; rendering without it")

    music_index: int | None = None
    if request.music_path and not request.muted:
        music_file = Path(request.music_path)
        if music_file.exists():
            argv += ["-stream_loop", "-1", "-i", str(music_file)]
            music_index = next_input
            next_input += 1
        else:
            warnings.append("background music file not found; rendering without it")

    # -------------------------------------------------------------- captions
    # Captions are written to an ASCII path: filtergraph escaping of arbitrary
    # unicode paths is a long-standing source of FFmpeg failures.
    ass_path: Path | None = None
    if request.caption_lines or request.watermark_text:
        if not probe.supports_filter("ass"):
            raise MediaError(
                "This FFmpeg build has no libass support, so captions cannot be burned in. "
                "Install a full FFmpeg build (apt install ffmpeg, or the static GPL build)."
            )
        ass_path = output.with_suffix(".ass")
        ass_path.write_text(
            to_ass(
                request.caption_lines,
                style=request.caption_style,
                width=plan.out_width,
                height=plan.out_height,
                overrides=request.caption_overrides,
                watermark_text=request.watermark_text,
                total_duration_ms=duration_ms,
            ),
            encoding="utf-8",
        )

    # ------------------------------------------------------------- filtergraph
    video_filter, video_is_complex = build_filtergraph(
        request, plan, ass_path, watermark_image_index=watermark_index
    )

    volume = max(0.0, min(3.0, request.volume))
    audio_is_complex = music_index is not None
    needs_complex = video_is_complex or audio_is_complex

    if needs_complex:
        parts: list[str] = []
        if video_is_complex:
            parts.append(video_filter)
        else:
            parts.append(f"[0:v]{video_filter}[vout]")
        if audio_is_complex:
            parts.append(
                f"[0:a]volume={volume:.3f}[voice];"
                f"[{music_index}:a]volume={max(0.0, min(1.0, request.music_volume)):.3f}[music];"
                f"[voice][music]amix=inputs=2:duration=first:dropout_transition=2[aout]"
            )
        argv += ["-filter_complex", ";".join(parts), "-map", "[vout]"]
        if audio_is_complex:
            argv += ["-map", "[aout]"]
        elif not request.muted:
            argv += ["-map", "0:a?"]
    else:
        argv += ["-vf", video_filter, "-map", "0:v"]
        if request.muted:
            pass
        else:
            argv += ["-map", "0:a?"]
            if volume != 1.0:
                argv += ["-af", f"volume={volume:.3f}"]

    if request.muted:
        argv += ["-an"]

    argv += [
        "-c:v", "libx264", "-preset", request.preset, "-crf", str(request.crf),
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.2",
    ]
    if not request.muted:
        argv += ["-c:a", "aac", "-b:a", request.audio_bitrate, "-ar", "48000"]
    argv += ["-movflags", "+faststart", "-t", f"{duration_ms / 1000:.3f}", str(output)]

    run_ffmpeg(
        argv,
        timeout=timeout,
        progress_total_ms=duration_ms,
        on_progress=on_progress,
        label="render_clip",
    )

    if not output.exists() or output.stat().st_size == 0:
        raise MediaError("Rendering finished but produced no file.")

    info = probe.inspect(output)
    return RenderResult(
        output_path=str(output),
        duration_ms=info.duration_ms or duration_ms,
        width=info.width or plan.out_width,
        height=info.height or plan.out_height,
        size_bytes=output.stat().st_size,
        plan=_plan_dict(plan, watermark_index is not None),
        captions_burned=ass_path is not None,
        warnings=warnings,
    )


def _plan_dict(plan: ReframePlan, watermark_input_added: bool) -> dict[str, Any]:
    from video.reframe import plan_to_dict

    data = plan_to_dict(plan)
    data["watermarkImageUsed"] = watermark_input_added
    return data


def cut_source_clip(
    source_path: str,
    dest_path: str,
    *,
    start_ms: int,
    end_ms: int,
    probe: MediaProbe | None = None,
    reencode: bool = True,
    timeout: int = 600,
) -> Path:
    """Extract a timestamp range. Used by `POST /clips` before any styling."""
    probe = probe or MediaProbe()
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    duration_ms = max(1, end_ms - start_ms)

    argv = [
        probe.ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-ss", f"{start_ms / 1000:.3f}",
        "-to", f"{end_ms / 1000:.3f}",
        "-i", source_path,
    ]
    if reencode:
        argv += [
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
        ]
    else:
        argv += ["-c", "copy", "-avoid_negative_ts", "make_zero"]
    argv += ["-t", f"{duration_ms / 1000:.3f}", str(dest)]

    run_ffmpeg(argv, timeout=timeout, progress_total_ms=duration_ms, label="cut_source_clip")
    if not dest.exists() or dest.stat().st_size == 0:
        raise MediaError("Cutting the clip produced no file.")
    return dest
