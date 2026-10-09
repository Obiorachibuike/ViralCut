"""Moment discovery — the whole deterministic pipeline in one call.

    transcript + scenes  ->  candidates  ->  score  ->  dedupe  ->  rank

This runs with no network and no LLM. When an LLM is configured,
`ai.analysis.MomentAnalyzer` refines the output of this stage; it never replaces
the evidence collected here.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from moments.candidates import Candidate, CandidateOptions, build_context, generate_candidates
from moments.dedupe import dedupe
from moments.embeddings import Embedder, get_embedder
from moments.rank import RankOptions, rank_moments
from moments.scoring import DEFAULT_WEIGHTS, MomentScorer, validate_weights
from moments.text import normalise, word_count
from transcription.base import Transcript

logger = logging.getLogger("viralcut.moments.discover")


@dataclass(slots=True)
class DiscoverOptions:
    max_candidates: int | None = None
    min_score: float = 0.0
    min_duration_s: float = 20.0
    max_duration_s: float = 120.0
    pad_before_s: float = 0.0
    pad_after_s: float = 0.0
    categories: tuple[str, ...] | None = None
    weights: dict[str, float] | None = None
    dedupe_threshold: float = 0.72
    limit: int | None = None

    def candidate_options(self) -> CandidateOptions:
        return CandidateOptions(
            min_duration_ms=int(self.min_duration_s * 1000),
            max_duration_ms=int(self.max_duration_s * 1000),
            pad_before_ms=int(self.pad_before_s * 1000),
            pad_after_ms=int(self.pad_after_s * 1000),
            target_count=self.max_candidates,
        )

    def rank_options(self) -> RankOptions:
        return RankOptions(
            min_score=self.min_score,
            limit=self.limit,
            categories=self.categories,
        )


@dataclass(slots=True)
class DiscoveryResult:
    moments: list[Candidate] = field(default_factory=list)
    candidate_count: int = 0
    cluster_count: int = 0
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    llm_refined: bool = False
    engine: str = "deterministic"
    prompt_version: str | None = None
    model: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidateCount": self.candidate_count,
            "clusterCount": self.cluster_count,
            "weights": self.weights,
            "llmRefined": self.llm_refined,
            "engine": self.engine,
            "promptVersion": self.prompt_version,
            "model": self.model,
            "moments": [
                {
                    "rank": m.rank,
                    "startMs": m.start_ms,
                    "endMs": m.end_ms,
                    "padBeforeMs": m.pad_before_ms,
                    "padAfterMs": m.pad_after_ms,
                    "title": m.title,
                    "summary": m.summary,
                    "transcriptExcerpt": m.excerpt(),
                    "category": m.category,
                    "categories": m.tags,
                    "tags": m.tags,
                    "scores": m.scores.as_dict(),
                    "scoreReasons": m.scores.reasons,
                    "finalScore": m.final,
                    "clusterId": m.cluster_id,
                    "isClusterBest": m.is_cluster_best,
                    "clusterSize": m.cluster_size,
                    "speakerTurns": m.speaker_turns,
                    "primarySpeaker": _primary_speaker(m),
                    "hookOptions": m.hook_options,
                    "titleOptions": m.title_options,
                }
                for m in self.moments
            ]
        }


def _primary_speaker(candidate: Candidate) -> str | None:
    tally: dict[str, int] = {}
    for segment in candidate.segments:
        if segment.speaker:
            tally[segment.speaker] = tally.get(segment.speaker, 0) + segment.duration_ms
    if not tally:
        return None
    return max(tally.items(), key=lambda item: item[1])[0]


_TITLE_TRIM_RE = re.compile(r"[\s\-–—:,.!?]+$")


def derive_title(candidate: Candidate) -> str:
    """Deterministic title fallback used when no LLM is configured.

    Built from the passage itself: the strongest marker sentence, shortened.
    """
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", candidate.text) if s.strip()]
    if not sentences:
        return f"Moment at {candidate.start_ms // 1000}s"

    def strength(sentence: str) -> float:
        from moments.text import (
            CURIOSITY_MARKERS,
            EMOTION_WORDS,
            HOOK_MARKERS,
            VALUE_MARKERS,
            count_marker,
            count_words,
        )

        score = 0.0
        score += count_marker(sentence, HOOK_MARKERS)[1] * 3
        score += count_marker(sentence, CURIOSITY_MARKERS)[1] * 2
        score += count_marker(sentence, VALUE_MARKERS)[1] * 1.5
        score += count_words(sentence, EMOTION_WORDS)[1] * 1.5
        words = word_count(sentence)
        if 4 <= words <= 14:
            score += 2
        elif words > 22:
            score -= 2
        return score

    best = max(sentences[:6], key=strength)
    title = _TITLE_TRIM_RE.sub("", best)
    if len(title) > 70:
        cut = title[:70]
        if " " in cut:
            cut = cut[: cut.rfind(" ")]
        title = _TITLE_TRIM_RE.sub("", cut) + "…"
    return title or f"Moment at {candidate.start_ms // 1000}s"


def derive_summary(candidate: Candidate, limit: int = 180) -> str:
    text = " ".join(candidate.text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,;:") + "…"


def derive_hooks(candidate: Candidate) -> list[str]:
    """Three hook angles, derived from the passage (no fabrication)."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", candidate.text) if s.strip()]
    hooks: list[str] = []
    for sentence in sentences[:4]:
        if 4 <= word_count(sentence) <= 20:
            hooks.append(_TITLE_TRIM_RE.sub("", sentence))
        if len(hooks) >= 3:
            break
    while len(hooks) < 3:
        fallback = candidate.excerpt(90)
        if fallback in hooks:
            break
        hooks.append(fallback)
    return hooks[:3]


def discover_moments(
    transcript: Transcript,
    *,
    scenes: list[tuple[int, int, float | None]] | None = None,
    options: DiscoverOptions | None = None,
    embedder: Embedder | None = None,
) -> DiscoveryResult:
    options = options or DiscoverOptions()
    scenes = scenes or []

    weights = validate_weights(options.weights)
    context = build_context(transcript, scenes)
    scorer = MomentScorer(context=context)

    raw = generate_candidates(
        transcript, scorer=scorer, options=options.candidate_options()
    )
    if not raw:
        return DiscoveryResult(
            candidate_count=0,
            cluster_count=0,
            weights=weights,
        )

    # Score first so dedupe can promote the strongest member of each cluster.
    for candidate in raw:
        candidate.final = _weighted(candidate, weights)

    survivors, clusters = dedupe(
        raw,
        embedder=embedder or get_embedder(),
        threshold=options.dedupe_threshold,
    )
    ranked = rank_moments(survivors, weights=weights, options=options.rank_options())

    for candidate in ranked:
        candidate.title = derive_title(candidate)
        candidate.summary = derive_summary(candidate)
        candidate.hook_options = derive_hooks(candidate)
        candidate.title_options = [candidate.title]

    logger.info(
        "discovered %d moments from %d candidates in %d clusters",
        len(ranked),
        len(raw),
        len(clusters),
    )
    return DiscoveryResult(
        moments=ranked,
        candidate_count=len(raw),
        cluster_count=len(clusters),
        weights=weights,
        engine="deterministic",
    )


def _weighted(candidate: Candidate, weights: dict[str, float]) -> float:
    from moments.scoring import final_score

    return final_score(candidate.scores.as_dict(), weights)
