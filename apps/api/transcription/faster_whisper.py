"""faster-whisper speech-to-text adapter.

Emits word-level timings, which the caption generator needs for karaoke styles
and which the boundary logic needs to avoid cutting mid-word.

The model is loaded lazily and cached for the process: Whisper weights are large
and loading them per request would dominate every job.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from app.errors import DependencyUnavailableError, TranscriptionError
from transcription.base import Segment, Transcript, Word

logger = logging.getLogger("viralcut.transcription.faster_whisper")


def faster_whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401

        return True
    except Exception:
        return False


class FasterWhisperTranscriber:
    name = "faster-whisper"

    def __init__(
        self,
        *,
        model_size: str = "small",
        device: str = "auto",
        compute_type: str = "default",
        vad_filter: bool = True,
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.vad_filter = vad_filter
        self._model: Any = None
        self._lock = threading.Lock()

    @property
    def available(self) -> bool:
        return faster_whisper_available()

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            if not faster_whisper_available():
                raise DependencyUnavailableError(
                    "faster-whisper is not installed. Run `pip install faster-whisper` on the "
                    "transcription worker, or set VIRALCUT_TRANSCRIBER to another backend.",
                    log_detail="import faster_whisper failed",
                )
            from faster_whisper import WhisperModel

            device = self.device
            if device == "auto":
                try:
                    import torch

                    device = "cuda" if torch.cuda.is_available() else "cpu"
                except Exception:
                    device = "cpu"
            logger.info(
                "loading faster-whisper %s on %s (%s)", self.model_size, device, self.compute_type
            )
            self._model = WhisperModel(
                self.model_size, device=device, compute_type=self.compute_type
            )
            return self._model

    def transcribe(self, audio_path: str, *, language: str | None = None) -> Transcript:
        if not os.path.exists(audio_path):
            raise TranscriptionError("The audio file to transcribe is missing.")
        model = self._load()
        try:
            segments_iter, info = model.transcribe(
                audio_path,
                language=language,
                word_timestamps=True,
                vad_filter=self.vad_filter,
                beam_size=5,
            )
            segments: list[Segment] = []
            for index, raw in enumerate(segments_iter):
                words = [
                    Word(
                        text=(w.word or "").strip(),
                        start_ms=int(round((w.start or 0) * 1000)),
                        end_ms=int(round((w.end or 0) * 1000)),
                        probability=float(w.probability) if w.probability is not None else None,
                    )
                    for w in (getattr(raw, "words", None) or [])
                ]
                segments.append(
                    Segment(
                        index=index,
                        start_ms=int(round((raw.start or 0) * 1000)),
                        end_ms=int(round((raw.end or 0) * 1000)),
                        text=(raw.text or "").strip(),
                        confidence=float(raw.avg_logprob) if raw.avg_logprob is not None else None,
                        words=words,
                    )
                )
        except Exception as err:
            logger.exception("faster-whisper failed on %s", audio_path)
            raise TranscriptionError(
                "Transcription failed. This is usually a codec or memory problem — retry, "
                "or try a smaller model.",
                log_detail=f"{err.__class__.__name__}: {err}",
            ) from err

        if not segments:
            raise TranscriptionError(
                "No speech was detected in that recording. If it has narration, try a larger "
                "Whisper model or check the audio track."
            )

        # `avg_logprob` is a log probability; convert to something 0..1-ish for storage.
        for segment in segments:
            if segment.confidence is not None:
                segment.confidence = round(min(1.0, max(0.0, _logprob_to_confidence(segment.confidence))), 4)

        duration_ms = int(round((info.duration or 0) * 1000)) or segments[-1].end_ms
        return Transcript(
            language=getattr(info, "language", None) or language,
            model=self.model_size,
            duration_ms=duration_ms,
            segments=segments,
            settings={
                "vadFilter": self.vad_filter,
                "wordTimestamps": True,
                "computeType": self.compute_type,
            },
        )


def _logprob_to_confidence(avg_logprob: float) -> float:
    """Map Whisper's mean log-probability onto 0..1 (exp is monotonic and bounded)."""
    import math

    if avg_logprob >= 0:
        return 1.0
    return math.exp(avg_logprob)
