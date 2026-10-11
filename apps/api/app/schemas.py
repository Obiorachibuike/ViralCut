"""Pydantic request/response models for the media engine API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from providers.base import SourceKind

AspectRatio = Literal["9:16", "1:1", "16:9", "4:5"]
ReframeMode = Literal["AUTO", "CENTER", "SPEAKER_TRACK", "SPLIT_SCREEN"]
CaptionStyleName = Literal["MINIMAL", "BOLD", "KARAOKE", "CREATOR", "PODCAST", "HIGH_IMPACT"]


class ErrorBody(BaseModel):
    id: str
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class ResolveUrlRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


class ResolveUrlResponse(BaseModel):
    kind: str
    provider: str
    permitted: bool
    externalId: str | None = None
    title: str | None = None
    reason: str | None = None
    isPrivate: bool = False
    requiresLogin: bool = False
    drmProtected: bool = False
    isLive: bool = False
    providers: list[dict[str, Any]] = Field(default_factory=list)


class DownloadRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    runId: str = Field(min_length=1, max_length=64)


class DownloadResponse(BaseModel):
    storageKey: str
    sizeBytes: int
    kind: str
    provider: str


class InspectRequest(BaseModel):
    storageKey: str = Field(min_length=1)


class ScoringWeights(BaseModel):
    hook: float | None = Field(default=None, ge=0, le=1)
    curiosity: float | None = Field(default=None, ge=0, le=1)
    emotion: float | None = Field(default=None, ge=0, le=1)
    story: float | None = Field(default=None, ge=0, le=1)
    value: float | None = Field(default=None, ge=0, le=1)
    share: float | None = Field(default=None, ge=0, le=1)
    standalone: float | None = Field(default=None, ge=0, le=1)
    visual: float | None = Field(default=None, ge=0, le=1)


class ProcessRequest(BaseModel):
    storageKey: str = Field(min_length=1)
    runId: str = Field(min_length=1, max_length=64)
    maxCandidates: int | None = Field(default=None, ge=5, le=200)
    minScore: float = Field(default=0, ge=0, le=100)
    minDurationSec: float = Field(default=20, ge=5, le=600)
    maxDurationSec: float = Field(default=120, ge=10, le=900)
    padBeforeSec: float = Field(default=0, ge=0, le=5)
    padAfterSec: float = Field(default=0, ge=0, le=5)
    categories: list[str] | None = None
    weights: ScoringWeights | None = None
    dedupeThreshold: float = Field(default=0.72, ge=0, le=1)
    limit: int | None = Field(default=None, ge=1, le=200)
    language: str | None = None
    skipDiarization: bool = False

    @field_validator("maxDurationSec")
    @classmethod
    def _order(cls, value: float, info: Any) -> float:
        data = info.data
        if "minDurationSec" in data and value <= data["minDurationSec"]:
            raise ValueError("maxDurationSec must be greater than minDurationSec")
        return value


class StageEvent(BaseModel):
    stage: str
    progress: int
    message: str
    at: float


class RunState(BaseModel):
    runId: str
    state: str = "QUEUED"
    progress: int = 0
    events: list[StageEvent] = Field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str | None = None
    errorCode: str | None = None


class RenderKeyframe(BaseModel):
    tMs: int
    x: float
    y: float
    w: float
    h: float


class RenderRequest(BaseModel):
    storageKey: str = Field(min_length=1)
    outputKey: str = Field(min_length=1)
    startMs: int = Field(ge=0)
    endMs: int = Field(gt=0)
    srcWidth: int = Field(gt=0)
    srcHeight: int = Field(gt=0)
    aspect: AspectRatio = "9:16"
    reframeMode: ReframeMode = "AUTO"
    keyframes: list[RenderKeyframe] = Field(default_factory=list)
    captions: list[dict[str, Any]] = Field(default_factory=list)
    captionStyle: CaptionStyleName = "CREATOR"
    captionOverrides: dict[str, Any] = Field(default_factory=dict)
    muted: bool = False
    volume: float = Field(default=1.0, ge=0, le=3)
    musicKey: str | None = None
    musicVolume: float = Field(default=0.18, ge=0, le=1)
    watermarkText: str | None = Field(default=None, max_length=60)
    watermarkKey: str | None = None
    maxShortSide: int | None = Field(default=None, ge=240, le=2160)
    preset: str = "medium"
    crf: int = Field(default=20, ge=0, le=51)


class RenderResponse(BaseModel):
    storageKey: str
    sizeBytes: int
    width: int
    height: int
    durationMs: int
    captionsBurned: bool
    plan: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)


class CaptionsRequest(BaseModel):
    transcript: dict[str, Any]
    wordsPerLine: int = Field(default=3, ge=1, le=12)
    uppercase: bool = True
    style: CaptionStyleName = "CREATOR"
    width: int = Field(default=1080, ge=240, le=2160)
    height: int = Field(default=1920, ge=240, le=2160)
    watermarkText: str | None = None


class CaptionsResponse(BaseModel):
    lines: list[dict[str, Any]]
    ass: str
    srt: str
    vtt: str


class ReframePlanRequest(BaseModel):
    srcWidth: int = Field(gt=0)
    srcHeight: int = Field(gt=0)
    aspect: AspectRatio = "9:16"
    reframeMode: ReframeMode = "AUTO"
    keyframes: list[RenderKeyframe] = Field(default_factory=list)
    maxShortSide: int | None = Field(default=None, ge=240, le=2160)


class BrollRequest(BaseModel):
    context: str = Field(min_length=1, max_length=2000)
    startSec: float = Field(ge=0)
    endSec: float = Field(gt=0)


class HealthResponse(BaseModel):
    status: str
    service: str
    ffmpeg: bool
    ffprobe: bool | None = None
    filters: dict[str, bool] = Field(default_factory=dict)
    transcription: dict[str, Any]
    diarization: bool
    ai: dict[str, Any]
    longcat: dict[str, Any]
    storage: str
    promptVersions: list[str]


ASPECTS = ("9:16", "1:1", "16:9", "4:5")


class TextToVideoRequest(BaseModel):
    """Prompt -> video. Idempotent per runId, like /v1/process."""

    runId: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=4000)
    negativePrompt: str = Field(default="", max_length=1000)
    seconds: float = Field(default=5.0, ge=1.0, le=60.0)
    aspectRatio: Literal["9:16", "1:1", "16:9", "4:5"] = "9:16"
    seed: int | None = None
    #: Backend override; defaults to VIRALCUT_T2V_PROVIDER.
    provider: str | None = None
    #: Backend-specific model override.
    model: str | None = None
