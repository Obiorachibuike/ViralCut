"""Active-speaker localisation for smart reframing.

Preferred backend is OpenCV's DNN face detector (CPU-friendly, no model
download beyond the bundled caffemodel). When OpenCV is unavailable we return an
empty track and the reframe planner falls back to a centre crop — the clip still
renders correctly, it just is not speaker-tracked.

Diarization tells us *who* is talking; this tells us *where* they are.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from typing import Any

from video.reframe import Keyframe

logger = logging.getLogger("viralcut.video.faces")


def opencv_available() -> bool:
    try:
        import cv2  # noqa: F401

        return True
    except Exception:
        return False


@dataclass(slots=True)
class Detection:
    t_ms: int
    x: float
    y: float
    w: float
    h: float
    confidence: float


class FaceTracker:
    """Samples frames and records the dominant face box over time."""

    def __init__(
        self,
        *,
        ffmpeg_path: str,
        sample_fps: float = 2.0,
        min_confidence: float = 0.5,
        max_frames: int = 900,
    ) -> None:
        self.ffmpeg_path = ffmpeg_path
        self.sample_fps = sample_fps
        self.min_confidence = min_confidence
        self.max_frames = max_frames

    @property
    def available(self) -> bool:
        return opencv_available()

    def track(
        self,
        video_path: str,
        *,
        start_ms: int,
        end_ms: int,
        src_w: int,
        src_h: int,
    ) -> list[Keyframe]:
        if not self.available:
            logger.info("OpenCV unavailable; skipping face tracking (centre crop will be used)")
            return []
        if end_ms <= start_ms:
            return []

        detections = self._detect(video_path, start_ms=start_ms, end_ms=end_ms)
        return self._to_keyframes(detections, src_w=src_w, src_h=src_h)

    # -- internals ----------------------------------------------------------
    def _detect(self, video_path: str, *, start_ms: int, end_ms: int) -> list[Detection]:
        import cv2

        duration_s = max(0.1, (end_ms - start_ms) / 1000)
        frame_count = int(min(self.max_frames, duration_s * self.sample_fps))
        detector = cv2.FaceDetectorYN.create(
            _model_path(), "", (320, 320), self.min_confidence, 0.3, 5000
        )
        cap = cv2.VideoCapture(video_path)
        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            first = int(start_ms / 1000 * fps)
            last = int(end_ms / 1000 * fps)
            step = max(1, (last - first) // max(1, frame_count))
            cap.set(cv2.CAP_PROP_POS_FRAMES, first)
            out: list[Detection] = []
            index = first
            while index < last and len(out) < self.max_frames:
                cap.set(cv2.CAP_PROP_POS_FRAMES, index)
                ok, frame = cap.read()
                if not ok:
                    break
                height, width = frame.shape[:2]
                detector.setInputSize((width, height))
                _rc, faces = detector.detect(frame)
                if faces is not None and len(faces):
                    # Largest face = the person currently filling the frame.
                    face = max(faces, key=lambda f: f[2] * f[3])
                    fx, fy, fw, fh, score = (float(v) for v in face[:5])
                    out.append(
                        Detection(
                            t_ms=int(index / fps * 1000) - start_ms,
                            x=fx / width,
                            y=fy / height,
                            w=fw / width,
                            h=fh / height,
                            confidence=score,
                        )
                    )
                index += step
            return out
        finally:
            cap.release()

    def _to_keyframes(
        self, detections: list[Detection], *, src_w: int, src_h: int
    ) -> list[Keyframe]:
        if not detections:
            return []
        # Merge detections closer than 400 ms so the crop does not jitter.
        merged: list[Detection] = []
        for detection in detections:
            if merged and detection.t_ms - merged[-1].t_ms < 400:
                previous = merged[-1]
                merged[-1] = Detection(
                    t_ms=detection.t_ms,
                    x=(previous.x + detection.x) / 2,
                    y=(previous.y + detection.y) / 2,
                    w=(previous.w + detection.w) / 2,
                    h=(previous.h + detection.h) / 2,
                    confidence=max(previous.confidence, detection.confidence),
                )
            else:
                merged.append(detection)
        return [
            Keyframe(t_ms=d.t_ms, x=d.x, y=d.y, w=d.w, h=d.h) for d in merged
        ]


_MODEL_CANDIDATES = (
    "/usr/share/viralcut/face_detection_yunet_2023mar.onnx",
    "/opt/viralcut/models/face_detection_yunet_2023mar.onnx",
)


def _model_path() -> str:
    import os

    explicit = os.environ.get("VIRALCUT_FACE_MODEL")
    if explicit and os.path.exists(explicit):
        return explicit
    for candidate in _MODEL_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    raise RuntimeError(
        "YuNet face-detection model not found. Set VIRALCUT_FACE_MODEL to "
        "face_detection_yunet_2023mar.onnx (see README)."
    )


def frame_sample_times(start_ms: int, end_ms: int, *, fps: float = 1.0) -> list[int]:
    """Helper used by the thumbnail step."""
    if end_ms <= start_ms:
        return [start_ms]
    step = max(1, int(1000 / fps))
    return list(range(start_ms, end_ms, step))[:60]
