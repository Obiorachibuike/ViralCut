"""Context-aware clip boundaries.

The rule is: never cut mid-word, never cut mid-sentence, never start before the
context the payoff needs, never end before the payoff lands. Padding is bounded
by the caller's config (default 0-5 s each side) and by the surrounding silence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from transcription.base import Segment

_SENTENCE_END_RE = re.compile(r"[.!?…]\s*$")
# Tails that cannot end a sentence. ASR frequently drops punctuation entirely,
# so a trailing modal / auxiliary / function word means the thought is unfinished.
_INCOMPLETE_END_RE = re.compile(
    r"\b(?:and|but|or|so|because|that|which|who|whom|the|a|an|to|of|in|on|for|with|from|at|by|as|if|when|while|"
    r"is|are|was|were|am|be|been|being|have|has|had|do|does|did|not|no|than|then|about|into|onto|over|under|"
    r"should|would|could|will|shall|might|must|can|cannot|going|gonna|wanna|need|needs|wanted|want)\s*$",
    re.I,
)


@dataclass(slots=True)
class Boundary:
    start_ms: int
    end_ms: int
    pad_before_ms: int = 0
    pad_after_ms: int = 0
    snapped: bool = False
    notes: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.notes is None:
            self.notes = []

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)


def snap_start_to_segment(segments: list[Segment], target_ms: int) -> tuple[int, bool]:
    """Move a start time onto the beginning of the segment that contains it.

    Cutting inside a segment starts the clip mid-sentence, which is exactly what
    spec 16 forbids.
    """
    if not segments:
        return target_ms, False
    for segment in segments:
        if segment.start_ms <= target_ms < segment.end_ms:
            return segment.start_ms, segment.start_ms != target_ms
        if segment.start_ms > target_ms:
            return segment.start_ms, True
    return segments[-1].start_ms, True


def snap_end_to_segment(segments: list[Segment], target_ms: int) -> tuple[int, bool]:
    if not segments:
        return target_ms, False
    for segment in segments:
        if segment.start_ms < target_ms <= segment.end_ms:
            return segment.end_ms, segment.end_ms != target_ms
    if target_ms <= segments[0].start_ms:
        return segments[0].end_ms, True
    return segments[-1].end_ms, True


def ends_mid_sentence(text: str) -> bool:
    """True when the tail of `text` is not a finished thought."""
    stripped = (text or "").rstrip()
    if not stripped:
        return False
    if _SENTENCE_END_RE.search(stripped):
        return False
    # No terminal punctuation at all: only complete if the last token is a
    # content word (ASR often drops punctuation entirely).
    if _INCOMPLETE_END_RE.search(stripped):
        return True
    return not stripped[-1].isalnum() and not _SENTENCE_END_RE.search(stripped)


def extend_to_sentence_end(
    segments: list[Segment],
    end_ms: int,
    *,
    max_extra_ms: int = 6000,
) -> tuple[int, str | None]:
    """Push the end forward until the transcript reads as a finished sentence."""
    limit = end_ms + max_extra_ms
    cursor = end_ms
    note = None
    for segment in segments:
        if segment.start_ms >= limit:
            break
        if segment.end_ms <= cursor:
            continue
        cursor = segment.end_ms
        note = segment.text
        if not ends_mid_sentence(segment.text):
            return cursor, None
        if cursor >= limit:
            break
    if note and ends_mid_sentence(note):
        # Still dangling: retreat to the last complete segment we passed.
        for segment in reversed(segments):
            if segment.end_ms <= cursor and not ends_mid_sentence(segment.text):
                return segment.end_ms, None
    return cursor, None


def word_boundary_ms(segments: list[Segment], target_ms: int, *, direction: str) -> int:
    """Snap to the nearest word edge so a caption never starts half a word."""
    best: int | None = None
    for segment in segments:
        for word in segment.words:
            if direction == "back" and word.start_ms <= target_ms:
                best = word.start_ms
            elif direction == "forward" and word.end_ms >= target_ms:
                return word.end_ms
    return best if best is not None else target_ms


def apply_padding(
    segments: list[Segment],
    boundary: Boundary,
    *,
    pad_before_ms: int,
    pad_after_ms: int,
    transcript_start_ms: int = 0,
    transcript_end_ms: int | None = None,
) -> Boundary:
    """Add breathing room, clamped to the media and snapped to word edges."""
    notes: list[str] = []
    start = boundary.start_ms
    end = boundary.end_ms

    if pad_before_ms > 0:
        candidate = max(transcript_start_ms, start - pad_before_ms)
        snapped = word_boundary_ms(segments, candidate, direction="back")
        # Never reach back past the previous segment's tail — that would pull in
        # the previous speaker's sentence.
        for segment in segments:
            if segment.end_ms <= start and segment.end_ms > snapped:
                snapped = max(transcript_start_ms, segment.end_ms)
                notes.append("pad-before clamped to previous segment end")
        start = snapped
        boundary.pad_before_ms = max(0, boundary.start_ms - start)

    if pad_after_ms > 0:
        candidate = end + pad_after_ms
        if transcript_end_ms is not None:
            candidate = min(transcript_end_ms, candidate)
        snapped = word_boundary_ms(segments, candidate, direction="forward")
        if transcript_end_ms is not None:
            snapped = min(transcript_end_ms, snapped)
        end = max(end, snapped)
        boundary.pad_after_ms = max(0, end - boundary.end_ms)

    boundary.start_ms = start
    boundary.end_ms = end
    boundary.notes.extend(notes)
    return boundary


def needs_prior_context(text: str) -> bool:
    """True when the opener depends on something said earlier."""
    head = (text or "").strip().lower()[:60]
    dependent = (
        "as i said", "like i said", "as i mentioned", "like i mentioned",
        "as you know", "so anyway", "the other", "another thing",
        "that thing", "going back", "earlier", "and that", "which is why",
    )
    if any(marker in head for marker in dependent):
        return True
    first_word = head.split(" ", 1)[0] if head else ""
    return first_word in {"it", "he", "she", "they", "that", "this", "those", "them", "and", "but", "so"}


def include_context_segment(
    segments: list[Segment],
    start_index: int,
    *,
    max_extra_ms: int = 8000,
) -> int:
    """Return the segment index to actually start on, pulling in setup if needed."""
    if start_index <= 0 or start_index >= len(segments):
        return start_index
    current = segments[start_index]
    if not needs_prior_context(current.text):
        return start_index
    previous = segments[start_index - 1]
    if current.start_ms - previous.start_ms <= max_extra_ms:
        return start_index - 1
    return start_index


def build_boundary(
    segments: list[Segment],
    start_ms: int,
    end_ms: int,
    *,
    pad_before_ms: int = 0,
    pad_after_ms: int = 0,
    transcript_start_ms: int = 0,
    transcript_end_ms: int | None = None,
    snap: bool = True,
) -> Boundary:
    """Full boundary pass: snap -> sentence completion -> padding."""
    if end_ms <= start_ms:
        raise ValueError("end_ms must be greater than start_ms")

    notes: list[str] = []
    snapped = False
    if snap and segments:
        new_start, moved_start = snap_start_to_segment(segments, start_ms)
        new_end, moved_end = snap_end_to_segment(segments, end_ms)
        snapped = moved_start or moved_end
        start_ms, end_ms = new_start, new_end
        if snapped:
            notes.append("snapped to segment boundaries")
        completed, _ = extend_to_sentence_end(segments, end_ms)
        if completed != end_ms:
            notes.append("extended to sentence end")
            end_ms = completed

    boundary = Boundary(start_ms=start_ms, end_ms=end_ms, snapped=snapped, notes=notes)
    if pad_before_ms or pad_after_ms:
        boundary = apply_padding(
            segments,
            boundary,
            pad_before_ms=pad_before_ms,
            pad_after_ms=pad_after_ms,
            transcript_start_ms=transcript_start_ms,
            transcript_end_ms=transcript_end_ms,
        )
    return boundary
