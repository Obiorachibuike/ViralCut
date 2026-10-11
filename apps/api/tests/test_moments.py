"""Moment discovery: candidate generation, scoring, boundaries, dedupe, ranking.

The fixture transcript is a synthetic 20-minute podcast with *deliberately
planted* strong moments (a failure story, a bold claim, an actionable list, an
argument, an emotional beat) surrounded by filler. The tests assert the engine
surfaces the planted moments and ranks them above the filler — which only works
if the scoring is genuinely reading content.
"""

from __future__ import annotations

import pytest

from moments.boundaries import (
    Boundary,
    apply_padding,
    build_boundary,
    ends_mid_sentence,
    extend_to_sentence_end,
    include_context_segment,
    needs_prior_context,
    snap_end_to_segment,
    snap_start_to_segment,
    word_boundary_ms,
)
from moments.candidates import CandidateOptions, generate_candidates, target_for_duration
from moments.dedupe import dedupe, find_clusters, overlap_ratio
from moments.discover import DiscoverOptions, derive_title, discover_moments
from moments.embeddings import HashingEmbedder, cosine_similarity
from moments.rank import RankOptions, rank_moments
from moments.scoring import (
    DEFAULT_WEIGHTS,
    MomentScorer,
    ScoringContext,
    SceneSpan,
    final_score,
    validate_weights,
)
from tests.fixtures.transcript import build_podcast_transcript, planted_moments

# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------


def test_default_weights_match_the_spec():
    assert DEFAULT_WEIGHTS["hook"] == 0.20
    assert DEFAULT_WEIGHTS["curiosity"] == 0.15
    assert DEFAULT_WEIGHTS["emotion"] == 0.15
    assert DEFAULT_WEIGHTS["story"] == 0.15
    assert DEFAULT_WEIGHTS["value"] == 0.15
    assert DEFAULT_WEIGHTS["share"] == 0.10
    assert DEFAULT_WEIGHTS["standalone"] == 0.05
    assert DEFAULT_WEIGHTS["visual"] == 0.05
    assert abs(sum(DEFAULT_WEIGHTS.values()) - 1.0) < 1e-9


def test_weights_are_renormalised():
    merged = validate_weights({"hook": 0.5, "curiosity": 0.5, "emotion": 0, "story": 0,
                               "value": 0, "share": 0, "standalone": 0, "visual": 0})
    assert abs(sum(merged.values()) - 1.0) < 1e-6
    assert merged["hook"] == pytest.approx(0.5)


def test_partial_weights_keep_the_other_defaults():
    merged = validate_weights({"hook": 0.4})
    assert merged["hook"] > DEFAULT_WEIGHTS["hook"]
    assert merged["emotion"] > 0


def test_unknown_dimension_is_rejected():
    with pytest.raises(ValueError, match="unknown scoring dimension"):
        validate_weights({"virality": 0.5})


def test_all_zero_weights_are_rejected():
    with pytest.raises(ValueError, match="must not all be zero"):
        validate_weights({k: 0 for k in DEFAULT_WEIGHTS})


def test_final_score_is_the_weighted_sum():
    scores = {k: 50.0 for k in DEFAULT_WEIGHTS}
    assert final_score(scores) == 50.0
    boosted = {**scores, "hook": 100.0}
    assert final_score(boosted) == pytest.approx(50.0 + 0.20 * 50.0, abs=0.01)


def test_final_score_clamps_to_100():
    assert final_score({k: 500.0 for k in DEFAULT_WEIGHTS}) == 100.0


# ---------------------------------------------------------------------------
# Scoring signals respond to content, not to length alone
# ---------------------------------------------------------------------------

SCORER = MomentScorer(context=ScoringContext(median_words_per_second=2.6))


def test_hook_marker_outranks_a_bland_opener():
    strong = "The biggest mistake I made was hiring too quickly, and it nearly killed the company."
    bland = "So yeah, we were talking a bit about, you know, some of the stuff around the team."
    assert SCORER.hook(strong)[0] > SCORER.hook(bland)[0]


def test_filler_opener_is_penalised():
    filler = "Um, so, like, you know, I think that maybe we should probably consider that."
    clean = "Hiring too quickly nearly killed the company."
    assert SCORER.hook(filler)[0] < SCORER.hook(clean)[0]


def test_question_opener_scores_as_a_hook():
    assert SCORER.hook("Why do most startups die in year two?")[0] > SCORER.hook(
        "We discussed the second year of the company."
    )[0]


def test_curiosity_detects_open_loops():
    looping = "And then something happened that I did not expect at all. The crazy part? It was my own fault."
    flat = "The quarterly numbers were roughly in line with what we had planned for."
    assert SCORER.curiosity(looping)[0] > SCORER.curiosity(flat)[0]


