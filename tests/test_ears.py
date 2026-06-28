from __future__ import annotations

from lullaby.assistant import answer_question
from lullaby.ears import extract_wake_question, iter_utterances


def test_extract_question_after_wake() -> None:
    assert (
        extract_wake_question("Hi Paddington, what is the humidity?")
        == "what is the humidity"
    )


def test_extract_question_hey_paddington() -> None:
    assert extract_wake_question("hey paddington is anyone there") == "is anyone there"


def test_extract_question_tolerates_mishearing() -> None:
    # Whisper often slips on the wake word; fuzzy matching absorbs it.
    assert (
        extract_wake_question("paddingten what is the temperature")
        == "what is the temperature"
    )
    assert extract_wake_question("padington temperature") == "temperature"
    # The exact mishearings Whisper produced on the Pi are wake words now.
    assert (
        extract_wake_question("a bangton water temperature") == "water temperature"
    )
    assert extract_wake_question("badington how warm is it") == "how warm is it"


def test_extract_none_without_wake_word() -> None:
    assert extract_wake_question("just two parents chatting about dinner") is None


def test_extract_bare_wake_returns_empty_string() -> None:
    # Wake word with no question — distinct from None so the loop can still react.
    assert extract_wake_question("paddington") == ""


def test_vitals_question_answered_as_labelled_bench_data() -> None:
    # The ears produce text only; the deterministic brain answers vitals from the
    # radar as a clearly-labelled rough estimate (never reassurance).
    question = extract_wake_question("paddington what is her breathing rate")
    assert question == "what is her breathing rate"
    answer = answer_question(question, {"radar_heart_rate_bpm": 90.0})
    assert "90" in answer
    assert "not a medical or safety reading" in answer.lower()


def test_iter_utterances_segments_one_sentence() -> None:
    flags = [False] * 2 + [True] * 30 + [False] * 25
    utterances = list(
        iter_utterances(flags, start_speech_frames=3, end_silence_frames=20)
    )
    assert len(utterances) == 1
    assert utterances[0].start_frame == 2
    assert utterances[0].end_frame == 32


def test_iter_utterances_ignores_silence() -> None:
    assert list(iter_utterances([False] * 50)) == []
