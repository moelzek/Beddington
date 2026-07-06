from __future__ import annotations

from beddington.assistant import answer_question
from beddington.ears import extract_wake_question, match_wake


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
    assert extract_wake_question("badington how warm is it") == "how warm is it"
    # "bangton" was dropped as an alias: at 7 letters it put everyday speech
    # ("hang on") within fuzzy reach, waking the assistant on room conversation.
    assert extract_wake_question("a bangton water temperature") is None


def test_extract_question_beddington_wake() -> None:
    # "Hi Beddington" triggers the brain too.
    assert (
        extract_wake_question("hi beddington what is the humidity")
        == "what is the humidity"
    )
    assert extract_wake_question("hey beddington how warm is it") == "how warm is it"


def test_extract_question_tolerates_split_beddington_wake() -> None:
    # Whisper can split the name into ordinary words on the Pi mic.
    assert extract_wake_question("hi bed in ten stop") == "stop"
    assert extract_wake_question("hey bedding ten play rain") == "play rain"
    assert (
        extract_wake_question("hi bennington what is the temperature")
        == "what is the temperature"
    )


def test_extract_none_without_wake_word() -> None:
    assert extract_wake_question("just two parents chatting about dinner") is None


def test_everyday_room_speech_does_not_wake() -> None:
    # Phrases that falsely woke the assistant before the matcher was tightened
    # (wake word now must start in the first two words; 1 edit for single
    # words, 2 for joined spans; no short aliases).
    for phrase in [
        "hang on",
        "bang on",
        "put it on",
        "bring it on",
        "hold on a second",
        "adding on",
        "adding to it",
        "leaning on",
        "leading on",
        "bending down",
        "putting on the kettle",
        "band on the run",
        "wanton",
        "canton",
        "what's going on",
        "come on",
        "carry on",
    ]:
        assert extract_wake_question(phrase) is None, phrase


def test_wake_word_must_start_the_utterance() -> None:
    # Real usage is "Beddington, …" — a wake word buried mid-sentence is room
    # conversation (e.g. talking ABOUT the assistant), not a command to it.
    assert extract_wake_question("we should ask beddington the temperature") is None
    assert extract_wake_question("the train from paddington was late") is None
    # Up to one leading word ("hi", "hey") is still fine — covered above too.
    assert extract_wake_question("hey beddington stop") == "stop"


def test_wake_confidence_gates_followup_window() -> None:
    # Exact or 1-edit single-word matches are confident: the CLI may open the
    # 6 s follow-up window on a bare wake.
    assert match_wake("beddington").confident
    assert match_wake("paddington").confident
    assert match_wake("paddingten what is the temperature").confident
    # An exact multi-word join is confident too ("bedding ton" == beddington,
    # and "bed in ten" is itself an alias).
    assert match_wake("bedding ton").confident
    assert match_wake("hi bed in ten stop") == ("stop", True)
    # An INEXACT multi-word span still wakes but is not confident, so the CLI
    # won't open the follow-up window on it.
    inexact_span = match_wake("bedding town")
    assert inexact_span is not None and not inexact_span.confident


def test_extract_bare_wake_returns_empty_string() -> None:
    # Wake word with no question — distinct from None so the loop can still react.
    assert extract_wake_question("paddington") == ""


def test_vitals_question_answered_from_radar() -> None:
    # The ears produce text only; the deterministic brain answers vitals from the
    # radar (no medical disclaimer, per Mo's preference; still never reassurance).
    question = extract_wake_question("paddington what is his breathing rate")
    assert question == "what is his breathing rate"
    answer = answer_question(question, {"radar_heart_rate_bpm": 90.0})
    assert "90" in answer
    assert "from the radar" in answer.lower()
