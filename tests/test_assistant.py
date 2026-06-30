from __future__ import annotations

from beddington.config import NarratorConfig, SootheStepConfig
from beddington.assistant import ConversationMemory, answer_question

SNAPSHOT = {
    "room_temperature_c": 21.4,
    "room_humidity_pct": 49.0,
    "room_pressure_hpa": 1012.0,
    "room_gas_resistance_ohms": 120000,
    "room_illuminance_lx": 80.0,
    "person_present": True,
    # Presence is radar-driven (radar_person_present): the person flag corroborated
    # by a real target / breathing lock. motion_detected is legacy (PIR removed).
    "motion_detected": True,
    "target_distance_cm": 120.0,
    "radar_respiratory_rate": 16.0,
}


def _translator_config(enabled: bool = True) -> NarratorConfig:
    return NarratorConfig(
        enabled=enabled,
        backend="ollama",
        model="llama3.2:1b",
        host="http://ollama.local:11434",
    )


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
    assert "dark" in dark  # spoken as an interpretation, no raw lux


def test_answer_temperature() -> None:
    assert "21 degrees" in answer_question("is it warm in here?", SNAPSHOT)


def test_temperature_followup_uses_last_intent_and_current_reading() -> None:
    memory = ConversationMemory()
    first = answer_question(
        "what is the temperature?",
        {"room_temperature_c": 18.0},
        memory=memory,
    )
    assert "18 degrees" in first
    assert memory.last_intent == "temperature"

    answer = answer_question(
        "is that hot for Rayan?",
        {"room_temperature_c": 23.0},
        memory=memory,
    )

    assert "23 degrees" in answer
    assert "warm for Rayan" in answer
    assert "say it again" not in answer


def test_bare_ok_followup_uses_last_intent_without_llm() -> None:
    memory = ConversationMemory()
    answer_question("temperature", {"room_temperature_c": 18.0}, memory=memory)

    def fail(prompt: str, config: object) -> str:
        del prompt, config
        raise AssertionError("follow-up should resolve before LLM translation")

    answer = answer_question(
        "is that ok?",
        {"room_temperature_c": 19.0},
        _translator_config(),
        ask_llm=fail,
        memory=memory,
    )

    assert "19 degrees" in answer
    assert "comfortable for Rayan" in answer


def test_humidity_followup_switches_topic_after_any_reading() -> None:
    memory = ConversationMemory()
    first = answer_question(
        "how bright is it?",
        {"room_illuminance_lx": 80.0},
        memory=memory,
    )
    assert "lit" in first
    assert memory.last_intent == "brightness"

    answer = answer_question(
        "what about humidity?",
        {"room_humidity_pct": 63.0},
        memory=memory,
    )

    assert "63 percent" in answer
    assert "humid" in answer
    assert memory.last_intent == "humidity"


def test_answer_pressure_is_interpreted() -> None:
    # No raw hectopascals — pressure is spoken high/normal/low.
    answer = answer_question("what's the air pressure?", SNAPSHOT)
    assert "pressure" in answer and "normal" in answer
    assert "hectopascal" not in answer


def test_answer_air_quality_is_interpreted() -> None:
    answer = answer_question("how is the air quality?", SNAPSHOT)
    assert "air quality" in answer and "clean" in answer
    assert "ohm" not in answer


def test_answer_brightness_is_interpreted() -> None:
    answer = answer_question("is it dark in the room?", SNAPSHOT)
    assert "lit" in answer  # "softly lit", not "80 lux"
    assert "lux" not in answer


def test_lighting_synonym_routes() -> None:
    assert "lit" in answer_question("how is the lighting", {"room_illuminance_lx": 80.0})


def test_motion_not_shadowed_by_presence() -> None:
    # "is there any movement" must reach motion, not presence.
    still = {**SNAPSHOT, "motion_detected": False}
    answer = answer_question("is there any movement", still)
    assert "still" in answer  # motion_detected is False


def test_people_count_handles_bad_value() -> None:
    # A glitchy NaN/inf radar count must not crash; it falls back to presence.
    for bad in (float("nan"), float("inf")):
        answer = answer_question("how many people are there", {"target_count": bad})
        assert isinstance(answer, str) and answer


