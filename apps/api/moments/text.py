"""Text normalisation and lexical features used by the moment scorer.

These are deliberately transparent, testable heuristics. They run on the real
transcript — when an LLM is configured it *refines* these results, it does not
replace the evidence.
"""

from __future__ import annotations

import re
from functools import lru_cache

FILLER_WORDS = {
    "um", "uh", "erm", "ah", "like", "you know", "i mean", "sort of", "kind of",
    "basically", "actually", "literally", "right", "okay", "so yeah",
}

LAUGHTER_RE = re.compile(r"\b(?:ha){2,}\b|\bheh+\b|\[laughs?\]|\(laughs?\)|\blol\b", re.I)

QUESTION_RE = re.compile(r"\?\s*$")

HOOK_MARKERS: tuple[tuple[str, float], ...] = (
    ("biggest mistake", 1.0),
    ("nobody talks about", 1.0),
    ("nobody tells you", 1.0),
    ("no one tells you", 1.0),
    ("the truth is", 0.9),
    ("here's the thing", 0.7),
    ("here's why", 0.7),
    ("stop doing", 0.8),
    ("most people", 0.6),
    ("everyone thinks", 0.8),
    ("i was wrong", 0.9),
    ("i got fired", 1.0),
    ("i almost", 0.9),
    ("i lost", 0.8),
    ("we lost", 0.7),
    ("i quit", 0.9),
    ("the secret", 0.8),
    ("what nobody", 0.9),
    ("the real reason", 0.9),
    ("contrarian", 0.8),
    ("unpopular opinion", 1.0),
    ("hot take", 0.8),
    ("this is going to sound", 0.8),
    ("you're doing it wrong", 1.0),
    ("never do this", 0.9),
    ("don't ever", 0.8),
    ("it turns out", 0.6),
    ("what if i told you", 1.0),
    ("let me tell you", 0.5),
    ("i'll be honest", 0.7),
    ("to be honest", 0.6),
    ("here's the truth", 0.9),
)

CURIOSITY_MARKERS: tuple[tuple[str, float], ...] = (
    ("you won't believe", 1.0),
    ("you wouldn't believe", 1.0),
    ("wait, what", 1.0),
    ("how did that happen", 0.9),
    ("and then", 0.4),
    ("but here's", 0.7),
    ("the crazy part", 1.0),
    ("the weird part", 0.9),
    ("what happened next", 1.0),
    ("the twist", 0.9),
    ("plot twist", 1.0),
    ("turns out", 0.6),
    ("it gets worse", 0.9),
    ("it gets better", 0.7),
    ("that's not the", 0.7),
    ("the reason why", 0.6),
    ("i had no idea", 0.8),
    ("i didn't expect", 0.8),
    ("out of nowhere", 0.8),
    ("suddenly", 0.5),
    ("mystery", 0.6),
    ("secret", 0.6),
)

EMOTION_WORDS: dict[str, float] = {
    # high arousal positive
    "amazing": 0.7, "incredible": 0.7, "unbelievable": 0.8, "insane": 0.8, "insane!": 0.8,
    "love": 0.5, "loved": 0.5, "excited": 0.7, "thrilled": 0.8, "proud": 0.6,
    "grateful": 0.6, "beautiful": 0.5, "fantastic": 0.6, "wow": 0.7,
    # high arousal negative
    "angry": 0.8, "furious": 0.9, "furious!": 0.9, "hate": 0.8, "hated": 0.7,
    "devastated": 0.9, "heartbroken": 0.9, "cried": 0.8, "crying": 0.8, "tears": 0.7,
    "terrified": 0.9, "scared": 0.7, "afraid": 0.6, "anxious": 0.6, "panic": 0.8,
    "humiliated": 0.9, "embarrassed": 0.7, "ashamed": 0.8, "betrayed": 0.8,
    "frustrated": 0.6, "furious": 0.9, "shocked": 0.8, "shocking": 0.8,
    # low arousal negative (still counts, less)
    "sad": 0.6, "hurt": 0.6, "painful": 0.7, "difficult": 0.3, "hard": 0.2,
    "failed": 0.6, "failure": 0.6, "broke": 0.6, "bankrupt": 0.8, "lost everything": 1.0,
    # humour — a real engagement driver on short-form
    "hilarious": 0.8, "laughing": 0.7, "laughed": 0.7, "laughs": 0.6,
    "funny": 0.6, "funniest": 0.7, "joke": 0.4, "ridiculous": 0.6,
    "absurd": 0.5, "haha": 0.6,
    # inspiration
    "hope": 0.5, "hopeful": 0.5, "believe": 0.4, "changed my life": 0.9,
    "turned my life": 0.9, "second chance": 0.7, "forgive": 0.6,
}

STORY_MARKERS: tuple[tuple[str, float], ...] = (
    ("i remember", 0.9), ("back then", 0.7), ("when i was", 0.8), ("years ago", 0.8),
    ("one day", 0.6), ("that day", 0.6), ("at that moment", 0.8), ("in that moment", 0.8),
    ("my first", 0.7), ("the first time", 0.7), ("i started", 0.5), ("we started", 0.5),
    ("it began", 0.7), ("it started", 0.6), ("ended up", 0.6), ("in the end", 0.6),
    ("finally", 0.5), ("after that", 0.5), ("then he", 0.5), ("then she", 0.5),
    ("my father", 0.6), ("my mother", 0.6), ("my dad", 0.6), ("my mom", 0.6),
    ("my wife", 0.5), ("my husband", 0.5), ("my boss", 0.5), ("my friend", 0.4),
    ("i grew up", 0.8), ("childhood", 0.6), ("story", 0.4), ("told me", 0.5),
)

