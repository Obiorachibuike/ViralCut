"""Synthetic-but-realistic podcast transcript used by the moment-discovery tests.

About 20 minutes of a two-host business podcast. Six passages are deliberately
strong (a failure story, a bold claim, an actionable list, an argument, an
emotional beat, a surprising reveal); the rest is the kind of filler real
podcasts are full of, generated from a seeded pool so the fixture is
deterministic. Word-level timings are synthesised at a natural speaking rate so
the boundary and caption code paths exercise realistic data shapes.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from transcription.base import Segment, Transcript, Word

WORDS_PER_SECOND = 2.6
GAP_MS = 260  # natural pause between segments
TARGET_DURATION_MS = 20 * 60 * 1000

FILLER_POOL: list[tuple[str, str]] = [
    ("Yeah, that is a fair point, and I think it comes up more than people realise.", "SPEAKER_00"),
    ("Right, and the other thing about that is the timing, which always seems to be off.", "SPEAKER_01"),
    ("So we were sort of going back and forth on it for a while before anything changed.", "SPEAKER_00"),
    ("I mean, generally speaking, it depends on the team you have in front of you.", "SPEAKER_01"),
    ("Um, I think the short version is that it took longer than we expected.", "SPEAKER_00"),
    ("And then there was the whole thing with the vendors, which was its own saga.", "SPEAKER_01"),
    ("Yeah, that part was, you know, not exactly fun at the time.", "SPEAKER_00"),
    ("Sure, sure. Although I would push back slightly on the framing there.", "SPEAKER_01"),
    ("It is one of those things where you only notice it in hindsight, honestly.", "SPEAKER_00"),
    ("Which is annoying, but I suppose that is how most of this works.", "SPEAKER_01"),
    ("We had a meeting about it, and then another meeting about the first meeting.", "SPEAKER_00"),
    ("That is very true. The paperwork alone took about three weeks.", "SPEAKER_01"),
    ("Anyway, that is roughly where things landed by the end of the quarter.", "SPEAKER_00"),
    ("I think most people would agree with that, at least in principle.", "SPEAKER_01"),
    ("In practice though, it is a bit messier than it sounds on a call like this.", "SPEAKER_00"),
    ("Yeah. And the numbers moved around quite a lot between the two reviews.", "SPEAKER_01"),
    ("Which is, I guess, the part that frustrated the board the most.", "SPEAKER_00"),
    ("So we ended up just picking a date and committing to it publicly.", "SPEAKER_01"),
    ("That helped, actually. Once it was written down people stopped arguing.", "SPEAKER_00"),
    ("Although there was still a fair amount of noise in the first two weeks.", "SPEAKER_01"),
    ("I remember someone asking about it in the all hands, which was fun.", "SPEAKER_00"),
    ("Right, and the answer at the time was basically that we did not know yet.", "SPEAKER_01"),
    ("Which is an honest answer, even if it is not a satisfying one.", "SPEAKER_00"),
    ("Definitely. And looking back I would probably have said it sooner.", "SPEAKER_01"),
    ("There is also the question of who owns it, which nobody wanted to touch.", "SPEAKER_00"),
    ("Yeah, ownership was the awkward part of the whole exercise.", "SPEAKER_01"),
    ("So it sat there for a while, which is usually how these things go.", "SPEAKER_00"),
    ("Until somebody just decided to pick it up and run with it.", "SPEAKER_01"),
    ("And to their credit it worked out, more or less.", "SPEAKER_00"),
    ("More or less is doing a lot of work in that sentence.", "SPEAKER_01"),
    ("Ha, fair enough. It was not a clean landing by any means.", "SPEAKER_00"),
    ("But you take those wins where you can get them in that situation.", "SPEAKER_01"),
    ("Absolutely. And the team knew it, which I think mattered more than the result.", "SPEAKER_00"),
    ("That is a good way to put it. People notice when you pretend otherwise.", "SPEAKER_01"),
    ("Right. So we kept going, and the next quarter was calmer.", "SPEAKER_00"),
    ("Calmer is a generous word for it, but yes, less fire.", "SPEAKER_01"),
    ("I will take less fire. Less fire is the goal for the year.", "SPEAKER_00"),
    ("Same. Although I suspect the year has other plans for us.", "SPEAKER_01"),
    ("It usually does. Anyway, where were we before that tangent.", "SPEAKER_00"),
    ("Somewhere around the hiring plan, I think, if I remember correctly.", "SPEAKER_01"),
]

_STRONG_BLOCKS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "failure_story",
        [
            ("I almost lost the company in 2019, and I have never told the whole story publicly.", "SPEAKER_01"),
            ("I remember the exact moment. I was sitting in the car park outside the bank, and I could not make myself go in.", "SPEAKER_01"),
            ("We had eleven people on payroll and about nine thousand dollars left in the account.", "SPEAKER_01"),
            ("That morning I had to call my father and ask him for money, and I was thirty eight years old.", "SPEAKER_01"),
            ("I was devastated. I actually cried in that car park, which is not something I had done since I was a kid.", "SPEAKER_01"),
            ("And the worst part was that I knew exactly which decision had put us there, and I had made it eighteen months earlier.", "SPEAKER_01"),
            ("I had hired four senior people in one quarter because the pipeline looked amazing, and the pipeline was a lie.", "SPEAKER_01"),
            ("In the end we survived, but only because I let five people go, and that was the hardest week of my life.", "SPEAKER_01"),
        ],
    ),
    (
        "bold_claim",
        [
            ("Here is an unpopular opinion. Most productivity advice is actively destroying people's careers.", "SPEAKER_01"),
            ("I completely disagree with the entire five AM hustle culture, and I think it is a scam being sold to young people.", "SPEAKER_01"),
            ("You are wrong if you think waking up earlier will fix a strategy problem. It will not. It never has.", "SPEAKER_01"),
            ("The companies I have watched win did it by saying no to eighty percent of their roadmap, not by working longer hours.", "SPEAKER_01"),
            ("People will hate this, but most of what fills your calendar this week will not matter in six months.", "SPEAKER_01"),
        ],
    ),
    (
        "actionable_list",
        [
            ("Here is how we fixed onboarding, and it took about thirty days start to finish.", "SPEAKER_01"),
            ("Step one, write down the three tasks that actually generate revenue, and only three.", "SPEAKER_01"),
            ("Step two, every new hire shadows one of those three tasks in their first week, no exceptions.", "SPEAKER_01"),
            ("Step three, cut every recurring meeting that does not produce a written decision at the end of it.", "SPEAKER_01"),
            ("Make sure you track one number every single Monday, and put it somewhere the whole team can see it.", "SPEAKER_01"),
            ("If you do those three things for four weeks, your onboarding problem usually turns out to be a clarity problem.", "SPEAKER_01"),
        ],
    ),
    (
        "argument",
        [
            ("Wait, no, I have to push back on that completely. That is not how the data reads.", "SPEAKER_00"),
            ("You are wrong about remote work killing culture, and I will tell you why in one sentence.", "SPEAKER_01"),
            ("Culture is what you tolerate, not where you sit, and that has not changed because of a video call.", "SPEAKER_01"),
            ("No, no, no, that is a nice line but it is not true. I have watched three teams fall apart doing exactly that.", "SPEAKER_00"),
            ("Then your leaders were weak, not your policy. With all due respect, that is a leadership failure.", "SPEAKER_01"),
            ("That is a genuinely controversial thing to say to someone who watched it happen.", "SPEAKER_00"),
            ("It is controversial because it is uncomfortable, not because it is wrong.", "SPEAKER_01"),
        ],
    ),
    (
        "emotional_beat",
        [
            ("The moment I am actually proud of is not the exit, it is the Tuesday we paid everyone back.", "SPEAKER_01"),
            ("I wrote the last repayment to my father by hand because I did not trust the banking app not to fail.", "SPEAKER_01"),
            ("He called me about twenty minutes later and he just said, well done son, and then he went quiet.", "SPEAKER_01"),
            ("I sat on the kitchen floor and I was not sad, I was just completely overwhelmed with relief.", "SPEAKER_01"),
            ("That is the thing nobody tells you about surviving something like that. It does not feel like winning.", "SPEAKER_01"),
            ("It feels like putting something heavy down after carrying it for far too long.", "SPEAKER_01"),
        ],
    ),
    (
        "surprising_reveal",
        [
            ("And here is the part I did not expect. The investor who passed on us ended up applying for a job here two years later.", "SPEAKER_01"),
            ("He sent me a message saying he had been wrong about the market, not about us, and he wanted in.", "SPEAKER_01"),
            ("I said no. And I do not feel bad about it, because he had been certain at exactly the moment we needed belief.", "SPEAKER_01"),
        ],
    ),
]

_OPENING: list[tuple[str, str]] = [
    ("Hello and welcome back to another episode of the show, really glad you could join us today.", "SPEAKER_00"),
    ("Yeah thanks for having me again, it is always good to be here.", "SPEAKER_01"),
    ("So we were chatting before we hit record and, you know, just sort of catching up on stuff.", "SPEAKER_00"),
]

_CLOSING: list[tuple[str, str]] = [
    ("That is a great place to leave it, honestly. Thank you so much for coming on again.", "SPEAKER_00"),
    ("Thanks for having me. This was a good one.", "SPEAKER_01"),
    ("Same time next week, and we will see you all then. Take care everybody.", "SPEAKER_00"),
]


@dataclass(slots=True)
class Line:
    text: str
    speaker: str
    label: str  # "filler" or the planted-moment label
    start_ms: int = 0
    end_ms: int = 0


def _duration_ms(text: str, words_per_second: float) -> int:
    words = max(1, len(text.split()))
    return int(words / words_per_second * 1000)


def _build_lines(words_per_second: float = WORDS_PER_SECOND) -> list[Line]:
    """Interleave the planted moments with seeded filler until ~20 minutes."""
    rng = random.Random(20260107)
    lines: list[Line] = []

    def push(text: str, speaker: str, label: str) -> None:
        lines.append(Line(text=text, speaker=speaker, label=label))

    for text, speaker in _OPENING:
        push(text, speaker, "filler")

    # Spread the six planted moments evenly across the episode.
    gap_target = TARGET_DURATION_MS // (len(_STRONG_BLOCKS) + 1)

    for label, block in _STRONG_BLOCKS:
        filler_ms = 0
        while filler_ms < gap_target - 90_000:
            text, speaker = rng.choice(FILLER_POOL)
            push(text, speaker, "filler")
            filler_ms += _duration_ms(text, words_per_second) + GAP_MS
        for text, speaker in block:
            push(text, speaker, label)

    while True:
        total = sum(_duration_ms(l.text, words_per_second) + GAP_MS for l in lines)
        if total >= TARGET_DURATION_MS:
            break
        text, speaker = rng.choice(FILLER_POOL)
        push(text, speaker, "filler")

    for text, speaker in _CLOSING:
        push(text, speaker, "filler")

    # Assign timestamps.
    cursor = 0
    for line in lines:
        line.start_ms = cursor
        line.end_ms = cursor + _duration_ms(line.text, words_per_second)
        cursor = line.end_ms + GAP_MS
    return lines


def build_podcast_transcript(*, words_per_second: float = WORDS_PER_SECOND) -> Transcript:
    lines = _build_lines(words_per_second)
    segments: list[Segment] = []
    for index, line in enumerate(lines):
        segments.append(
            Segment(
                index=index,
                start_ms=line.start_ms,
                end_ms=line.end_ms,
                text=line.text,
                confidence=0.94,
                speaker=line.speaker,
                words=_synthesise_words(line.text, line.start_ms, line.end_ms),
            )
        )
    return Transcript(
        language="en",
        model="fixture",
        duration_ms=lines[-1].end_ms if lines else 0,
        segments=segments,
        settings={"wordsPerSecond": words_per_second},
    )


def planted_moments(*, words_per_second: float = WORDS_PER_SECOND) -> list[tuple[str, int, int]]:
    """(label, start_ms, end_ms) for every block, filler included, in order."""
    out: list[tuple[str, int, int]] = []
    current_label: str | None = None
    start = 0
    end = 0
    for line in _build_lines(words_per_second):
        if line.label != current_label:
            if current_label is not None:
                out.append((current_label, start, end))
            current_label = line.label
            start = line.start_ms
        end = line.end_ms
    if current_label is not None:
        out.append((current_label, start, end))
    return out


def strong_moment_starts() -> list[int]:
    return [start for label, start, _ in planted_moments() if label != "filler"]


def _synthesise_words(text: str, start_ms: int, end_ms: int) -> list[Word]:
    tokens = text.split()
    if not tokens:
        return []
    span = max(1, end_ms - start_ms)
    step = span / len(tokens)
    return [
        Word(text=token, start_ms=int(start_ms + i * step), end_ms=int(start_ms + (i + 1) * step))
        for i, token in enumerate(tokens)
    ]