def test_answer_presence_plainly() -> None:
    assert (
        answer_question("is anyone there?", SNAPSHOT)
        == "Yes, I can detect someone in the room."
    )


def test_radar_presence_requires_corroboration() -> None:
    # Radar-driven presence (the PIR has been removed): trust the "present" flag
    # only when a real target or a plausible breathing lock corroborates it, so
    # bare-flag micro-vibration clutter is never reported as someone in the room.
    from beddington.assistant import radar_person_present

    # Flag + a real target (distance / count) or a breathing lock → present.
    assert radar_person_present({"person_present": True, "target_distance_cm": 90.0})
    assert radar_person_present({"person_present": True, "target_count": 1.0})
    assert radar_person_present({"person_present": True, "radar_respiratory_rate": 16.0})
    # Bare present flag with nothing behind it (clutter) → not trusted.
    bare = {"person_present": True}
    assert radar_person_present(bare) is False
    assert answer_question("is anyone there", bare).startswith("No")
    assert radar_person_present({"person_present": True, "target_count": 0.0}) is False
    # A false flag, the removed PIR's motion, and an empty snapshot never assert it.
    assert radar_person_present({"person_present": False, "target_distance_cm": 90.0}) is False
    assert radar_person_present({"motion_detected": True}) is False
    assert radar_person_present({}) is False


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


import re

# Words/phrases that would turn a labelled estimate into medical/safety
# reassurance. A vitals answer must contain none of them.
_REASSURANCE = {
    "fine", "safe", "healthy", "normal", "normally", "okay", "asleep",
    "sleeping", "well", "good", "stable", "calm", "settled",
}
_REASSURANCE_PHRASES = (
    "breathing normally", "he s okay", "rayan is okay",
    "all good", "perfectly fine", "doing well",
)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def _no_reassurance(text: str) -> bool:
    low = text.lower()
    return _tokens(text).isdisjoint(_REASSURANCE) and not any(
        phrase in low for phrase in _REASSURANCE_PHRASES
    )


def test_vitals_questions_answered_without_reassurance() -> None:
    # Vitals questions are answered from the radar (no medical disclaimer, per
    # Mo's preference) — but still never reassuring and never captured by
    # people/presence/motion.
    loaded = {
        "target_count": 2,
        "person_present": True,
        "motion_detected": True,
        "radar_heart_rate_bpm": 90.0,
        "radar_respiratory_rate": 16.0,
    }
    for question in (
        "how many breaths per minute",
        "is he breathing",
        "is he still breathing",
        "what is his heart rate",
        "what is his heart rate and how warm is the room",
        "what is his pulse",
        "what is the respiratory rate",
        "how is Rayan",
    ):
        answer = answer_question(question, loaded)
        assert "90" in answer or "16" in answer, question  # the radar numbers
        assert _no_reassurance(answer), question
        assert "2 people" not in answer, question  # not captured by people-count


def test_vitals_no_lock_is_honest() -> None:
    # No vitals in the snapshot (radar not locked / bench_vitals off): say so,
    # never fabricate, never reassure.
    answer = answer_question("what is his heart rate", {})
    assert "don't have a clear reading" in answer.lower()
    assert _no_reassurance(answer)


def test_vitals_surface_the_numbers() -> None:
    answer = answer_question(
        "what is his breathing rate", {"radar_respiratory_rate": 16.0}
    )
    assert "16" in answer
    assert _no_reassurance(answer)


def test_unsupported_vitals_are_declined_not_misrouted() -> None:
    # Oxygen, blood pressure, fever are not measured: say so, never return air
    # pressure or the breathing/heart estimate.
    loaded = {
        "room_pressure_hpa": 1012.0,
        "radar_respiratory_rate": 16.0,
        "radar_heart_rate_bpm": 90.0,
    }
    for question in (
        "what is the baby's blood pressure",
        "what's his oxygen saturation",
        "does he have a fever",
    ):
        answer = answer_question(question, loaded)
        assert "don't have that particular reading" in answer.lower(), question
        assert "hectopascal" not in answer.lower(), question
        assert "90" not in answer, question


