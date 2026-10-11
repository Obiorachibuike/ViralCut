"""Scene detection.

Primary backend is PySceneDetect (`ContentDetector`). When it is not installed
we fall back to FFmpeg's own scene filter
(`select='gt(scene,T)',showinfo`), which is the same class of content-difference
detector — so moment scoring always has real visual cuts to work with.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from typing import Any

from app.errors import MediaError
from moments.scoring import SceneSpan

logger = logging.getLogger("viralcut.video.scenes")

_PTS_RE = re.compile(r"pts_time:(?P<time>\d+(?:\.\d+)?)")


@dataclass(slots=True)
class Scene:
    index: int
    start_ms: int
    end_ms: int
    cut_score: float | None = None

    def as_span(self) -> SceneSpan:
        return SceneSpan(start_ms=self.start_ms, end_ms=self.end_ms, cut_score=self.cut_score)


def py_scene_detect_available() -> bool:
    try:
        import scenedetect  # noqa: F401

        return True
    except Exception:
        return False


class SceneDetector:
    def __init__(
        self,
        *,
        ffmpeg_path: str,
        threshold: float = 27.0,
        min_scene_seconds: float = 1.2,
        timeout: int = 1800,
    ) -> None:
        self.ffmpeg_path = ffmpeg_path
        self.threshold = threshold
        self.min_scene_seconds = min_scene_seconds
        self.timeout = timeout

    @property
    def backend(self) -> str:
        return "pyscenedetect" if py_scene_detect_available() else "ffmpeg-scene-filter"

    def detect(self, video_path: str, *, duration_ms: int | None = None) -> list[Scene]:
        if py_scene_detect_available():
            try:
                return self._detect_pyscenedetect(video_path, duration_ms)
            except Exception as err:  # pragma: no cover - depends on cv2 build
                logger.warning("PySceneDetect failed (%s); falling back to FFmpeg", err)
        return self._detect_ffmpeg(video_path, duration_ms)

    # -- backends -----------------------------------------------------------
    def _detect_pyscenedetect(self, video_path: str, duration_ms: int | None) -> list[Scene]:
        from scenedetect import ContentDetector, detect  # type: ignore

        scene_list = detect(video_path, ContentDetector(threshold=self.threshold))
        scenes: list[Scene] = []
        for index, (start, end) in enumerate(scene_list):
            start_ms = int(start.get_seconds() * 1000)
            end_ms = int(end.get_seconds() * 1000)
            if end_ms - start_ms < self.min_scene_seconds * 1000:
                continue
            scenes.append(Scene(index=len(scenes), start_ms=start_ms, end_ms=end_ms))
        if not scenes and duration_ms:
            scenes = [Scene(index=0, start_ms=0, end_ms=duration_ms)]
        return scenes

    def _detect_ffmpeg(self, video_path: str, duration_ms: int | None) -> list[Scene]:
        """FFmpeg's scene filter reports a 0..1 content-difference per frame."""
        # ContentDetector's 27 is on a 0-255 scale; the scene filter uses 0..1.
        normalised = max(0.05, min(0.9, self.threshold / 100))
        argv = [
            self.ffmpeg_path, "-hide_banner", "-nostdin",
            "-i", video_path,
            "-vf", f"select='gt(scene,{normalised})',showinfo",
            "-f", "null", "-",
        ]
        try:
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=self.timeout, check=False)
        except subprocess.TimeoutExpired as err:
            raise MediaError("Scene detection timed out. The video may be very long.") from err
        if proc.returncode != 0:
            raise MediaError(
                "Scene detection failed.", log_detail=(proc.stderr or "")[-800:]
            )

        cuts: list[float] = []
        for match in _PTS_RE.finditer(proc.stderr or ""):
            cuts.append(float(match.group("time")))
        cuts = sorted(set(cuts))

        # Enforce the minimum scene length by dropping cuts that are too close.
        kept: list[float] = []
        for cut in cuts:
            if not kept or (cut - kept[-1]) >= self.min_scene_seconds:
                kept.append(cut)

        total_ms = duration_ms or (int(kept[-1] * 1000) + 5000 if kept else 0)
        boundaries = [0.0] + kept + [total_ms / 1000]
        scenes: list[Scene] = []
        for index in range(len(boundaries) - 1):
            start_ms = int(boundaries[index] * 1000)
            end_ms = int(boundaries[index + 1] * 1000)
            if end_ms <= start_ms:
                continue
            scenes.append(
                Scene(
                    index=len(scenes),
                    start_ms=start_ms,
                    end_ms=end_ms,
                    # Cuts found by the filter are by definition above threshold.
                    cut_score=round(normalised * 100, 1) if index > 0 else None,
                )
            )
        if not scenes and total_ms:
            scenes = [Scene(index=0, start_ms=0, end_ms=total_ms)]
        return scenes


def scenes_to_tuples(scenes: list[Scene]) -> list[tuple[int, int, float | None]]:
    return [(s.start_ms, s.end_ms, s.cut_score) for s in scenes]


def scenes_covering(scenes: list[Scene], start_ms: int, end_ms: int) -> list[Scene]:
    return [s for s in scenes if s.start_ms < end_ms and s.end_ms > start_ms]
