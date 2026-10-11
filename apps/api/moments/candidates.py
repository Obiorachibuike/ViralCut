"""Candidate moment generation.

Spec 14: generate many candidates first, store them as timestamp ranges, and
never auto-render. The candidate count scales with duration:

    ~20 min  -> 15-30 candidates
    ~60 min  -> 30-80 candidates
    ~120 min -> 50-120 candidates
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from moments.boundaries import build_boundary, include_context_segment
from moments.scoring import MomentScorer, ScoreBreakdown, ScoringContext, categorise
from moments.text import (
    CURIOSITY_MARKERS,
    EMOTION_WORDS,
    HOOK_MARKERS,
    STORY_MARKERS,
    VALUE_MARKERS,
    count_marker,
    count_words,
    normalise,
    word_count,
)
from transcription.base import Segment, Transcript

logger = logging.getLogger("viralcut.moments.candidates")


@dataclass(slots=True)
class Candidate:
    start_ms: int
    end_ms: int
    start_index: int
    end_index: int
    text: str
    scores: ScoreBreakdown
    final: float
    category: str
    tags: list[str]
    segments: list[Segment] = field(default_factory=list, repr=False)
    pad_before_ms: int = 0
    pad_after_ms: int = 0
    anchor_strength: float = 0.0
    speaker_turns: int = 0
    rank: int = 0
    cluster_id: str | None = None
    is_cluster_best: bool = True
    cluster_size: int = 1
    title: str = ""
    summary: str = ""
    hook_options: list[str] = field(default_factory=list)
    title_options: list[str] = field(default_factory=list)

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    def excerpt(self, limit: int = 320) -> str:
        text = " ".join(self.text.split())
        return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def target_for_duration(duration_seconds: float) -> int:
    """Explicit mapping onto the ranges spec 14 asks for."""
    if duration_seconds <= 0:
        return 15
    minutes = duration_seconds / 60
    if minutes <= 20:
        return int(min(30, max(15, round(minutes * 1.25))))
    if minutes <= 60:
        return int(min(80, max(30, round(30 + (minutes - 20) * (50 / 40)))))
    return int(min(120, max(80, round(80 + (minutes - 60) * (40 / 60)))))


def _anchor_strength(segment: Segment) -> float:
    """How promising this segment is as the FIRST line of a clip."""
    text = segment.text
    strength = 0.0
    strength += count_marker(text, HOOK_MARKERS)[1] * 3.0
    strength += count_marker(text, CURIOSITY_MARKERS)[1] * 1.6
    strength += count_marker(text, STORY_MARKERS)[1] * 1.1
    strength += count_marker(text, VALUE_MARKERS)[1] * 1.1
    strength += count_words(text, EMOTION_WORDS)[1] * 1.2
    words = word_count(text)
    if 6 <= words <= 28:
        strength += 0.8  # a crisp line reads as a hook
    if words < 3:
        strength -= 1.0
    normalised = normalise(text)
    if normalised.endswith("?"):
        strength += 0.9
    if normalised.startswith(("um ", "uh ", "so ", "yeah ", "okay ", "well ")):
        strength -= 1.2
    return strength


def _merge_text(segments: list[Segment]) -> str:
    return " ".join(s.text.strip() for s in segments if s.text.strip())


def _speaker_turns(segments: list[Segment]) -> int:
    turns = 0
    last: str | None = None
    for segment in segments:
        if segment.speaker and segment.speaker != last:
            turns += 1
            last = segment.speaker
    return turns


@dataclass(slots=True)
class CandidateOptions:
    min_duration_ms: int = 20_000
    max_duration_ms: int = 120_000
    pad_before_ms: int = 0
    pad_after_ms: int = 0
    target_count: int | None = None
    #: Length variants tried per anchor (seconds). Multiple lengths per anchor is
    #: what lets the scorer prefer the version where the payoff actually lands.
    length_variants_s: tuple[float, ...] = (30.0, 45.0, 60.0, 85.0)


def generate_candidates(
    transcript: Transcript,
    *,
    scorer: MomentScorer,
    options: CandidateOptions | None = None,
) -> list[Candidate]:
    options = options or CandidateOptions()
    segments = transcript.segments
    if len(segments) < 2:
        return []

    total_ms = transcript.duration_ms or (segments[-1].end_ms if segments else 0)
    target = options.target_count or target_for_duration(total_ms / 1000)

    # 1. Rank every segment as a potential opening line.
    anchors = sorted(
        ((idx, _anchor_strength(seg)) for idx, seg in enumerate(segments)),
        key=lambda pair: pair[1],
        reverse=True,
    )
    # Keep enough anchors that several length variants each can fill the target.
    anchor_pool = [idx for idx, strength in anchors if strength > 0][: max(target * 2, 24)]
    if not anchor_pool:
        anchor_pool = [idx for idx, _ in anchors[: max(target * 2, 24)]]

    candidates: list[Candidate] = []
    for anchor_index in anchor_pool:
        context_index = include_context_segment(segments, anchor_index)
        for variant_seconds in options.length_variants_s:
            desired_end = segments[context_index].start_ms + int(variant_seconds * 1000)
            if desired_end > total_ms + options.max_duration_ms:
                desired_end = total_ms
            boundary = build_boundary(
                segments,
                segments[context_index].start_ms,
                desired_end,
                pad_before_ms=options.pad_before_ms,
                pad_after_ms=options.pad_after_ms,
                transcript_start_ms=segments[0].start_ms,
                transcript_end_ms=segments[-1].end_ms,
            )
            duration = boundary.duration_ms
            if duration < options.min_duration_ms or duration > options.max_duration_ms:
                continue

            window = [
                s for s in segments
                if s.start_ms >= boundary.start_ms - 1 and s.end_ms <= boundary.end_ms + 1
            ]
            if len(window) < 2:
                continue
            text = _merge_text(window)
            if word_count(text) < 20:
                continue

            turns = _speaker_turns(window)
            scores = scorer.score(
                text,
                start_ms=boundary.start_ms,
                end_ms=boundary.end_ms,
                speaker_turns=turns,
            )
            category, tags = categorise(scores, text)
            candidates.append(
                Candidate(
                    start_ms=boundary.start_ms,
                    end_ms=boundary.end_ms,
                    start_index=window[0].index,
                    end_index=window[-1].index,
                    text=text,
                    scores=scores,
                    final=0.0,  # filled in by rank_moments with the configured weights
                    category=category,
                    tags=tags,
                    segments=window,
                    pad_before_ms=boundary.pad_before_ms,
                    pad_after_ms=boundary.pad_after_ms,
                    anchor_strength=next((s for i, s in anchors if i == anchor_index), 0.0),
                    speaker_turns=turns,
                )
            )

    logger.debug("generated %d raw candidates (target %d)", len(candidates), target)
    return candidates


def build_context(transcript: Transcript, scenes: list[tuple[int, int, float | None]]) -> ScoringContext:
    densities = [s.words_per_second() for s in transcript.segments if s.duration_ms > 0]
    densities.sort()
    median = densities[len(densities) // 2] if densities else 2.6
    from moments.scoring import SceneSpan

    return ScoringContext(
        video_duration_ms=transcript.duration_ms,
        scenes=[SceneSpan(start_ms=a, end_ms=b, cut_score=c) for a, b, c in scenes],
        total_segments=len(transcript.segments),
        median_words_per_second=median,
    )
