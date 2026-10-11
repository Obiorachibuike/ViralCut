"""Moment ranking.

Applies the configurable weights, filters, sorts, and assigns 1-based ranks.
Ranking is a pure function of the scores, so the same transcript + weights always
produce the same ordering.
"""

from __future__ import annotations

from dataclasses import dataclass

from moments.candidates import Candidate
from moments.scoring import final_score, validate_weights


@dataclass(slots=True)
class RankOptions:
    min_score: float = 0.0
    limit: int | None = None
    categories: tuple[str, ...] | None = None
    #: When True, moments that sit mostly inside an already-selected moment are
    #: dropped. Prevents the top-10 from being one long passage chopped up.
    drop_nested: bool = True
    nested_overlap_threshold: float = 0.85


def rank_moments(
    candidates: list[Candidate],
    *,
    weights: dict[str, float] | None = None,
    options: RankOptions | None = None,
) -> list[Candidate]:
    options = options or RankOptions()
    normalised = validate_weights(weights)

    for candidate in candidates:
        candidate.final = final_score(candidate.scores.as_dict(), normalised)

    filtered = [c for c in candidates if c.final >= options.min_score]
    if options.categories:
        wanted = {c.upper() for c in options.categories}
        filtered = [c for c in filtered if c.category.upper() in wanted]

    if options.drop_nested:
        filtered = _drop_nested(filtered, options.nested_overlap_threshold)

    filtered.sort(key=lambda c: (-c.final, c.start_ms))

    if options.limit is not None:
        filtered = filtered[: options.limit]

    for position, candidate in enumerate(filtered, start=1):
        candidate.rank = position
    return filtered


def _drop_nested(candidates: list[Candidate], threshold: float) -> list[Candidate]:
    """Keep the better of two moments where one is almost entirely inside the other."""
    ordered = sorted(candidates, key=lambda c: (-c.final, c.start_ms))
    kept: list[Candidate] = []
    for candidate in ordered:
        nested = False
        for existing in kept:
            start = max(candidate.start_ms, existing.start_ms)
            end = min(candidate.end_ms, existing.end_ms)
            intersection = max(0, end - start)
            span = max(1, candidate.end_ms - candidate.start_ms)
            if intersection / span >= threshold:
                nested = True
                break
        if not nested:
            kept.append(candidate)
    return kept