def test_emotion_detects_affect_and_swings():
    intense = "I was devastated. I cried in the car park. I was furious and completely humiliated!"
    neutral = "The report was filed on Tuesday and reviewed by the committee."
    assert SCORER.emotion(intense)[0] > SCORER.emotion(neutral)[0] + 20


def test_laughter_counts_as_emotion():
    assert SCORER.emotion("That was hilarious hahaha I could not stop laughing")[0] > 40


def test_story_rewards_narrative_markers():
    narrative = (
        "I remember the day my father handed me the keys. Back then we had nothing. "
        "One day the bank called, and at that moment I understood what risk actually means. "
        "In the end we paid every cent back."
    )
    expository = "Revenue recognition follows the accrual basis under the current standard."
    assert SCORER.story(narrative)[0] > SCORER.story(expository)[0]


def test_value_rewards_actionable_content():
    actionable = (
        "Here's how to fix it. Step one, write down the three things that actually move revenue. "
        "Step two, cut everything else for 30 days. Make sure you track one number every Monday."
    )
    vague = "Things are kind of complicated in that area, generally speaking, you know."
    assert SCORER.value(actionable)[0] > SCORER.value(vague)[0]


def test_share_rewards_controversy_and_concreteness():
    spicy = "That advice is a scam. I completely disagree with it, and you're wrong if you follow it. It cost me $40,000."
    mild = "There are a few considerations that might be worth thinking about at some point."
    assert SCORER.share(spicy)[0] > SCORER.share(mild)[0]


def test_standalone_penalises_dangling_references():
    dangling = "As I said earlier, like I mentioned, that thing I talked about is going back to the previous point."
    self_contained = "Hiring before you have revenue is the most expensive mistake a founder can make."
    assert SCORER.standalone(self_contained)[0] > SCORER.standalone(dangling)[0]


def test_visual_uses_real_scene_cuts_not_text():
    """Same text, different scene lists -> different visual score."""
    text = "Here is the framework we used to fix onboarding in thirty days."
    calm = MomentScorer(context=ScoringContext(
        scenes=[SceneSpan(0, 20_000, 30.0), SceneSpan(20_000, 40_000, 30.0), SceneSpan(40_000, 60_000, 30.0)]
    ))
    strobe = MomentScorer(context=ScoringContext(
        scenes=[SceneSpan(i * 1_000, (i + 1) * 1_000, 30.0) for i in range(60)]
    ))
    silent = MomentScorer(context=ScoringContext(scenes=[]))
    assert calm.visual(text, start_ms=0, end_ms=60_000)[0] > strobe.visual(
        text, start_ms=0, end_ms=60_000
    )[0]
    assert silent.visual(text, start_ms=0, end_ms=60_000)[0] < 60


def test_scores_are_deterministic():
    text = "The biggest mistake I made was hiring too quickly."
    assert SCORER.score(text, start_ms=0, end_ms=40_000).as_dict() == SCORER.score(
        text, start_ms=0, end_ms=40_000
    ).as_dict()


def test_different_content_produces_different_scores():
    """Guards against a constant 'AI score'."""
    a = SCORER.score("The biggest mistake I made was hiring too quickly.", start_ms=0, end_ms=40_000).as_dict()
    b = SCORER.score("The quarterly filing was submitted on schedule.", start_ms=0, end_ms=40_000).as_dict()
    assert a != b


# ---------------------------------------------------------------------------
# Candidate count scaling (spec 14)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "seconds,low,high",
    [(20 * 60, 15, 30), (60 * 60, 30, 80), (120 * 60, 50, 120)],
)
def test_candidate_target_scales_with_duration(seconds, low, high):
    assert low <= target_for_duration(seconds) <= high


# ---------------------------------------------------------------------------
# Boundaries (spec 16)
# ---------------------------------------------------------------------------


def test_ends_mid_sentence_detects_incomplete_tails():
    assert ends_mid_sentence("and then we decided that we should") is True
    assert ends_mid_sentence("That was the moment everything changed.") is False


def test_snap_start_never_lands_inside_a_segment():
    transcript = build_podcast_transcript()
    segments = transcript.segments
    mid = segments[5].start_ms + 400
    snapped, moved = snap_start_to_segment(segments, mid)
    assert snapped == segments[5].start_ms
    assert moved is True


def test_snap_end_lands_on_a_segment_end():
    transcript = build_podcast_transcript()
    segments = transcript.segments
    mid = segments[7].start_ms + 300
    snapped, _ = snap_end_to_segment(segments, mid)
    assert snapped == segments[7].end_ms