def test_chest_movement_is_vitals_not_motion() -> None:
    answer = answer_question(
        "is the baby's chest moving",
        {"radar_respiratory_rate": 16.0, "motion_detected": True},
    )
    assert "16" in answer  # radar breathing, not "there's movement in the room"
    assert _no_reassurance(answer)


def test_non_vitals_baby_questions_do_not_speak_vitals() -> None:
    loaded = {"radar_respiratory_rate": 16.0, "radar_heart_rate_bpm": 90.0}
    for question in ("is Rayan asleep", "why is Rayan crying", "is Rayan hungry"):
        answer = answer_question(question, loaded)
        assert "say it again" in answer, question
        assert "90" not in answer, question


def test_specific_question_beats_overview() -> None:
    # "how warm is the room" must route to temperature, not the room overview.
    answer = answer_question("how warm is the room?", SNAPSHOT)
    assert "21 degrees" in answer
    assert "Here's the room" not in answer


def test_answer_distance() -> None:
    assert "120 centimetres" in answer_question("how far away is the baby?", SNAPSHOT)


def test_is_night_question() -> None:
    from beddington.assistant import is_night_question

    assert is_night_question("how was the night")
    assert is_night_question("Paddington, give me the night summary")
    assert is_night_question("what happened overnight")
    assert is_night_question("recap please")
    # current-reading questions are not night questions
    assert not is_night_question("what is the temperature")
    assert not is_night_question("is anyone there")


def test_answer_fallback_when_unknown() -> None:
    assert "say it again" in answer_question(
        "what is the meaning of life?", SNAPSHOT
    )


def test_answer_fallback_when_value_missing() -> None:
    assert "say it again" in answer_question(
        "what is the humidity?", {}
    )


def test_llm_translator_disabled_keeps_fallback() -> None:
    calls: list[str] = []

    def fake(prompt: str, config: object) -> str:
        del config
        calls.append(prompt)
        return "temperature"

    answer = answer_question(
        "should I crack a window?",
        SNAPSHOT,
        _translator_config(enabled=False),
        ask_llm=fake,
    )

    assert "say it again" in answer
    assert calls == []


def test_llm_translator_only_runs_after_fallback() -> None:
    def fail(prompt: str, config: object) -> str:
        del prompt, config
        raise AssertionError("translator should only run after fallback")

    answer = answer_question(
        "what is the humidity?",
        SNAPSHOT,
        _translator_config(),
        ask_llm=fail,
    )

    assert "49 percent" in answer


def test_llm_translator_maps_fallback_to_deterministic_room_answer() -> None:
    def fake(prompt: str, config: object) -> str:
        del prompt, config
        return "temperature"

    answer = answer_question(
        "should I crack a window?",
        {"room_temperature_c": 18.0},
        _translator_config(),
        ask_llm=fake,
    )

    assert "18 degrees" in answer


def test_llm_translator_cannot_supply_values() -> None:
    def fake(prompt: str, config: object) -> str:
        del prompt, config
        return "temperature"

    answer = answer_question(
        "should I crack a window if it is 999?",
        {"room_temperature_c": 19.0},
        _translator_config(),
        ask_llm=fake,
    )

    assert "19 degrees" in answer
    assert "999" not in answer


def test_answer_tolerates_misheard_keywords() -> None:
    # Whisper slips on the topic word at marginal audio; fuzzy matching recovers it.
    assert "21 degrees" in answer_question("what's the temprature", SNAPSHOT)
    assert "49 percent" in answer_question("tell me the humdity", SNAPSHOT)


