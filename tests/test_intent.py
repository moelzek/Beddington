from __future__ import annotations

import json

import pytest

from beddington.config import NarratorConfig, SootheStepConfig
from beddington.intent import (
    INTENT_KEYWORDS,
    lead_response,
    translate_intent,
    translate_soothe_command,
)


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def _cfg(**kw: object) -> NarratorConfig:
    base: dict[str, object] = dict(
        enabled=True,
        backend="ollama",
        model="llama3.2:1b",
        host="http://ollama.local:11434",
    )
    base.update(kw)
    return NarratorConfig(**base)  # type: ignore[arg-type]


def test_translate_intent_returns_allowed_keyword_from_injected_llm() -> None:
    calls: list[str] = []

    def fake(prompt: str, config: object) -> str:
        del config
        calls.append(prompt)
        return "temperature"

    assert translate_intent("is it too warm in there?", _cfg(), ask_llm=fake) == "temperature"
    assert calls
    assert "temperature" in calls[0]
    assert "is it too warm in there?" in calls[0]
    for keyword in INTENT_KEYWORDS:
        assert keyword in calls[0]


def test_translate_intent_returns_none_when_disabled() -> None:
    def fail(prompt: str, config: object) -> str:
        raise AssertionError("translator should not call the model")

    assert translate_intent("is the air dry?", _cfg(enabled=False), ask_llm=fail) is None


def test_translate_intent_returns_none_for_non_ollama_backend() -> None:
    def fail(prompt: str, config: object) -> str:
        raise AssertionError("translator should not call the model")

    assert translate_intent("is the room bright?", _cfg(backend="other"), ask_llm=fail) is None


@pytest.mark.parametrize(
    "response",
    [
        "room_temperature_c = 22",
        "The room is 22 degrees.",
        "temperature and humidity",
        "open window",
        "",
    ],
)
def test_translate_intent_rejects_values_and_unknown_text(response: str) -> None:
    def fake(prompt: str, config: object) -> str:
        del prompt, config
        return response

    assert translate_intent("what do you think?", _cfg(), ask_llm=fake) is None


def test_translate_intent_accepts_simple_wrapping() -> None:
    def fake(prompt: str, config: object) -> str:
        del prompt, config
        return '"air_quality".'

    assert translate_intent("does the air smell odd?", _cfg(), ask_llm=fake) == "air quality"


def test_translate_intent_returns_none_when_injected_llm_raises() -> None:
    def fake(prompt: str, config: object) -> str:
        del prompt, config
        raise OSError("local model unavailable")

    assert translate_intent("is there movement?", _cfg(), ask_llm=fake) is None


def test_translate_intent_uses_ollama_generate(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[tuple[object, float]] = []

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        requests.append((request, timeout))
        return FakeResponse({"response": "humidity"})

    monkeypatch.setattr("beddington.intent.urllib.request.urlopen", fake_urlopen)

    assert translate_intent("is the air dry?", _cfg()) == "humidity"

    request, timeout = requests[0]
    payload = json.loads(request.data.decode("utf-8"))
    assert request.full_url == "http://ollama.local:11434/api/generate"
    assert timeout == 8.0
    assert payload["stream"] is False
    assert payload["model"] == "llama3.2:1b"
    assert payload["options"] == {"num_predict": 8, "temperature": 0.0}
    assert "is the air dry?" in payload["prompt"]


def test_translate_intent_honours_tuning_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[object, float]] = []

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        requests.append((request, timeout))
        return FakeResponse({"response": "temperature"})

    monkeypatch.setattr("beddington.intent.urllib.request.urlopen", fake_urlopen)

    config = _cfg(
        intent_num_predict=5,
        intent_temperature=0.2,
        intent_timeout=1.5,
    )

    assert translate_intent("is it warm?", config) == "temperature"

    request, timeout = requests[0]
    payload = json.loads(request.data.decode("utf-8"))
    assert timeout == 1.5
    assert payload["options"] == {"num_predict": 5, "temperature": 0.2}


def test_lead_response_handles_non_sensor_conversation() -> None:
    def fake(prompt: str, config: object) -> str:
        del config
        assert "non-sensor conversation" in prompt
        return "I don't know her name yet, but I can remember it once you tell me."

    assert "don't know her name yet" in lead_response(
        "what is my baby's name?",
        _cfg(),
        ask_llm=fake,
    )


def test_lead_response_rejects_sensor_or_safety_claim() -> None:
    def fake(prompt: str, config: object) -> str:
        del prompt, config
        return "She is safe and sleeping."

    assert lead_response("is she okay?", _cfg(), ask_llm=fake) == (
        "Sorry, I can't answer that from here."
    )