VALUE_MARKERS: tuple[tuple[str, float], ...] = (
    ("here's how", 1.0), ("here are", 0.6), ("step one", 0.9), ("first step", 0.8),
    ("the trick is", 0.9), ("the key is", 0.8), ("what you need to", 0.8),
    ("you should", 0.6), ("you need to", 0.6), ("make sure you", 0.6),
    ("rule of thumb", 0.8), ("framework", 0.6), ("strategy", 0.6), ("tactic", 0.6),
    ("the formula", 0.7), ("three things", 0.8), ("two things", 0.7), ("five things", 0.8),
    ("how to", 0.7), ("the best way", 0.7), ("avoid", 0.5), ("mistake", 0.6),
    ("lesson", 0.6), ("tip", 0.4), ("advice", 0.6), ("learned", 0.5),
    ("in practice", 0.6), ("for example", 0.4), ("that means", 0.4),
)

CONTROVERSY_MARKERS: tuple[tuple[str, float], ...] = (
    ("i disagree", 0.9), ("you're wrong", 1.0), ("that's wrong", 0.9), ("that's nonsense", 1.0),
    ("i don't agree", 0.8), ("completely disagree", 1.0), ("that's ridiculous", 1.0),
    ("with all due respect", 0.7), ("no, no, no", 0.7), ("wait, wait", 0.5),
    ("controversial", 0.8), ("people will hate", 0.9), ("this will upset", 0.9),
    ("overrated", 0.7), ("a scam", 0.9), ("it's a lie", 1.0), ("that's a myth", 0.8),
    ("i'm going to be controversial", 1.0),
)

SHAREABLE_MARKERS: tuple[tuple[str, float], ...] = (
    ("send this to", 1.0), ("share this", 0.8), ("everyone needs to hear", 0.9),
    ("if you know someone", 0.9), ("tag someone", 0.8), ("relatable", 0.6),
    ("we've all been there", 0.8), ("you've probably", 0.6),
)

DANGLING_REFERENCE_MARKERS: tuple[str, ...] = (
    "as i said", "like i said", "as i mentioned", "like i mentioned",
    "as we discussed", "like we talked about", "as you know", "as you saw",
    "that thing i", "the thing i mentioned", "going back to", "earlier i",
    "so anyway", "anyway,", "moving on", "next question",
)

CONTEXT_DEPENDENT_STARTS: tuple[str, ...] = (
    "so ", "and ", "but ", "yeah", "right", "okay", "well ", "i mean",
    "um ", "uh ", "the other ", "another ", "also ", "plus ",
)

SECOND_PERSON_RE = re.compile(r"\b(you|your|yours|you're|you'll|you've)\b", re.I)
FIRST_PERSON_RE = re.compile(r"\b(i|my|mine|i'm|i've|i'll|we|our|us)\b", re.I)
PAST_TENSE_RE = re.compile(r"\b(was|were|had|did|went|said|told|found|made|took|gave|saw|felt)\b", re.I)
NUMBER_RE = re.compile(r"\b\$?\d[\d,]*(?:\.\d+)?%?\b")
MONEY_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?\s?(?:k|m|million|billion|thousand)?", re.I)
SUPERLATIVE_RE = re.compile(r"\b(best|worst|biggest|smallest|hardest|easiest|most|least|never|always|every|nobody|everyone|nothing|everything)\b", re.I)
IMPERATIVE_RE = re.compile(r"^\s*(?:so\s+)?(do|don't|stop|start|make|take|use|try|build|write|read|learn|avoid|focus|pick|choose|set|get|be)\b", re.I)
NEGATION_RE = re.compile(r"\b(not|never|no|don't|doesn't|didn't|won't|can't|cannot|isn't|aren't|wasn't)\b", re.I)
CAUSAL_RE = re.compile(r"\b(because|so that|therefore|that's why|which means|as a result)\b", re.I)


@lru_cache(maxsize=8192)
def normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def count_marker(text: str, markers: tuple[tuple[str, float], ...]) -> tuple[int, float]:
    """Returns (hits, weighted_strength) for a marker table."""
    haystack = normalise(text)
    hits = 0
    strength = 0.0
    for marker, weight in markers:
        occurrences = haystack.count(marker)
        if occurrences:
            hits += occurrences
            strength += weight * (1 + 0.25 * (occurrences - 1))
    return hits, strength


def count_words(text: str, words: dict[str, float]) -> tuple[int, float]:
    haystack = normalise(text)
    hits = 0
    strength = 0.0
    for word, weight in words.items():
        pattern = rf"\b{re.escape(word)}\b"
        occurrences = len(re.findall(pattern, haystack))
        if occurrences:
            hits += occurrences
            strength += weight * (1 + 0.25 * (occurrences - 1))
    return hits, strength


def count_phrases(text: str, phrases: tuple[str, ...]) -> int:
    haystack = normalise(text)
    return sum(haystack.count(phrase) for phrase in phrases)


def word_count(text: str) -> int:
    return len([w for w in (text or "").split() if w.strip(" .,!?;:")])


def sentence_starts_with_filler(text: str) -> bool:
    head = normalise(text)[:24]
    return any(head.startswith(f) for f in CONTEXT_DEPENDENT_STARTS) or any(
        f in head for f in ("um ", "uh ", "you know")
    )


def has_numbers(text: str) -> bool:
    return bool(NUMBER_RE.search(text or ""))


def is_question(text: str) -> bool:
    stripped = (text or "").strip()
    return bool(QUESTION_RE.search(stripped)) or normalise(stripped).startswith(
        ("what ", "why ", "how ", "when ", "who ", "where ", "which ", "is ", "are ", "do ", "did ", "can ", "would ", "should ")
    )