def test_match_soothe_command() -> None:
    from beddington.assistant import match_soothe_command
    from beddington.ears import extract_wake_question

    assert match_soothe_command("play white noise") == {
        "action": "play", "preset": "white_noise"
    }
    assert match_soothe_command("put on the heartbeat") == {
        "action": "play", "preset": "heartbeat"
    }
    assert match_soothe_command("play some music") == {
        "action": "play", "preset": "soothing_music"
    }
    # generic comfort -> default preset
    assert match_soothe_command("soothe Rayan") == {
        "action": "play", "preset": "white_noise"
    }
    assert match_soothe_command(extract_wake_question("Hi Beddington, stop") or "") == {
        "action": "stop"
    }
    assert match_soothe_command("stop") == {"action": "stop"}
    assert match_soothe_command("stop the soothe") == {"action": "stop"}
    assert match_soothe_command("stop the sound") == {"action": "stop"}
    assert match_soothe_command("stop the music") == {"action": "stop"}
    assert match_soothe_command("stop the noise") == {"action": "stop"}
    assert match_soothe_command("turn off the music") == {"action": "stop"}
    assert match_soothe_command("switch off the music") == {"action": "stop"}
    # not soothe commands
    assert match_soothe_command("what is the temperature") is None
    assert match_soothe_command("is anyone there") is None
    assert match_soothe_command("what's his heart rate") is None


def test_match_soothe_command_vc2_play_names_and_controls() -> None:
    from beddington.assistant import match_soothe_command

    presets = {
        "white_noise": SootheStepConfig(name="white noise"),
        "heartbeat": SootheStepConfig(name="heartbeat-style pulses"),
        "soothing_music": SootheStepConfig(name="soothing music"),
        "uterine_whoosh": SootheStepConfig(name="uterine whoosh"),
        "pink_noise": SootheStepConfig(name="pink noise"),
        "rain": SootheStepConfig(name="rain"),
        "ocean_waves": SootheStepConfig(name="ocean waves"),
        "forest_breeze": SootheStepConfig(name="forest breeze"),
        "night_sky": SootheStepConfig(name="night sky"),
        "music_box_lullaby": SootheStepConfig(name="music box lullaby"),
        "shushing": SootheStepConfig(name="shushing"),
        "fan_hum": SootheStepConfig(name="fan hum"),
    }

    play_cases = {
        "PLAY WHITE NOISE": "white_noise",
        "play the heartbeat": "heartbeat",
        "play heartbeat-style pulses": "heartbeat",
        "play soothing music": "soothing_music",
        "play uterine whoosh": "uterine_whoosh",
        "play pink noise": "pink_noise",
        "play rain": "rain",
        "play ocean waves": "ocean_waves",
        "play forest breeze": "forest_breeze",
        "play night sky": "night_sky",
        "play music box lullaby": "music_box_lullaby",
        "play shushing": "shushing",
        "play fan hum": "fan_hum",
    }
    for phrase, preset in play_cases.items():
        assert match_soothe_command(phrase, presets) == {
            "action": "play",
            "preset": preset,
        }

    control_cases = {
        "next": {"action": "next"},
        "switch": {"action": "next"},
        "try another": {"action": "next"},
        "louder": {"action": "volume", "dir": "up"},
        "quieter": {"action": "volume", "dir": "down"},
        "start watching for crying": {"action": "autosoothe", "enabled": True},
        "stop watching": {"action": "autosoothe", "enabled": False},
        "auto soothe on": {"action": "autosoothe", "enabled": True},
        "auto soothe off": {"action": "autosoothe", "enabled": False},
    }
    for phrase, expected in control_cases.items():
        assert match_soothe_command(phrase, presets) == expected

    assert match_soothe_command("play washing machine", presets) is None


def test_answer_falls_back_on_unrelated_word() -> None:
    # A garbled word that is not close to any topic must NOT false-match.
    assert "say it again" in answer_question("western", SNAPSHOT)


def test_answer_ignores_substring_false_match() -> None:
    # "shot" must not trigger the temperature branch by containing "hot".
    assert "say it again" in answer_question("lets go to the mid shot", SNAPSHOT)


def test_vitals_answer_is_unreassuring() -> None:
    snapshot = {"radar_heart_rate_bpm": 90.0, "radar_respiratory_rate": 16.0}
    answer = answer_question("what is the baby's heart rate?", snapshot)
    assert "90" in answer and "16" in answer
    assert _no_reassurance(answer)