def test_lead_response_conversational_carries_history_weather_and_character() -> None:
    seen: dict[str, str] = {}

    def fake(prompt: str, config: object) -> str:
        del config
        seen["prompt"] = prompt
        return (
            "Most little ones start around six months, dear — soft steamed "
            "veg sticks are a lovely first food. Let her set the pace."
        )

    answer = lead_response(
        "when should we start baby led weaning?",
        _cfg(),
        ask_llm=fake,
        history=[("hello there", "Hello, dear! Lovely to hear you.")],
        weather="Outside it is clear and about 20 degrees Celsius.",
        conversational=True,
    )
    prompt = seen["prompt"]
    # Everything lives in the one Paddington system prompt.
    assert "spirit of Paddington" in prompt
    assert "baby-led weaning" in prompt
    assert "do not add disclaimers" in prompt
    assert "Parent: hello there" in prompt
    assert "Beddington: Hello, dear! Lovely to hear you." in prompt
    assert "Outside it is clear and about 20 degrees Celsius." in prompt
    assert prompt.rstrip().endswith("Beddington:")
    # Relaxed cleaner: multi-sentence childcare answer with counting words passes.
    assert "six months" in answer


def test_lead_response_conversational_allows_digits_and_childcare_words() -> None:
    reply = "Around 6 months is normal, and sleeping through takes time."

    answer = lead_response(
        "when do babies sleep through the night?",
        _cfg(),
        ask_llm=lambda prompt, config: reply,
        conversational=True,
    )
    assert answer == reply
    # The same reply is still rejected by the strict (non-conversational) path.
    strict = lead_response(
        "when do babies sleep through the night?",
        _cfg(),
        ask_llm=lambda prompt, config: reply,
    )
    assert strict == "Sorry, I can't answer that from here."


def test_translate_soothe_command_maps_music_context() -> None:
    presets = {
        "piano": SootheStepConfig(name="Piano"),
        "white_noise": SootheStepConfig(name="White noise"),
    }

    def fake(prompt: str, config: object) -> str:
        del config
        assert "play music for sleep" in prompt
        return '{"action":"play_best","category":"music","context":"sleep"}'

    assert translate_soothe_command(
        "play music for sleep",
        _cfg(),
        presets,
        ask_llm=fake,
    ) == {"action": "play_best", "category": "music", "context": "sleep"}


def test_translate_soothe_command_skips_llm_for_non_soothe_questions() -> None:
    # The lexical gate keeps the (cold-loading, seconds-long) Ollama call out
    # of ordinary sensor questions — they must fall through to the
    # deterministic answer path immediately.
    def fake(prompt: str, config: object) -> str:
        raise AssertionError("LLM must not be called for non-soothe questions")

    presets = {"lofi_rain": SootheStepConfig(name="Lofi rain")}
    for question in [
        "what is the temperature",
        "light in the room",
        "how was the night",
        "is anyone there",
    ]:
        assert translate_soothe_command(question, _cfg(), presets, ask_llm=fake) is None


def test_translate_soothe_command_gate_passes_soothe_phrasings() -> None:
    # Soothe-ish phrasings (including preset-name words) still reach the LLM.
    seen: list[str] = []

    def fake(prompt: str, config: object) -> str:
        del config
        seen.append(prompt)
        return '{"action":"stop"}'

    presets = {"lofi_rain": SootheStepConfig(name="Lofi rain")}
    for question in [
        "flame music",
        "make it quieter",
        "put on lofi",
        "turn it off",
        "relaxing for feeding",
        "something calming please",
        "that worked",
        "that didn't help",
    ]:
        translate_soothe_command(question, _cfg(), presets, ask_llm=fake)
    assert len(seen) == 8


def test_translate_soothe_command_rejects_unknown_preset() -> None:
    presets = {"piano": SootheStepConfig(name="Piano")}

    def fake(prompt: str, config: object) -> str:
        del prompt, config
        return '{"action":"play","preset":"washing_machine"}'

    assert translate_soothe_command(
        "play washing machine",
        _cfg(),
        presets,
        ask_llm=fake,
    ) is None


def test_translate_soothe_command_uses_longer_ollama_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[object, float]] = []

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        requests.append((request, timeout))
        return FakeResponse({"response": '{"action":"stop"}'})

    monkeypatch.setattr("beddington.intent.urllib.request.urlopen", fake_urlopen)

    assert translate_soothe_command("stop the music", _cfg()) == {"action": "stop"}

    request, timeout = requests[0]
    payload = json.loads(request.data.decode("utf-8"))
    assert timeout == 8.0
    assert payload["options"] == {"num_predict": 80, "temperature": 0.0}
