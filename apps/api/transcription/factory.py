"""Transcriber selection.

`VIRALCUT_TRANSCRIBER` chooses the backend:

    faster-whisper  (default; local GPU/CPU ASR)
    openai          (hosted API; needs AI_API_KEY)
    none            (fail loudly rather than pretending to transcribe)

ViralCut never fabricates a transcript. If no backend is usable the job fails
with an actionable message instead of silently producing empty results.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.config import get_settings
from app.errors import DependencyUnavailableError
from transcription.base import Segment, Transcript, Word
from transcription.faster_whisper import FasterWhisperTranscriber, faster_whisper_available

logger = logging.getLogger("viralcut.transcription")


class OpenAITranscriber:
    """Hosted transcription via the OpenAI-compatible audio endpoint."""

    name = "openai"

    def __init__(self, *, api_key: str, model: str = "whisper-1", base_url: str = "https://api.openai.com/v1") -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def transcribe(self, audio_path: str, *, language: str | None = None) -> Transcript:
        import httpx

        with open(audio_path, "rb") as handle:
            response = httpx.post(
                f"{self.base_url}/audio/transcriptions",
                headers={"authorization": f"Bearer {self.api_key}"},
                files={"file": (os.path.basename(audio_path), handle, "audio/wav")},
                data={
                    "model": self.model,
                    "response_format": "verbose_json",
                    "timestamp_granularities[]": ["segment", "word"],
                    **({"language": language} if language else {}),
                },
                timeout=600,
            )
        if response.status_code != 200:
            from app.errors import TranscriptionError

            raise TranscriptionError(
                "Hosted transcription rejected the request.",
                log_detail=f"HTTP {response.status_code}: {response.text[:300]}",
            )
        data = response.json()
        segments: list[Segment] = []
        for index, raw in enumerate(data.get("segments") or []):
            segments.append(
                Segment(
                    index=index,
                    start_ms=int(round(float(raw.get("start", 0)) * 1000)),
                    end_ms=int(round(float(raw.get("end", 0)) * 1000)),
                    text=str(raw.get("text", "")).strip(),
                    confidence=raw.get("avg_logprob"),
                )
            )
        for raw_word in data.get("words") or []:
            start_ms = int(round(float(raw_word.get("start", 0)) * 1000))
            target = next((s for s in segments if s.start_ms <= start_ms < s.end_ms), None)
            if target is not None:
                target.words.append(
                    Word(
                        text=str(raw_word.get("word", "")).strip(),
                        start_ms=start_ms,
                        end_ms=int(round(float(raw_word.get("end", 0)) * 1000)),
                    )
                )
        return Transcript(
            language=data.get("language") or language,
            model=self.model,
            duration_ms=int(round(float(data.get("duration", 0)) * 1000)),
            segments=segments,
        )


def create_transcriber(name: str | None = None) -> Any:
    settings = get_settings()
    choice = (name or os.environ.get("VIRALCUT_TRANSCRIBER") or "faster-whisper").lower()

    if choice in ("none", "disabled"):
        raise DependencyUnavailableError(
            "Transcription is disabled on this instance (VIRALCUT_TRANSCRIBER=none)."
        )
    if choice in ("openai", "hosted"):
        api_key = settings.ai_api_key
        if not api_key:
            raise DependencyUnavailableError(
                "VIRALCUT_TRANSCRIBER=openai but AI_API_KEY is not set."
            )
        return OpenAITranscriber(api_key=api_key, base_url=settings.ai_base_url or "https://api.openai.com/v1")
    if choice == "faster-whisper":
        if not faster_whisper_available():
            raise DependencyUnavailableError(
                "faster-whisper is not installed. Run `pip install faster-whisper` on the "
                "transcription worker."
            )
        return FasterWhisperTranscriber(
            model_size=settings.whisper_model,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
        )
    raise DependencyUnavailableError(f"Unknown transcriber: {choice!r}")


def transcriber_status() -> dict[str, Any]:
    """Reported by /v1/health so the orchestrator can explain a failure."""
    settings = get_settings()
    return {
        "configured": os.environ.get("VIRALCUT_TRANSCRIBER", "faster-whisper"),
        "fasterWhisperInstalled": faster_whisper_available(),
        "model": settings.whisper_model,
        "hostedConfigured": bool(settings.ai_api_key),
    }
