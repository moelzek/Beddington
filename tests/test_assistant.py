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


def test_answer_presence_uses_scene() -> None:
    assert (
        answer_question("is anyone there?", SNAPSHOT)
        == "Best guess: settled near the cot."
    )


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
