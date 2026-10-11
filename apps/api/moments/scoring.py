"""Moment scoring.

Eight signals, each 0-100, each computed from evidence that actually exists in
the transcript, the diarization output and the scene list:

  hook        how hard the first line grabs a cold viewer
  curiosity   how much it creates an open loop
  emotion     emotional intensity
  story       narrative completeness
  value       usefulness / actionability
  share       likelihood a viewer sends it on
  standalone  how well it works with zero prior context
  visual      whether the visual track can carry a vertical crop

Final score is the configurable weighted sum. There is no random component and
no constant: two different passages always produce different vectors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np

from moments.text import (
    CAUSAL_RE,
    CONTROVERSY_MARKERS,
    CURIOSITY_MARKERS,
    DANGLING_REFERENCE_MARKERS,
    EMOTION_WORDS,
    FIRST_PERSON_RE,
    HOOK_MARKERS,
    IMPERATIVE_RE,
    LAUGHTER_RE,
    MONEY_RE,
    NEGATION_RE,
    NUMBER_RE,
    PAST_TENSE_RE,
    SECOND_PERSON_RE,
    SHAREABLE_MARKERS,
    STORY_MARKERS,
    SUPERLATIVE_RE,
    VALUE_MARKERS,
    count_marker,
    count_phrases,
    count_words,
    is_question,
    normalise,
    sentence_starts_with_filler,
    word_count,
)

DIMENSIONS = ("hook", "curiosity", "emotion", "story", "value", "share", "standalone", "visual")

DEFAULT_WEIGHTS: dict[str, float] = {
    "hook": 0.20,
    "curiosity": 0.15,
    "emotion": 0.15,
    "story": 0.15,
    "value": 0.15,
    "share": 0.10,
    "standalone": 0.05,
    "visual": 0.05,
}


def validate_weights(weights: Mapping[str, float] | None) -> dict[str, float]:
    """Merge caller weights onto the defaults and re-normalise to sum 1."""
    merged = dict(DEFAULT_WEIGHTS)
    if weights:
        for key, value in weights.items():
            if key not in merged:
                raise ValueError(f"unknown scoring dimension: {key!r}")
            if value is None:
                continue
            value = float(value)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"weight {key!r} must be between 0 and 1, got {value}")
            merged[key] = value
    total = sum(merged.values())
    if total <= 0:
        raise ValueError("scoring weights must not all be zero")
    return {k: round(v / total, 6) for k, v in merged.items()}


def final_score(scores: Mapping[str, float], weights: Mapping[str, float] | None = None) -> float:
    normalised = validate_weights(weights)
    total = sum(float(scores.get(dim, 0.0)) * weight for dim, weight in normalised.items())
    return round(min(100.0, max(0.0, total)), 2)


@dataclass(slots=True)
class SceneSpan:
    start_ms: int
    end_ms: int
    cut_score: float | None = None


@dataclass(slots=True)
class ScoringContext:
    """Everything the scorer needs besides the passage itself."""

    video_duration_ms: int = 0
    scenes: list[SceneSpan] = field(default_factory=list)
    total_segments: int = 0
    median_words_per_second: float = 2.6


@dataclass(slots=True)
class ScoreBreakdown:
    hook: float
    curiosity: float
    emotion: float
    story: float
    value: float
    share: float
    standalone: float
    visual: float
    reasons: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, float]:
        return {dim: round(getattr(self, dim), 1) for dim in DIMENSIONS}

    @property
    def as_array(self) -> np.ndarray:
        return np.array([getattr(self, dim) for dim in DIMENSIONS], dtype=np.float32)


def _clamp(value: float) -> float:
    return round(min(100.0, max(0.0, value)), 1)


def _opening_line(text: str, max_words: int = 18) -> str:
    words = (text or "").split()
    return " ".join(words[:max_words])


class MomentScorer:
    """Pure function object: passage + context in, eight scores out."""

    def __init__(self, *, context: ScoringContext | None = None) -> None:
        self.context = context or ScoringContext()

    # -- individual signals -------------------------------------------------
    def hook(self, passage: str) -> tuple[float, str]:
        opening = _opening_line(passage)
        hits, strength = count_marker(opening, HOOK_MARKERS)
        score = min(100.0, strength * 42)

        if is_question(opening):
            score += 18
        if MONEY_RE.search(opening) or NUMBER_RE.search(opening):
            score += 14
        if SUPERLATIVE_RE.search(opening):
            score += 12
        if NEGATION_RE.search(opening):
            score += 8
        if len(opening.split()) <= 12 and word_count(opening) >= 4:
            score += 6  # short punchy openers cut through

        # A filler-led opener actively hurts the first two seconds.
        if sentence_starts_with_filler(opening):
            score -= 22

        reason = f"{hits} hook marker(s) in the opening line"
        if is_question(opening):
            reason += "; opens on a question"
        if sentence_starts_with_filler(opening):
            reason += "; starts with filler"
        return _clamp(score), reason

    def curiosity(self, passage: str) -> tuple[float, str]:
        hits, strength = count_marker(passage, CURIOSITY_MARKERS)
        score = min(100.0, strength * 34)
        questions = sum(1 for line in passage.split(".") if is_question(line))
        score += min(24.0, questions * 8)
        if CAUSAL_RE.search(passage):
            score += 8
        # An unresolved forward reference ("and then this happened") keeps people watching.
        tail = " ".join(passage.split()[-25:])
        if any(marker in normalise(tail) for marker in ("and then", "but then", "what happened", "next thing")):
            score += 10
        if NEGATION_RE.search(passage) and SUPERLATIVE_RE.search(passage):
            score += 6
        return _clamp(score), f"{hits} curiosity marker(s), {questions} question(s)"

    def emotion(self, passage: str) -> tuple[float, str]:
        hits, strength = count_words(passage, EMOTION_WORDS)
        score = min(100.0, strength * 30)
        lowered = passage.lower()
        if LAUGHTER_RE.search(lowered):
            score += 22
        exclamation = passage.count("!")
        score += min(12.0, exclamation * 4)
        if passage.isupper() and len(passage) > 8:
            score += 10
        # Emotional swings beat a flat affect.
        positive = sum(1 for w in ("amazing", "love", "excited", "proud", "grateful", "hope") if w in lowered)
        negative = sum(1 for w in ("hate", "angry", "cried", "devastated", "scared", "failed", "lost") if w in lowered)
        if positive and negative:
            score += 14
        return _clamp(score), f"{hits} affect word(s), {exclamation} exclamation(s)"

    def story(self, passage: str) -> tuple[float, str]:
        hits, strength = count_marker(passage, STORY_MARKERS)
        score = min(100.0, strength * 26)
        words = word_count(passage)
        past = len(PAST_TENSE_RE.findall(passage))
        first = len(FIRST_PERSON_RE.findall(passage))
        score += min(24.0, past * 3.0)
        score += min(14.0, first * 2.0)
        # A story needs length; 20 words cannot carry an arc.
        if words >= 90:
            score += 12
        elif words < 35:
            score -= 18
        if any(marker in normalise(passage) for marker in ("because", "so i", "and then", "in the end", "finally")):
            score += 8
        return _clamp(score), f"{hits} narrative marker(s), {past} past-tense verb(s)"

    def value(self, passage: str) -> tuple[float, str]:
        hits, strength = count_marker(passage, VALUE_MARKERS)
        score = min(100.0, strength * 28)
        imperatives = len(IMPERATIVE_RE.findall(passage))
        numbers = len(NUMBER_RE.findall(passage))
        score += min(20.0, imperatives * 5.0)
        score += min(16.0, numbers * 4.0)
        if SECOND_PERSON_RE.search(passage):
            score += 8
        if word_count(passage) >= 60:
            score += 6
        return _clamp(score), f"{hits} value marker(s), {imperatives} imperative(s), {numbers} number(s)"

    def share(self, passage: str) -> tuple[float, str]:
        hits, strength = count_marker(passage, SHAREABLE_MARKERS)
        score = min(100.0, strength * 40)
        controversy_hits, controversy_strength = count_marker(passage, CONTROVERSY_MARKERS)
        score += min(38.0, controversy_strength * 30)
        if SECOND_PERSON_RE.search(passage):
            score += 12  # "you" statements feel addressed to the viewer
        if MONEY_RE.search(passage) or NUMBER_RE.search(passage):
            score += 10  # concrete numbers get screenshotted
        if word_count(passage) <= 140:
            score += 8  # short enough to watch through, which drives shares
        return _clamp(score), f"{hits} share marker(s), {controversy_hits} controversy marker(s)"

    def standalone(self, passage: str) -> tuple[float, str]:
        score = 70.0
        dangling = count_phrases(passage, DANGLING_REFERENCE_MARKERS)
        score -= min(45.0, dangling * 15.0)
        if sentence_starts_with_filler(passage):
            score -= 18
        opening = _opening_line(passage, 12)
        # Opening on a bare pronoun with no antecedent confuses a cold viewer.
        if normalise(opening).split()[:1] in (["it"], ["he"], ["she"], ["they"], ["that"], ["this"]):
            score -= 14
        if word_count(passage) < 30:
            score -= 20  # too short to establish itself
        elif word_count(passage) > 220:
            score -= 8  # too long for a single cold watch
        if NEGATION_RE.search(opening) or SUPERLATIVE_RE.search(opening) or NUMBER_RE.search(opening):
            score += 10
        return _clamp(score), f"{dangling} dangling reference(s)"

    def visual(
        self,
        passage: str,
        *,
        start_ms: int,
        end_ms: int,
        speaker_turns: int = 0,
    ) -> tuple[float, str]:
        """Scored from the *real* scene list and speech density, not from text."""
        score = 45.0
        overlapping = [
            s for s in self.context.scenes if s.start_ms < end_ms and s.end_ms > start_ms
        ]
        cuts = max(0, len(overlapping) - 1)
        if cuts:
            # Some cutting keeps a vertical clip alive; a strobe does not.
            seconds = max(1.0, (end_ms - start_ms) / 1000)
            per_minute = cuts / seconds * 60
            if per_minute <= 12:
                score += min(28.0, cuts * 7.0)
            else:
                score -= min(20.0, (per_minute - 12) * 1.5)
            hard_cuts = sum(1 for s in overlapping if (s.cut_score or 0) >= 40)
            score += min(10.0, hard_cuts * 3.0)
        else:
            score -= 6  # one locked-off shot for the whole clip

        seconds = max(1.0, (end_ms - start_ms) / 1000)
        wps = word_count(passage) / seconds
        median = self.context.median_words_per_second or 2.6
        if wps <= 0.2:
            score -= 25  # near silence
        elif wps > median * 1.45:
            score -= 14  # frantic delivery, hard to caption
        else:
            score += 12

        if speaker_turns >= 2:
            score += 8  # two-shot / conversation reads well in split-screen
        return _clamp(score), f"{cuts} scene cut(s), {wps:.1f} words/s, {speaker_turns} speaker turn(s)"

    # -- composite ----------------------------------------------------------
    def score(
        self,
        passage: str,
        *,
        start_ms: int,
        end_ms: int,
        speaker_turns: int = 0,
    ) -> ScoreBreakdown:
        hook, hook_reason = self.hook(passage)
        curiosity, curiosity_reason = self.curiosity(passage)
        emotion, emotion_reason = self.emotion(passage)
        story, story_reason = self.story(passage)
        value, value_reason = self.value(passage)
        share, share_reason = self.share(passage)
        standalone, standalone_reason = self.standalone(passage)
        visual, visual_reason = self.visual(
            passage, start_ms=start_ms, end_ms=end_ms, speaker_turns=speaker_turns
        )
        return ScoreBreakdown(
            hook=hook,
            curiosity=curiosity,
            emotion=emotion,
            story=story,
            value=value,
            share=share,
            standalone=standalone,
            visual=visual,
            reasons={
                "hook": hook_reason,
                "curiosity": curiosity_reason,
                "emotion": emotion_reason,
                "story": story_reason,
                "value": value_reason,
                "share": share_reason,
                "standalone": standalone_reason,
                "visual": visual_reason,
            },
        )


def categorise(scores: ScoreBreakdown, passage: str) -> tuple[str, list[str]]:
    """Primary category + secondary tags, derived from the same evidence."""
    ranked = sorted(
        (
            ("EDUCATIONAL", scores.value),
            ("STORY", scores.story),
            ("EMOTIONAL", scores.emotion),
            ("CONTROVERSIAL", min(100.0, count_marker(passage, CONTROVERSY_MARKERS)[1] * 45)),
            ("HOOK", scores.hook),
            ("SURPRISING", scores.curiosity),
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    primary = ranked[0][0] if ranked[0][1] > 0 else "HOOK"

    tags: list[str] = []
    if count_marker(passage, CONTROVERSY_MARKERS)[0]:
        tags.append("Controversial")
    if LAUGHTER_RE.search(passage.lower()):
        tags.append("Funny")
    if MONEY_RE.search(passage):
        tags.append("Money")
    if is_question(_opening_line(passage)):
        tags.append("Question")
    if IMPERATIVE_RE.search(passage):
        tags.append("Actionable")
    if any(marker in normalise(passage) for marker in ("business", "startup", "company", "revenue", "founder", "customers")):
        tags.append("Business")
    if any(marker in normalise(passage) for marker in ("code", "api", "engineer", "developer", "system", "database", "algorithm")):
        tags.append("Technical")
    if scores.share >= 65:
        tags.append("Shareable")
    return primary, tags[:5]