def test_extend_to_sentence_end_moves_forward():
    transcript = build_podcast_transcript()
    segments = transcript.segments
    target = segments[10].start_ms + 200  # deliberately mid-segment
    extended, _ = extend_to_sentence_end(segments, target)
    assert extended >= segments[10].end_ms


def test_padding_respects_the_configured_bounds():
    transcript = build_podcast_transcript()
    segments = transcript.segments
    start, end = segments[20].start_ms, segments[30].end_ms
    boundary = build_boundary(
        segments, start, end, pad_before_ms=2000, pad_after_ms=2000,
        transcript_start_ms=segments[0].start_ms, transcript_end_ms=segments[-1].end_ms,
    )
    # Padding snaps to the nearest word edge so a caption never starts half a
    # word, so the realised pad can slightly exceed the nominal request.
    assert boundary.pad_before_ms <= 2000 + 600
    assert boundary.pad_after_ms <= 2000 + 600
    assert boundary.pad_before_ms > 0 or boundary.pad_after_ms > 0
    assert boundary.start_ms <= start
    assert boundary.end_ms >= end


def test_padding_never_exceeds_the_media_end():
    transcript = build_podcast_transcript()
    segments = transcript.segments
    last = segments[-1]
    boundary = build_boundary(
        segments, last.start_ms - 30_000, last.end_ms,
        pad_after_ms=5000, transcript_end_ms=last.end_ms,
    )
    assert boundary.end_ms <= last.end_ms


def test_needs_prior_context_flags_dependent_openers():
    assert needs_prior_context("as I said before, the numbers were fine") is True
    assert needs_prior_context("it was the worst quarter we had") is True
    assert needs_prior_context("Hiring too early nearly killed us") is False


def test_include_context_segment_pulls_in_setup():
    transcript = build_podcast_transcript()
    segments = transcript.segments
    # Find a segment whose text starts with a dependent reference.
    index = next(
        i for i, s in enumerate(segments)
        if needs_prior_context(s.text) and i > 0
    )
    assert include_context_segment(segments, index) == index - 1


