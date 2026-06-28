from __future__ import annotations

from lullaby.assistant import answer_question

SNAPSHOT = {
    "room_temperature_c": 21.4,
    "room_humidity_pct": 49.0,
    "room_pressure_hpa": 1012.0,
    "room_gas_resistance_ohms": 120000,
    "room_illuminance_lx": 80.0,
    "person_present": True,
    "motion_detected": False,
    "target_distance_cm": 120.0,
}


def test_answer_humidity() -> None:
    answer = answer_question("Hi Paddington, what is the humidity?", SNAPSHOT)
    assert "49 percent" in answer
    assert "comfortable" in answer  # 49% sits in the comfortable range


def test_answer_interprets_values() -> None:
    warm = answer_question("temperature", {"room_temperature_c": 27.0})
    assert "27 degrees" in warm and "warm" in warm
    dry = answer_question("humidity", {"room_humidity_pct": 30.0})
    assert "30 percent" in dry and "dry" in dry
    dark = answer_question("is it bright", {"room_illuminance_lx": 5.0})
    assert "5 lux" in dark and "dark" in dark


def test_answer_temperature() -> None:
    assert "21.4 degrees" in answer_question("is it warm in here?", SNAPSHOT)


def test_answer_pressure() -> None:
    assert "1012 hectopascals" in answer_question("what's the air pressure?", SNAPSHOT)


def test_answer_air_quality() -> None:
    assert "120 kilo-ohms" in answer_question("how is the air quality?", SNAPSHOT)


def test_answer_brightness() -> None:
    assert "80 lux" in answer_question("is it dark in the room?", SNAPSHOT)


def test_answer_presence_plainly() -> None:
    assert (
        answer_question("is anyone there?", SNAPSHOT)
        == "Yes — I can detect someone in the room."
    )


def test_natural_presence_phrasing() -> None:
    # "are there people in the room" must reach presence, not the fallback.
    answer = answer_question(
        "are there people in the room", {"person_present": False, "motion_detected": False}
    )
    assert "anyone" in answer.lower()


def test_natural_humidity_phrasing() -> None:
    # "is the air dry" should reach humidity, not the overview.
    answer = answer_question("is the air dry in here", {"room_humidity_pct": 30.0})
    assert "30 percent" in answer and "dry" in answer


def test_presence_does_not_invent_empty_without_reading() -> None:
    # No radar presence reading + no motion: must not claim the room is "empty".
    answer = answer_question("is anyone there?", {})
    assert "empty" not in answer.lower()


def test_nan_reading_is_refused() -> None:
    assert "say it again" in answer_question(
        "what is the temperature", {"room_temperature_c": float("nan")}
    )


def test_answer_presence_when_empty() -> None:
    answer = answer_question(
        "is anybody around?", {"person_present": False, "motion_detected": False}
    )
    assert answer.startswith("No")
    assert "anyone" in answer.lower()


def test_answer_people_count() -> None:
    assert "2 people" in answer_question(
        "how many people are in the room?", {"target_count": 2}
    )
    assert "one person" in answer_question("how many people?", {"target_count": 1})
    assert "anyone" in answer_question("how many people?", {"target_count": 0}).lower()


def test_answer_room_overview() -> None:
    answer = answer_question("how is the room?", SNAPSHOT)
    assert "degrees" in answer
    assert "percent" in answer
    assert "pressure" in answer  # overview covers all environment readings
    assert any(word in answer for word in ("lit", "dark", "bright"))
    # The overview is the environment, not presence.
    assert "cot" not in answer


def test_vitals_questions_are_refused() -> None:
    # Vitals-flavoured questions must hit the fallback, never people/presence/motion.
    loaded = {
        "target_count": 2,
        "person_present": True,
        "motion_detected": True,
        "radar_heart_rate_bpm": 90.0,
        "radar_respiratory_rate": 16.0,
    }
    for question in (
        "how many breaths per minute",
        "is she breathing",
        "is anyone breathing in there",
        "is she breathing and moving",
        "what is her heart rate",
        "what is her pulse",
        "what is the respiratory rate",
    ):
        answer = answer_question(question, loaded)
        assert "say it again" in answer, question
        assert "90" not in answer
        assert "2 people" not in answer


def test_specific_question_beats_overview() -> None:
    # "how warm is the room" must route to temperature, not the room overview.
    answer = answer_question("how warm is the room?", SNAPSHOT)
    assert "21.4 degrees" in answer
    assert "Here's the room" not in answer


def test_answer_distance() -> None:
    assert "120 centimetres" in answer_question("how far away is the baby?", SNAPSHOT)


def test_answer_fallback_when_unknown() -> None:
    assert "say it again" in answer_question(
        "what is the meaning of life?", SNAPSHOT
    )


def test_answer_fallback_when_value_missing() -> None:
    assert "say it again" in answer_question(
        "what is the humidity?", {}
    )


def test_answer_tolerates_misheard_keywords() -> None:
    # Whisper slips on the topic word at marginal audio; fuzzy matching recovers it.
    assert "21.4 degrees" in answer_question("what's the temprature", SNAPSHOT)
    assert "49 percent" in answer_question("tell me the humdity", SNAPSHOT)


def test_answer_falls_back_on_unrelated_word() -> None:
    # A garbled word that is not close to any topic must NOT false-match.
    assert "say it again" in answer_question("western", SNAPSHOT)


def test_answer_ignores_substring_false_match() -> None:
    # "shot" must not trigger the temperature branch by containing "hot".
    assert "say it again" in answer_question("lets go to the mid shot", SNAPSHOT)


def test_vitals_are_never_answered() -> None:
    snapshot = {"radar_heart_rate_bpm": 90.0, "radar_respiratory_rate": 16.0}
    answer = answer_question("what is the baby's heart rate?", snapshot)
    assert "90" not in answer
    assert "heart" not in answer.lower()
