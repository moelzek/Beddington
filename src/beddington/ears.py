"""Pure, testable logic for the voice assistant's "ears".

This module holds NO audio or speech-to-text I/O — only deterministic functions
that the CLI loop drives:
  * extract_wake_question() — find the wake word in a transcript and return the
    question after it (fuzzy, to absorb speech-to-text slips). Returns None when
    there is no wake word, so non-wake speech is silently ignored.

The transcribed question is always handed to assistant.answer_question(), which
has no vital-sign branch, so the medical-refusal boundary holds for free.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

# "beddington" is the default wake word; "paddington" and common Whisper
# mangles stay as aliases for marginal/far audio. Fuzzy matching (edit distance
# <= 2) catches the near-variants, so a slightly-misheard wake word still
# triggers.
WAKE_WORDS: tuple[str, ...] = (
    "beddington",
    "bedington",
    "bed in ten",
    "bed in ton",
    "bedding ten",
    "bedding ton",
    "bendington",
    "bellington",
    "bennington",
    "paddington",
    "badington",
    "bangton",
    "padington",
    "patington",
)


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


def extract_wake_question(
    transcript: str,
    wake_words: Sequence[str] = WAKE_WORDS,
    max_edits: int = 2,
) -> str | None:
    """Return the question after the wake word, or None if no wake word is heard.

    Returns "" (empty, not None) when the wake word is heard with no question, so
    the caller can distinguish "ignore" (None) from "wake, but ask what?" ("").
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
    for index, word in enumerate(words):
        span_lengths = (1, 3, 2) if len(word) <= 7 else (1,)
        for span_length in span_lengths:
            end = index + span_length
            if end > len(words):
                continue
            candidate = "".join(words[index:end])
            if len(candidate) < 4:
                continue
            allowed_edits = max_edits if span_length == 1 else max_edits + 1
            if any(
                _edit_distance(candidate, target) <= allowed_edits
                for target in wake_targets
            ):
                return " ".join(words[end:]).strip()
    return None
