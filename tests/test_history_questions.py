from __future__ import annotations

import re
from pathlib import Path

import pytest

from beddington.assistant import answer_history_question, is_history_question
from beddington.sensor_store import SensorStore

_BANNED = {"asleep", "sleeping", "slept", "safe", "healthy", "fine", "normal", "well"}


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def test_history_cry_count_from_seeded_store(tmp_path: Path) -> None:
    now = 20_000.0
    store = SensorStore(str(tmp_path / "history.db"))
    store.append_cry_episode(now - 900.0, now - 840.0, 60.0)
    store.append_cry_episode(now - 300.0, now - 240.0, 60.0)
    store.append_cry_episode(now - 13 * 3600.0, now - 13 * 3600.0 + 60.0, 60.0)

    answer = answer_history_question(
        "how many times did she cry tonight?",
        store,
        window_seconds=12 * 3600,
        now_ts=now,
    )

    assert answer == "I found 2 crying episodes tonight."
    store.close()


@pytest.mark.parametrize(
    ("question", "key", "values", "expected"),
    (
        (
            "is the temperature rising?",
            "room_temperature_c",
            [18.0, 18.5, 20.0, 21.0],
            "getting warmer",
        ),
        (
            "is it getting colder?",
            "room_temperature_c",
            [22.0, 21.0, 19.0, 18.0],
            "getting colder",
        ),
        (
            "is it getting more humid?",
            "room_humidity_pct",
            [40.0, 41.0, 50.0, 52.0],
            "getting more humid",
        ),
    ),
)
def test_history_trend_from_seeded_store(
    tmp_path: Path,
    question: str,
    key: str,
    values: list[float],
    expected: str,
) -> None:
    now = 20_000.0
    store = SensorStore(str(tmp_path / "history.db"))
    for index, value in enumerate(values):
        store.append(now - 3600.0 + index * 600.0, {key: value})

    answer = answer_history_question(question, store, now_ts=now)

    assert answer is not None
    assert expected in answer
    assert "(best guess)" in answer
    assert _words(answer).isdisjoint(_BANNED)
    store.close()


def test_history_question_with_sparse_history_says_so(tmp_path: Path) -> None:
    store = SensorStore(str(tmp_path / "history.db"))

    assert is_history_question("how many cries")
    assert is_history_question("is it getting colder?")
    assert answer_history_question("is it getting colder?", store, now_ts=20_000.0) == (
        "I don't have enough temperature history yet to tell."
    )
    store.close()
