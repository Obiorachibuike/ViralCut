"""Smart reframing: landscape source -> vertical (or any target aspect) output.

The crop centre is keyframed, so the active speaker stays framed instead of the
crop sitting in the middle of a two-shot for the whole clip. Keyframes are
compiled into an FFmpeg `crop` filter whose x/y are expressions of `t`, which
gives smooth piecewise-linear motion without re-encoding per keyframe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from app.errors import ValidationError

ASPECTS: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "16:9": (1920, 1080),
    "4:5": (1080, 1350),
}


class ReframeMode(StrEnum):
    AUTO = "AUTO"
    CENTER = "CENTER"
    SPEAKER_TRACK = "SPEAKER_TRACK"
    SPLIT_SCREEN = "SPLIT_SCREEN"


@dataclass(slots=True)
class Keyframe:
    """Normalised crop box (0..1 of the source frame) at a point in time."""

    t_ms: int
    x: float
    y: float
    w: float
    h: float

    def clamped(self) -> "Keyframe":
        w = min(1.0, max(0.05, self.w))
        h = min(1.0, max(0.05, self.h))
        return Keyframe(
            t_ms=max(0, self.t_ms),
            x=min(1.0 - w, max(0.0, self.x)),
            y=min(1.0 - h, max(0.0, self.y)),
            w=w,
            h=h,
        )


@dataclass(slots=True)
class ReframePlan:
    mode: ReframeMode
    crop_width: int
    crop_height: int
    out_width: int
    out_height: int
    keyframes: list[Keyframe] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def is_animated(self) -> bool:
        return len(self.keyframes) > 1


def target_size(
    aspect: str,
    *,
    max_short_side: int | None = None,
    max_height: int | None = None,
) -> tuple[int, int]:
    """Resolve an aspect ratio to pixel dimensions.

    Plan limits are expressed as a resolution tier ("720p", "1080p"). For
    vertical video that means 720x1280 / 1080x1920 — the tier caps the *short*
    side of the frame, which is the industry convention and the one creators
    expect. `max_height` is still honoured for callers that really mean height.
    """
    if aspect not in ASPECTS:
        raise ValidationError(f"Unsupported aspect ratio: {aspect}. Use one of {sorted(ASPECTS)}.")
    width, height = ASPECTS[aspect]

    if max_short_side:
        short = min(width, height)
        if short > max_short_side:
            scale = max_short_side / short
            width, height = int(width * scale) // 2 * 2, int(height * scale) // 2 * 2
    if max_height and height > max_height:
        scale = max_height / height
        width, height = int(width * scale) // 2 * 2, int(height * scale) // 2 * 2
    return width, height


def crop_box_for_aspect(src_w: int, src_h: int, out_w: int, out_h: int) -> tuple[int, int]:
    """Largest crop of the source that already matches the target aspect."""
    if src_w <= 0 or src_h <= 0:
        raise ValidationError("Source dimensions are invalid.")
    target = out_w / out_h
    source = src_w / src_h
    if source > target:
        # Source is wider: crop the sides.
        crop_w = int(round(src_h * target))
        crop_h = src_h
    else:
        crop_w = src_w
        crop_h = int(round(src_w / target))
    return min(crop_w, src_w) // 2 * 2, min(crop_h, src_h) // 2 * 2


def plan_reframe(
    *,
    src_w: int,
    src_h: int,
    aspect: str = "9:16",
    mode: ReframeMode | str = ReframeMode.AUTO,
    boxes: list[Keyframe] | None = None,
    max_short_side: int | None = None,
    max_height: int | None = None,
) -> ReframePlan:
    mode = ReframeMode(mode)
    out_w, out_h = target_size(aspect, max_short_side=max_short_side, max_height=max_height)
    crop_w, crop_h = crop_box_for_aspect(src_w, src_h, out_w, out_h)
    notes: list[str] = []

    if mode is ReframeMode.AUTO:
        mode = ReframeMode.SPEAKER_TRACK if boxes else ReframeMode.CENTER
        notes.append(f"auto selected {mode.value}")

    keyframes: list[Keyframe] = []
    if mode is ReframeMode.SPEAKER_TRACK and boxes:
        # Convert detected face boxes into crop boxes of the fixed crop size,
        # centred on the face horizontally.
        for box in boxes:
            box = box.clamped()
            centre_x = box.x + box.w / 2
            crop_x = centre_x - (crop_w / src_w) / 2
            keyframes.append(
                Keyframe(
                    t_ms=box.t_ms,
                    x=crop_x,
                    y=box.y,
                    w=crop_w / src_w,
                    h=crop_h / src_h,
                ).clamped()
            )
        keyframes.sort(key=lambda k: k.t_ms)
    elif mode is ReframeMode.CENTER:
        keyframes = [
            Keyframe(
                t_ms=0,
                x=(src_w - crop_w) / 2 / src_w,
                y=(src_h - crop_h) / 2 / src_h,
                w=crop_w / src_w,
                h=crop_h / src_h,
            )
        ]

    return ReframePlan(
        mode=mode,
        crop_width=crop_w,
        crop_height=crop_h,
        out_width=out_w,
        out_height=out_h,
        keyframes=keyframes,
        notes=notes,
    )


def crop_filter(plan: ReframePlan, src_w: int, src_h: int) -> str:
    """Build the `crop` filter. Animated plans emit x as an expression of `t`."""
    if not plan.is_animated:
        kf = plan.keyframes[0] if plan.keyframes else Keyframe(0, 0.5, 0.5, 1, 1)
        x = int(round(kf.x * src_w)) // 2 * 2
        y = int(round(kf.y * src_h)) // 2 * 2
        return f"crop={plan.crop_width}:{plan.crop_height}:{x}:{y}"

    x_expr = _piecewise_expression(
        [(kf.t_ms / 1000, min(1.0, max(0.0, kf.x * src_w))) for kf in plan.keyframes]
    )
    y_expr = _piecewise_expression(
        [(kf.t_ms / 1000, min(1.0, max(0.0, kf.y * src_h))) for kf in plan.keyframes]
    )
    return f"crop={plan.crop_width}:{plan.crop_height}:'{x_expr}':'{y_expr}'"


def _piecewise_expression(points: list[tuple[float, float]]) -> str:
    """Piecewise-linear interpolation as a nested FFmpeg expression.

    FFmpeg expressions have no loops, so keyframes are folded right-to-left with
    `if(lt(t,T), A, B)` — linear between keyframes, clamped outside them.
    """
    if not points:
        return "0"
    if len(points) == 1:
        return f"{points[0][1]:.2f}"

    expr = f"{points[-1][1]:.2f}"
    for (t0, v0), (t1, v1) in zip(reversed(points[:-1]), reversed(points[1:])):
        span = max(0.001, t1 - t0)
        interpolated = f"({v0:.2f}+({v1:.2f}-{v0:.2f})*(t-{t0:.3f})/{span:.3f})"
        expr = f"if(lt(t\\,{t0:.3f})\\,{v0:.2f}\\,if(lt(t\\,{t1:.3f})\\,{interpolated}\\,{expr}))"
    return expr


def scale_pad_filter(plan: ReframePlan) -> str:
    """Scale the crop to the output canvas, letterboxing if the aspect is off."""
    return (
        f"scale={plan.out_width}:{plan.out_height}:"
        f"force_original_aspect_ratio=decrease,"
        f"pad={plan.out_width}:{plan.out_height}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1"
    )


def split_screen_filter(src_w: int, src_h: int, plan: ReframePlan) -> str:
    """Two-up framing for interviews: each speaker gets half the vertical frame."""
    half = plan.out_height // 2
    box_w = min(src_w, int(src_h * (plan.out_width / half)))
    return (
        f"crop={box_w}:{src_h}:(iw-{box_w})/2:0,"
        f"split=2[top][bottom];"
        f"[top]scale={plan.out_width}:{half}:force_original_aspect_ratio=decrease,"
        f"pad={plan.out_width}:{half}:(ow-iw)/2:(oh-ih)/2[t];"
        f"[bottom]scale={plan.out_width}:{half}:force_original_aspect_ratio=decrease,"
        f"pad={plan.out_width}:{half}:(ow-iw)/2:(oh-ih)/2[b];"
        f"[t][b]vstack=inputs=2,setsar=1"
    )


def plan_to_dict(plan: ReframePlan) -> dict[str, Any]:
    return {
        "mode": plan.mode.value,
        "cropWidth": plan.crop_width,
        "cropHeight": plan.crop_height,
        "outWidth": plan.out_width,
        "outHeight": plan.out_height,
        "animated": plan.is_animated,
        "notes": plan.notes,
        "keyframes": [
            {"tMs": k.t_ms, "x": round(k.x, 4), "y": round(k.y, 4), "w": round(k.w, 4), "h": round(k.h, 4)}
            for k in plan.keyframes
        ],
    }
