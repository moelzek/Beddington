from __future__ import annotations

import json

import pytest

from beddington.config import NarratorConfig
from beddington.persona import is_medically_sensitive, paddingtonise


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
        persona_enabled=True,
        backend="ollama",
        model="llama3.2:1b",
        persona_num_predict=80,
        persona_temperature=0.4,
        persona_timeout=8.0,
    )
    base.update(kw)
    return NarratorConfig(**base)  # type: ignore[arg-type]


def _mock(monkeypatch: pytest.MonkeyPatch, response_text: str) -> None:
    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        return FakeResponse({"response": response_text})

    monkeypatch.setattr("beddington.persona.urllib.request.urlopen", fake_urlopen)


PLAIN = "The room is about 20 degrees Celsius, comfortable for Rayan."


def test_clean_restyle_used(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock(
        monkeypatch,
        "If I may, the room is about 20 degrees Celsius, comfortable for Rayan.",
    )
    out = paddingtonise(PLAIN, _cfg())
    assert "20 degrees" in out
    assert out != PLAIN  # actually restyled


def test_dropped_child_name_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock(
        monkeypatch,
        "If I may, the room is about 20 degrees Celsius, comfortable for a little one.",
    )
    assert paddingtonise(PLAIN, _cfg()) == PLAIN


def test_added_reassurance_word_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock(monkeypatch, "Don't worry, the baby is perfectly fine at about 20 degrees Celsius.")
    assert paddingtonise(PLAIN, _cfg()) == PLAIN


def test_invented_number_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock(monkeypatch, "The room is about 20 degrees Celsius, around 22 percent too.")
    assert paddingtonise(PLAIN, _cfg()) == PLAIN


def test_added_presence_claim_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    plain = "Playing white noise."
    _mock(monkeypatch, "Playing white noise while someone stayed nearby.")
    assert paddingtonise(plain, _cfg()) == plain


def test_dropped_number_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    plain = "Around 16 to 20 degrees Celsius is the usual comfortable range."
    _mock(monkeypatch, "Around 20 degrees Celsius is the comfortable range, if I may.")
    assert paddingtonise(plain, _cfg()) == plain


def test_altered_number_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock(monkeypatch, "The room is about 21 degrees Celsius, marvellous.")
    assert paddingtonise(PLAIN, _cfg()) == PLAIN


def test_spelled_out_number_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock(monkeypatch, "The room is about twenty degrees Celsius, marvellous.")
    assert paddingtonise(PLAIN, _cfg()) == PLAIN


def test_unit_swap_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    plain = "The humidity is about 20 percent, comfortable."
    _mock(monkeypatch, "The humidity is about 20 degrees, comfortable.")  # percent->degrees
    assert paddingtonise(plain, _cfg()) == plain


def test_added_reassurance_synonym_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock(
        monkeypatch,
        "The room is about 20 degrees Celsius; the little one is resting peacefully.",
    )
    assert paddingtonise(PLAIN, _cfg()) == PLAIN


def test_ollama_down_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        calls.append(1)
        raise OSError("connection refused")

    monkeypatch.setattr("beddington.persona.urllib.request.urlopen", fake_urlopen)
    assert paddingtonise(PLAIN, _cfg()) == PLAIN
    assert calls  # it actually tried


def test_timeout_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: object, timeout: float) -> FakeResponse:
        raise TimeoutError()

    monkeypatch.setattr("beddington.persona.urllib.request.urlopen", fake_urlopen)
    assert paddingtonise(PLAIN, _cfg()) == PLAIN


def test_empty_output_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock(monkeypatch, "   ")
    assert paddingtonise(PLAIN, _cfg()) == PLAIN


def test_persona_disabled_is_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(request: object, timeout: float) -> FakeResponse:
        raise AssertionError("urlopen should not be called when persona disabled")

    monkeypatch.setattr("beddington.persona.urllib.request.urlopen", fail)
    assert paddingtonise(PLAIN, _cfg(persona_enabled=False)) == PLAIN


def test_trailing_ramble_trimmed(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock(
        monkeypatch,
        "The room is about 20 degrees Celsius, rather pleasant.\n\nThe baby is fine.",
    )
    out = paddingtonise(PLAIN, _cfg())
    assert "20 degrees" in out
    assert "fine" not in out.lower()  # the banned second paragraph was trimmed off


def test_banned_word_already_in_plain_is_not_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    plain = "The air pressure is normal."
    _mock(monkeypatch, "The air pressure is normal, if I may say.")
    out = paddingtonise(plain, _cfg())
    assert "normal" in out  # 'normal' was already in plain -> echoing it is fine


def test_vitals_answer_spoken_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(request: object, timeout: float) -> FakeResponse:
        raise AssertionError("vitals must never be sent to the LLM")

    monkeypatch.setattr("beddington.persona.urllib.request.urlopen", fail)
    vitals = (
        "From the radar, breathing about 16 breaths a minute, and heart rate "
        "about 90 beats per minute."
    )
    assert is_medically_sensitive(vitals)
    assert paddingtonise(vitals, _cfg()) == vitals


def test_unsupported_vitals_spoken_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(request: object, timeout: float) -> FakeResponse:
        raise AssertionError("vitals decline must never be sent to the LLM")

    monkeypatch.setattr("beddington.persona.urllib.request.urlopen", fail)
    decline = (
        "I can only read breathing and heart rate from the radar. I don't have "
        "that particular reading."
    )
    assert paddingtonise(decline, _cfg()) == decline


def test_soothe_confirmation_restyled(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock(monkeypatch, "Marmalade at the ready! Playing white noise for you now.")
    out = paddingtonise("Playing white noise.", _cfg())
    assert "white noise" in out.lower()