def test_word_boundary_snapping_uses_real_word_timings():
    transcript = build_podcast_transcript()
    segments = [s for s in transcript.segments if s.words]
    assert segments, "fixture must carry word-level timings"
    seg = segments[10]
    middle_word = seg.words[len(seg.words) // 2]
    back = word_boundary_ms([seg], middle_word.start_ms + 120, direction="back")
    assert back == middle_word.start_ms
    forward = word_boundary_ms([seg], middle_word.end_ms - 120, direction="forward")
    assert forward == middle_word.end_ms


def test_build_boundary_rejects_inverted_range():
    with pytest.raises(ValueError, match="end_ms must be greater"):
        build_boundary([], 5000, 5000)


# ---------------------------------------------------------------------------
# Candidate generation + discovery
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def transcript():
    return build_podcast_transcript()


@pytest.fixture(scope="module")
def scenes():
    """A scene list with a hard cut inside the story moment."""
    return [(0, 90_000, 25.0), (90_000, 200_000, 55.0), (200_000, 600_000, 20.0),
            (600_000, 900_000, 30.0), (900_000, 1_200_000, 22.0)]


def test_candidates_are_generated(transcript, scenes):
    from moments.candidates import build_context

    scorer = MomentScorer(context=build_context(transcript, scenes))
    candidates = generate_candidates(
        transcript,
        scorer=scorer,
        options=CandidateOptions(min_duration_ms=20_000, max_duration_ms=120_000),
    )
    assert len(candidates) > 10


def test_every_candidate_respects_the_duration_limits(transcript, scenes):
    from moments.candidates import build_context

    scorer = MomentScorer(context=build_context(transcript, scenes))
    candidates = generate_candidates(
        transcript,
        scorer=scorer,
        options=CandidateOptions(min_duration_ms=20_000, max_duration_ms=120_000),
    )
    for candidate in candidates:
        assert 20_000 <= candidate.duration_ms <= 120_000


def test_discovery_finds_a_meaningful_number_of_moments(transcript, scenes):
    result = discover_moments(transcript, scenes=scenes, options=DiscoverOptions())
    assert result.candidate_count >= 20
    assert len(result.moments) >= 8
    assert result.cluster_count <= result.candidate_count


def test_planted_strong_moments_outrank_the_filler(transcript, scenes):
    """The core product promise: the interesting parts come out on top."""
    result = discover_moments(transcript, scenes=scenes, options=DiscoverOptions(limit=25))
    assert result.moments, "discovery returned nothing"

    planted = planted_moments()
    top_starts = [m.start_ms for m in result.moments[:10]]

    hits = 0
    for label, start_ms, _end_ms in planted:
        if any(abs(start - start_ms) <= 25_000 for start in top_starts):
            hits += 1
    assert hits >= 3, (
        f"only {hits}/{len(planted)} planted moments reached the top 10; "
        f"planted={[p[0] for p in planted]}, top_starts={top_starts}"
    )


def test_filler_passage_is_not_a_top_moment(transcript, scenes):
    result = discover_moments(transcript, scenes=scenes, options=DiscoverOptions(limit=50))
    filler_starts = [p[1] for p in planted_moments() if p[0] == "filler"]
    top_three = result.moments[:3]
    for moment in top_three:
        for start in filler_starts:
            assert abs(moment.start_ms - start) > 20_000, "filler outranked real content"


def test_ranks_are_contiguous_and_score_ordered(transcript, scenes):
    result = discover_moments(transcript, scenes=scenes, options=DiscoverOptions())
    ranks = [m.rank for m in result.moments]
    assert ranks == list(range(1, len(ranks) + 1))
    scores = [m.final for m in result.moments]
    assert scores == sorted(scores, reverse=True)


def test_scores_are_in_range(transcript, scenes):
    result = discover_moments(transcript, scenes=scenes, options=DiscoverOptions())
    for moment in result.moments:
        for value in moment.scores.as_dict().values():
            assert 0 <= value <= 100
        assert 0 <= moment.final <= 100


def test_every_moment_has_a_title_and_hooks(transcript, scenes):
    result = discover_moments(transcript, scenes=scenes, options=DiscoverOptions())
    for moment in result.moments:
        assert moment.title and len(moment.title) <= 72
        assert moment.hook_options
        assert moment.summary


def test_category_filter_limits_results(transcript, scenes):
    result = discover_moments(
        transcript, scenes=scenes, options=DiscoverOptions(categories=("EDUCATIONAL",))
    )
    assert all(m.category == "EDUCATIONAL" for m in result.moments)


def test_min_score_filter_is_applied(transcript, scenes):
    unfiltered = discover_moments(transcript, scenes=scenes, options=DiscoverOptions())
    filtered = discover_moments(
        transcript, scenes=scenes, options=DiscoverOptions(min_score=70.0)
    )
    assert len(filtered.moments) <= len(unfiltered.moments)
    assert all(m.final >= 70.0 for m in filtered.moments)


def test_weights_change_the_ranking(transcript, scenes):
    hook_heavy = discover_moments(
        transcript, scenes=scenes,
        options=DiscoverOptions(weights={"hook": 0.9, "curiosity": 0.02, "emotion": 0.02,
                                         "story": 0.02, "value": 0.02, "share": 0.01,
                                         "standalone": 0.005, "visual": 0.005}),
    )
    value_heavy = discover_moments(
        transcript, scenes=scenes,
        options=DiscoverOptions(weights={"hook": 0.02, "curiosity": 0.02, "emotion": 0.02,
                                         "story": 0.02, "value": 0.9, "share": 0.01,
                                         "standalone": 0.005, "visual": 0.005}),
    )
    assert hook_heavy.moments and value_heavy.moments
    assert hook_heavy.moments[0].start_ms != value_heavy.moments[0].start_ms or (
        hook_heavy.moments[0].final != value_heavy.moments[0].final
    )


def test_padding_is_recorded_on_the_moment(transcript, scenes):
    result = discover_moments(
        transcript, scenes=scenes,
        options=DiscoverOptions(pad_before_s=2.0, pad_after_s=2.0),
    )
    assert any(m.pad_before_ms > 0 or m.pad_after_ms > 0 for m in result.moments)


def test_result_serialises_with_millisecond_timestamps(transcript, scenes):
    payload = discover_moments(transcript, scenes=scenes, options=DiscoverOptions()).to_dict()
    assert payload["candidateCount"] > 0
    first = payload["moments"][0]
    assert first["startMs"] < first["endMs"]
    assert set(first["scores"]) == {
        "hook", "curiosity", "emotion", "story", "value", "share", "standalone", "visual"
    }
    assert first["transcriptExcerpt"]


# ---------------------------------------------------------------------------
# Duplicate detection (spec 17)
# ---------------------------------------------------------------------------


def test_near_duplicate_texts_are_detected():
    embedder = HashingEmbedder()
    a = embedder.embed("the biggest mistake founders make is hiring before they have revenue")
    b = embedder.embed("the biggest mistake that founders make is hiring before having revenue")
    c = embedder.embed("here is how to structure your onboarding checklist for new engineers")
    assert cosine_similarity(a, b) > cosine_similarity(a, c)
    assert cosine_similarity(a, b) > 0.6


def test_embeddings_are_normalised():
    import numpy as np

    embedder = HashingEmbedder()
    vector = embedder.embed("some reasonably long passage about business strategy")
    assert np.linalg.norm(vector) == pytest.approx(1.0, abs=1e-4)


def test_dedupe_collapses_overlapping_candidates():
    from moments.candidates import Candidate
    from moments.scoring import ScoreBreakdown

    def make(start, end, text, score):
        return Candidate(
            start_ms=start, end_ms=end, start_index=0, end_index=1, text=text,
            scores=ScoreBreakdown(*([score] * 8)), final=score, category="HOOK", tags=[],
        )

    candidates = [
        make(0, 60_000, "the biggest mistake founders make is hiring before they have revenue", 80.0),
        make(2_000, 62_000, "the biggest mistake founders make is hiring before they have revenue", 70.0),
        make(5_000, 65_000, "the biggest mistake founders make is hiring before they have revenue", 90.0),
        make(300_000, 360_000, "here is how to structure the onboarding checklist for engineers", 60.0),
    ]
    survivors, clusters = dedupe(candidates, embedder=HashingEmbedder(), threshold=0.7)
    assert len(clusters) == 2
    assert len(survivors) == 2
    # The strongest member of the duplicate cluster is the one kept.
    kept_starts = {s.start_ms for s in survivors}
    assert 5_000 in kept_starts
    assert 300_000 in kept_starts


def test_dedupe_marks_losers_when_requested():
    from moments.candidates import Candidate
    from moments.scoring import ScoreBreakdown

    def make(start, end, text, score):
        return Candidate(
            start_ms=start, end_ms=end, start_index=0, end_index=1, text=text,
            scores=ScoreBreakdown(*([score] * 8)), final=score, category="HOOK", tags=[],
        )

    candidates = [
        make(0, 60_000, "identical passage about hiring mistakes and revenue", 80.0),
        make(1_000, 61_000, "identical passage about hiring mistakes and revenue", 60.0),
    ]
    survivors, _ = dedupe(candidates, embedder=HashingEmbedder(), threshold=0.6, keep_losers=True)
    assert len(survivors) == 2
    assert sum(1 for s in survivors if s.is_cluster_best) == 1
    assert len({s.cluster_id for s in survivors}) == 1


def test_overlap_ratio():
    assert overlap_ratio(0, 100, 0, 100) == 1.0
    assert overlap_ratio(0, 100, 200, 300) == 0.0
    assert overlap_ratio(0, 100, 50, 150) == 0.5


def test_empty_input_is_handled():
    assert dedupe([]) == ([], [])
    assert find_clusters([])[0] == []


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def _candidate(start, end, score, category="HOOK"):
    from moments.candidates import Candidate
    from moments.scoring import ScoreBreakdown

    return Candidate(
        start_ms=start, end_ms=end, start_index=0, end_index=1, text="x",
        scores=ScoreBreakdown(*([score] * 8)), final=0.0, category=category, tags=[],
    )


def test_rank_orders_by_final_score():
    ranked = rank_moments([_candidate(0, 1000, 0), _candidate(2000, 3000, 0), _candidate(4000, 5000, 0)])
    assert [c.rank for c in ranked] == [1, 2, 3]


def test_rank_drops_nested_moments():
    outer = _candidate(0, 100_000, 0)
    inner = _candidate(1_000, 50_000, 0)
    ranked = rank_moments([outer, inner], options=RankOptions(drop_nested=True))
    assert len(ranked) == 1


def test_rank_keeps_nested_when_disabled():
    outer = _candidate(0, 100_000, 0)
    inner = _candidate(1_000, 50_000, 0)
    ranked = rank_moments([outer, inner], options=RankOptions(drop_nested=False))
    assert len(ranked) == 2


def test_rank_limit_is_applied():
    ranked = rank_moments(
        [_candidate(i * 200_000, i * 200_000 + 60_000, 0) for i in range(10)],
        options=RankOptions(limit=3),
    )
    assert len(ranked) == 3


def test_derive_title_is_bounded():
    from moments.candidates import Candidate
    from moments.scoring import ScoreBreakdown

    long_text = "This is an extremely long sentence that keeps going and going and going well past any sane title length for a short form video platform"
    candidate = Candidate(
        start_ms=0, end_ms=60_000, start_index=0, end_index=1, text=long_text,
        scores=ScoreBreakdown(*([50.0] * 8)), final=50.0, category="HOOK", tags=[],
    )
    title = derive_title(candidate)
    assert len(title) <= 72
