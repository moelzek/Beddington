"""Pure, testable logic for the voice assistant's "ears".

This module holds NO audio or speech-to-text I/O — only deterministic functions
that the CLI loop drives:
  * match_wake() — find the wake word at the START of a transcript and return
    the question after it plus a confidence flag (fuzzy, to absorb
    speech-to-text slips). Returns None when there is no wake word, so
    non-wake speech is silently ignored.
  * extract_wake_question() — question-only wrapper around match_wake().

The wake word must appear in the first two words of the utterance: real usage
is always "Beddington, …", and scanning the whole sentence made everyday room
conversation ("hang on", "putting on the kettle") wake the assistant.

The transcribed question is always handed to assistant.answer_question(), which
has no vital-sign branch, so the medical-refusal boundary holds for free.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import NamedTuple

# "beddington" is the default wake word; "paddington" and common Whisper
# mangles stay as aliases for marginal/far audio. Fuzzy matching (edit distance
# <= 1 for single words, <= 2 for joined multi-word spans) catches the
# near-variants, so a slightly-misheard wake word still triggers. Short/noisy
# aliases ("bangton") are gone — at 7 letters they put everyday speech
# ("hang on") within fuzzy reach of the wake word.
WAKE_WORDS: tuple[str, ...] = (
    "beddington",
    "bedington",
    "bed in ten",
    "bed in ton",
    "bedding ten",
    "bedding ton",
    # "bendington" (a real Whisper mangle) is intentionally absent: it is
    # 1 edit from "beddington" so single-word matching still catches it, and
    # keeping it as a span target let "bending down" wake the assistant.
    "bellington",
    "bennington",
    "paddington",
    "badington",
    "padington",
    "patington",
)

# The wake word must start within the first this-many words of the utterance.
_MAX_WAKE_START_INDEX = 1


def normalize_transcript(text: str) -> str:
    lowered = text.lower()
    lowered = re.sub(r"[^a-z0-9\s]", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb))
            )
        previous = current
    return previous[-1]


class WakeMatch(NamedTuple):
    question: str
    # True for an exact/near-exact hit (single word within 1 edit, or a
    # multi-word span that joins to a wake word exactly). Fuzzier span matches
    # still wake, but the caller should not open the follow-up window on them.
    confident: bool


def match_wake(
    transcript: str,
    wake_words: Sequence[str] = WAKE_WORDS,
) -> WakeMatch | None:
    """Return the question after the wake word, or None if no wake word is heard.

    The question is "" (empty, not None) when the wake word is heard with no
    question, so the caller can distinguish "ignore" (None) from "wake, but ask
    what?" (""). Only the first two words of the utterance can start the wake
    word — real usage is "Beddington, …", never mid-sentence.
    """
    words = normalize_transcript(transcript).split()
    if not words:
        return None
    # Match one-token wake words ("beddington") and common Whisper splits
    # ("bed in ten"). Joining short spans keeps the function pure while catching
    # marginal Pi-mic transcripts that split the name into ordinary words.
    wake_targets = {
        "".join(normalize_transcript(phrase).split())
        for phrase in wake_words
        if normalize_transcript(phrase)
    }
    best: tuple[int, int, int] | None = None  # (distance, -span_length, end)
    for index in range(min(len(words), _MAX_WAKE_START_INDEX + 1)):
        word = words[index]
        span_lengths = (1, 2, 3) if len(word) <= 7 else (1,)
        for span_length in span_lengths:
            end = index + span_length
            if end > len(words):
                continue
            candidate = "".join(words[index:end])
            if len(candidate) < 4:
                continue
            allowed_edits = 1 if span_length == 1 else 2
            # Anchor on the first letter: every wake alias keeps the initial
            # b/p plosive, while room-speech near-misses ("adding on",
            # "wellington") differ right at the front.
            distances = [
                _edit_distance(candidate, target)
                for target in wake_targets
                if target[0] == candidate[0]
            ]
            distance = min(distances, default=allowed_edits + 1)
            if distance > allowed_edits:
                continue
            key = (distance, -span_length, end)
            if best is None or key < best:
                best = key
    if best is None:
        return None
    distance, neg_span, end = best
    confident = distance == 0 or (-neg_span == 1 and distance <= 1)
    return WakeMatch(" ".join(words[end:]).strip(), confident)


def extract_wake_question(
    transcript: str,
    wake_words: Sequence[str] = WAKE_WORDS,
) -> str | None:
    """Question-only view of match_wake(), for callers without follow-up state."""
    match = match_wake(transcript, wake_words)
    return None if match is None else match.question
