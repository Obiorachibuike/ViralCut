"""Text-to-video provider abstraction.

One contract, several interchangeable backends. The engine never hard-codes a
vendor: `VIRALCUT_T2V_PROVIDER` selects the backend and
`GET /v1/generate/providers` reports honestly which ones are usable.

A provider either returns a URL the engine can fetch, a local file path, or raw
bytes — the service layer normalises all three into a stored object key, so the
rest of ViralCut treats generated video exactly like an uploaded one.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

#: Progress callback: (fraction 0..1, human message)
ProgressHook = Callable[[float, str], None]


@dataclass(slots=True)
class GenerationRequest:
    prompt: str
    negative_prompt: str = ""
    seconds: float = 5.0
    aspect_ratio: str = "9:16"
    seed: int | None = None
    #: Provider-specific model override (e.g. an fal model slug or Replicate version).
    model: str | None = None

    def validated(self, max_seconds: float, supported: tuple[str, ...]) -> "GenerationRequest":
        """Clamp duration to what the backend supports and normalise the ratio."""
        seconds = max(1.0, min(float(max_seconds), self.seconds))
        ratio = self.aspect_ratio if self.aspect_ratio in supported else supported[0]
        return GenerationRequest(
            prompt=self.prompt.strip(),
            negative_prompt=self.negative_prompt.strip(),
            seconds=seconds,
            aspect_ratio=ratio,
            seed=self.seed,
            model=self.model,
        )


@dataclass(slots=True)
class GenerationResult:
    provider: str
    model: str
    #: Exactly one of these is populated, in preference order url > path > data.
    video_url: str | None = None
    video_path: str | None = None
    video_bytes: bytes | None = None
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    #: Provider ids worth keeping for troubleshooting (prediction/task/generation id).
    provider_job_id: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def has_output(self) -> bool:
        return bool(self.video_url or self.video_path or self.video_bytes)


class TextToVideoProvider(ABC):
    """Contract every text-to-video backend implements."""

    #: Stable machine name, used by VIRALCUT_T2V_PROVIDER.
    name: str = "abstract"
    #: Human label for the UI.
    label: str = "Abstract"
    #: Longest clip this backend can produce, in seconds.
    max_seconds: float = 10.0
    #: Aspect ratios this backend understands.
    supported_aspects: tuple[str, ...] = ("9:16",)

    @abstractmethod
    def configured(self) -> bool:
        """True when the credentials/endpoint needed to call it are present."""

    def status(self) -> dict[str, Any]:
        """Honest capability report surfaced by GET /v1/generate/providers."""
        return {
            "name": self.name,
            "label": self.label,
            "configured": self.configured(),
            "maxSeconds": self.max_seconds,
            "supportedAspects": list(self.supported_aspects),
            "requiresNetwork": True,
        }

    @abstractmethod
    def generate(
        self,
        request: GenerationRequest,
        on_progress: ProgressHook | None = None,
    ) -> GenerationResult:
        """Produce a video. Raises GenerationError on failure — never returns fakes."""


class GenerationError(RuntimeError):
    """A backend refused, timed out, or returned something unusable."""

    def __init__(self, message: str, *, log_detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.log_detail = log_detail


#: Aspect ratio -> the "WxH" phrasing most backends expect.
RATIO_DIMENSIONS: dict[str, tuple[int, int]] = {
    "9:16": (720, 1280),
    "1:1": (1024, 1024),
    "16:9": (1280, 720),
    "4:5": (1080, 1350),
}
