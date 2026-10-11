"""Transcript data model.

Every downstream stage (diarization, scene fusion, moment discovery, captions)
consumes these dataclasses, so swapping faster-whisper for another ASR engine
only means writing a new `Transcriber`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class Word:
    text: str
    start_ms: int
    end_ms: int
    probability: float | None = None

    @property
    def stripped(self) -> str:
        return self.text.strip()


@dataclass(slots=True)
class Segment:
    index: int
    start_ms: int
    end_ms: int
    text: str
    confidence: float | None = None
    speaker: str | None = None
    scene_id: int | None = None
    words: list[Word] = field(default_factory=list)

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)

    @property
    def start_s(self) -> float:
        return self.start_ms / 1000

    @property
    def end_s(self) -> float:
        return self.end_ms / 1000

    def words_per_second(self) -> float:
        seconds = self.duration_ms / 1000
        return len(self.text.split()) / seconds if seconds > 0 else 0.0


@dataclass(slots=True)
class Transcript:
    language: str | None = None
    model: str | None = None
    duration_ms: int = 0
    segments: list[Segment] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments if s.text.strip())

    @property
    def word_count(self) -> int:
        return sum(len(s.text.split()) for s in self.segments)

    def window(self, start_ms: int, end_ms: int) -> list[Segment]:
        """Segments overlapping [start_ms, end_ms), ordered by index."""
        return [s for s in self.segments if s.start_ms < end_ms and s.end_ms > start_ms]

    def speakers(self) -> list[str]:
        seen: list[str] = []
        for segment in self.segments:
            if segment.speaker and segment.speaker not in seen:
                seen.append(segment.speaker)
        return seen

    def to_dict(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "model": self.model,
            "durationMs": self.duration_ms,
            "wordCount": self.word_count,
            "segments": [
                {
                    "index": s.index,
                    "startMs": s.start_ms,
                    "endMs": s.end_ms,
                    "text": s.text,
                    "confidence": s.confidence,
                    "speaker": s.speaker,
                    "sceneId": s.scene_id,
                    "words": [
                        {"w": w.text, "s": w.start_ms, "e": w.end_ms, "p": w.probability}
                        for w in s.words
                    ],
                }
                for s in self.segments
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Transcript":
        segments: list[Segment] = []
        for raw in data.get("segments") or []:
            segments.append(
                Segment(
                    index=int(raw.get("index", len(segments))),
                    start_ms=int(raw["startMs"]),
                    end_ms=int(raw["endMs"]),
                    text=str(raw.get("text", "")),
                    confidence=raw.get("confidence"),
                    speaker=raw.get("speaker"),
                    scene_id=raw.get("sceneId"),
                    words=[
                        Word(
                            text=str(w.get("w", "")),
                            start_ms=int(w.get("s", 0)),
                            end_ms=int(w.get("e", 0)),
                            probability=w.get("p"),
                        )
                        for w in (raw.get("words") or [])
                    ],
                )
            )
        return cls(
            language=data.get("language"),
            model=data.get("model"),
            duration_ms=int(data.get("durationMs") or 0),
            segments=segments,
            settings=data.get("settings") or {},
        )


class Transcriber(Protocol):
    """Contract every speech-to-text backend implements."""

    name: str

    def transcribe(self, audio_path: str, *, language: str | None = None) -> Transcript: ...

    @property
    def available(self) -> bool: ...
