"""pyannote.audio speaker diarization adapter.

Maps each transcript segment to the speaker who dominates it. Requires an
accept-terms Hugging Face token for the pyannote models, so the whole module is
guarded: when it is unavailable, diarization is skipped and the pipeline
continues with `speaker=None`.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

from app.errors import DependencyUnavailableError
from transcription.base import Transcript

logger = logging.getLogger("viralcut.diarization")


@dataclass(slots=True)
class SpeakerSpan:
    label: str
    start_ms: int
    end_ms: int


def pyannote_available() -> bool:
    try:
        import pyannote.audio  # noqa: F401

        return True
    except Exception:
        return False


class PyAnnoteDiarizer:
    name = "pyannote"

    def __init__(self, *, model: str = "pyannote/speaker-diarization-3.1", hf_token: str = "") -> None:
        self.model_name = model
        self.hf_token = hf_token
        self._pipeline: Any = None
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return pyannote_available() and bool(self.hf_token)

    def _load(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline
        with self._lock:
            if self._pipeline is not None:
                return self._pipeline
            if not self.available:
                raise DependencyUnavailableError(
                    "pyannote.audio is not installed or HF_TOKEN is not set. Speaker diarization "
                    "requires accepting the pyannote model terms on Hugging Face."
                )
            from pyannote.audio import Pipeline

            self._pipeline = Pipeline.from_pretrained(self.model_name, use_auth_token=self.hf_token)
            return self._pipeline

    def diarize(self, audio_path: str, *, num_speakers: int | None = None) -> list[SpeakerSpan]:
        pipeline = self._load()
        try:
            kwargs: dict[str, Any] = {}
            if num_speakers:
                kwargs["num_speakers"] = num_speakers
            output = pipeline(audio_path, **kwargs)
        except Exception as err:
            logger.exception("diarization failed on %s", audio_path)
            raise DependencyUnavailableError(
                "Speaker detection failed. The transcript is still available; retry to add speakers.",
                log_detail=f"{err.__class__.__name__}: {err}",
            ) from err

        spans: list[SpeakerSpan] = []
        for turn, _track, label in output.itertracks(yield_label=True):
            spans.append(
                SpeakerSpan(
                    label=str(label),
                    start_ms=int(round(turn.start * 1000)),
                    end_ms=int(round(turn.end * 1000)),
                )
            )
        spans.sort(key=lambda s: s.start_ms)
        return spans

    def speakers(self, spans: list[SpeakerSpan]) -> list[str]:
        seen: list[str] = []
        for span in spans:
            if span.label not in seen:
                seen.append(span.label)
        return seen


def assign_speakers(transcript: Transcript, spans: list[SpeakerSpan]) -> int:
    """Label every segment with the speaker covering the most of its duration."""
    if not spans:
        return 0
    assigned = 0
    for segment in transcript.segments:
        tally: dict[str, int] = {}
        for span in spans:
            overlap = min(segment.end_ms, span.end_ms) - max(segment.start_ms, span.start_ms)
            if overlap > 0:
                tally[span.label] = tally.get(span.label, 0) + overlap
        if tally:
            segment.speaker = max(tally.items(), key=lambda item: item[1])[0]
            assigned += 1
    return assigned


def display_name_for(label: str) -> str:
    """SPEAKER_00 -> Speaker 1 (stable, human-friendly)."""
    digits = "".join(ch for ch in label if ch.isdigit())
    if digits:
        return f"Speaker {int(digits) + 1}"
    return label.replace("_", " ").title()


def create_diarizer() -> PyAnnoteDiarizer | None:
    from app.config import get_settings

    settings = get_settings()
    diarizer = PyAnnoteDiarizer(model=settings.diarization_model, hf_token=settings.hf_token)
    if not diarizer.available:
        logger.info(
            "diarization unavailable (pyannote installed=%s, hf_token=%s); continuing without speakers",
            pyannote_available(),
            bool(settings.hf_token),
        )
        return None
    return diarizer
