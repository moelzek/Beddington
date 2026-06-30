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
