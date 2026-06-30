from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from beddington.config import (
    AppConfig,
    DetectionConfig,
    NarratorConfig,
    NotificationConfig,
)
from beddington.digest import build_digest
from beddington.models import AudioWindow, Event, NightReport
from beddington.narrator import build_narration_prompt, narrate, speak
from beddington.pipeline import run_pipeline


class FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


@dataclass
class FakeSource:
    scores: list[float]
    name: str = "fake.wav"

    @property
    def duration_seconds(self) -> float:
        return len(self.scores) * 0.5

    def windows(self) -> Iterator[AudioWindow]:
        for index in range(len(self.scores)):
            yield AudioWindow(index * 0.5, np.zeros(16_000, dtype=np.float32))


class FakeDetector:
    name = "fake detector"

    def __init__(self, scores: list[float]):
        self._scores = iter(scores)

    def score(self, samples: np.ndarray) -> float:
        del samples
        return next(self._scores)


class FakeNotifier:
    def __init__(self) -> None:
        self.calls = 0

    def notify(self, title: str, message: str) -> dict[str, bool]:
        assert title == "Beddington"
        assert "Sustained crying" in message
        self.calls += 1
        return {"console": True, "desktop": False}


def test_narrate_returns_ollama_response(monkeypatch: pytest.MonkeyPatch) -> None:
    report = _sample_report()
    requests = []

    def fake_urlopen(request, timeout):
        requests.append((request, timeout))
        return FakeResponse({"response": "Crying was detected once for 5 seconds."})

    monkeypatch.setattr("beddington.narrator.urllib.request.urlopen", fake_urlopen)

    text = narrate(
        report,
        NarratorConfig(enabled=True, host="http://ollama.local:11434"),
        "fallback digest",
    )

    request, timeout = requests[0]
    payload = json.loads(request.data.decode("utf-8"))
    assert text == "Crying was detected once for 5 seconds."
    assert request.full_url == "http://ollama.local:11434/api/generate"
    assert timeout == 30
    assert payload["stream"] is False
    assert payload["model"] == "llama3.2:1b"
    assert payload["options"] == {"num_predict": 140, "temperature": 0.3}
    assert "Crying episode count: 1" in payload["prompt"]


def test_narrate_trims_trailing_ramble(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request, timeout):
        return FakeResponse(
            {
                "response": (
                    "Crying was detected once for 5 seconds.\n\n"
                    "Crying ceased after three quiet checks."
                )
            }
        )

    monkeypatch.setattr("beddington.narrator.urllib.request.urlopen", fake_urlopen)

    text = narrate(_sample_report(), NarratorConfig(enabled=True), "fallback digest")

    assert text == "Crying was detected once for 5 seconds."


def test_narrate_returns_fallback_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_urlopen(request, timeout):
        raise AssertionError("urlopen should not be called")

    monkeypatch.setattr("beddington.narrator.urllib.request.urlopen", fail_urlopen)

    assert (
        narrate(_sample_report(), NarratorConfig(enabled=False), "fallback digest")
        == "fallback digest"
    )


def test_narrate_falls_back_when_ollama_adds_sensor_fact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = _report_without_sensor_context()
    fallback = build_digest(report)

    def fake_urlopen(request, timeout):
        return FakeResponse(
            {
                "response": (
                    "Beddington noticed one crying episode. The room temperature "
                    "was 22 C, humidity was 60%, and presence stayed constant."
                )
            }
        )

    monkeypatch.setattr("beddington.narrator.urllib.request.urlopen", fake_urlopen)

    text = narrate(report, NarratorConfig(enabled=True), fallback)

    assert text == fallback
    assert "22" not in text
    assert "60" not in text
    assert "presence" not in text.lower()


def test_narrate_uses_faithful_rewording(monkeypatch: pytest.MonkeyPatch) -> None:
    report = _report_without_sensor_context()

    def fake_urlopen(request, timeout):
        return FakeResponse(
            {
                "response": (
                    "Beddington noticed one crying episode lasting 5 seconds, "
                    "and no parent notification was sent."
                )
            }
        )

    monkeypatch.setattr("beddington.narrator.urllib.request.urlopen", fake_urlopen)

    text = narrate(report, NarratorConfig(enabled=True), build_digest(report))

    assert text == (
        "Beddington noticed one crying episode lasting 5 seconds, "
        "and no parent notification was sent."
    )


def test_narrate_returns_fallback_when_post_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_urlopen(request, timeout):
        raise OSError("ollama unavailable")

    monkeypatch.setattr("beddington.narrator.urllib.request.urlopen", fail_urlopen)

    assert (
        narrate(_sample_report(), NarratorConfig(enabled=True), "fallback digest")
        == "fallback digest"
    )


def test_build_narration_prompt_uses_only_derived_facts() -> None:
    prompt = build_narration_prompt(_sample_report())

    assert "Crying episode count: 1" in prompt
    assert "Crying episode durations: 5 seconds." in prompt
    assert "Soothing played: white noise." in prompt
    assert "crying no longer detected after 2 quiet checks" in prompt
    assert "Best-guess room temperature context: 21.5 C." in prompt
    assert "Best-guess room humidity context: 48.2%." in prompt
    assert "Movement noticed 2 times." in prompt
    assert "best-guess context only" in prompt
    assert "Never say the baby is safe, asleep, healthy, fine, or breathing" in prompt
    assert 'Say "crying"' in prompt
    assert 'do not say "tantrum"' in prompt
    assert "raw.wav" not in prompt
    assert "/private/recordings" not in prompt


def test_build_narration_prompt_includes_radar_context() -> None:
    started = datetime(2026, 6, 28, tzinfo=UTC)
    events = (
        Event(
            kind="environment_sample",
            occurred_at=started + timedelta(seconds=2),
            offset_seconds=2.0,
            details={"person_present": True, "room_illuminance_lx": 96.2},
        ),
    )
    report = NightReport(
        started_at=started,
        finished_at=started + timedelta(seconds=10),
        source="/private/recordings/raw.wav",
        detector="fake",
        threshold=0.4,
        sustained_seconds=1.0,
        windows_processed=20,
        peak_score=0.0,
        events=events,
    )

    prompt = build_narration_prompt(report)

    assert "Best-guess room brightness context: 96.2 lux." in prompt
    assert "someone was detected in the room" in prompt
    assert "Best-guess scene: present near the cot." in prompt
    assert "Never mention heart rate, breathing rate, or any vital sign." in prompt


def test_narration_excludes_radar_vitals_even_when_present() -> None:
    started = datetime(2026, 6, 28, tzinfo=UTC)
    events = (
        Event(
            kind="environment_sample",
            occurred_at=started + timedelta(seconds=2),
            offset_seconds=2.0,
            details={
                "radar_respiratory_rate": 16.0,
                "radar_heart_rate_bpm": 92.0,
                "person_present": True,
                "room_illuminance_lx": 80.0,
            },
        ),
    )
    report = NightReport(
        started_at=started,
        finished_at=started + timedelta(seconds=10),
        source="x",
        detector="x",
        threshold=0.4,
        sustained_seconds=1.0,
        windows_processed=1,
        peak_score=0.0,
        events=events,
    )

    facts = " ".join(
        line
        for line in build_narration_prompt(report).splitlines()
        if line.startswith("- ")
    ).lower()

    # Vital-sign values and words never enter the product narration facts.
    assert "92" not in facts
    assert "16" not in facts
    assert "heart" not in facts
    assert "respir" not in facts
    assert "breath" not in facts
    # Non-medical context is still present.
    assert "someone was detected" in facts
    assert "80 lux" in facts


def test_build_narration_prompt_summarises_other_sounds() -> None:
    started = datetime(2026, 6, 28, tzinfo=UTC)
    events = tuple(
        Event(
            kind="sound_observed",
            occurred_at=started + timedelta(seconds=offset),
            offset_seconds=float(offset),
            details={"sound": sound},
        )
        for offset, sound in ((2, "cooing"), (4, "cooing"), (6, "laughing"))
    )
    report = NightReport(
        started_at=started,
        finished_at=started + timedelta(seconds=10),
        source="x",
        detector="x",
        threshold=0.4,
        sustained_seconds=1.0,
        windows_processed=1,
        peak_score=0.0,
        events=events,
    )

    prompt = build_narration_prompt(report)

    assert "Other sounds heard: cooing 2 times, laughing 1 time." in prompt


def test_speak_uses_piper_and_supported_player(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    piper = tmp_path / "piper"
    model = tmp_path / "voice.onnx"
    piper.write_text("", encoding="utf-8")
    model.write_text("", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_which(command: str) -> str | None:
        return f"/usr/bin/{command}" if command == "aplay" else None

    def fake_run(command: list[str], **kwargs: object) -> object:
        commands.append(command)
        if command[0] == str(piper):
            output = Path(command[command.index("--output_file") + 1])
            output.write_bytes(b"RIFF")
        else:
            assert command[0] == "aplay"
            assert Path(command[1]).exists()
        return object()

    monkeypatch.setattr("beddington.narrator.shutil.which", fake_which)
    monkeypatch.setattr("beddington.narrator.subprocess.run", fake_run)

    result = speak(
        "Crying was detected once.",
        NarratorConfig(
            voice_enabled=True,
            piper_binary=str(piper),
            piper_model=str(model),
        ),
    )

    assert result == {"spoken": True, "engine": "piper", "player": "aplay"}
    assert commands[0][0] == str(piper)
    assert commands[1][0] == "aplay"


def test_speak_passes_speaker_only_for_multispeaker_voice(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    piper = tmp_path / "piper"
    model = tmp_path / "voice.onnx"
    piper.write_text("", encoding="utf-8")
    model.write_text("", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_which(command: str) -> str | None:
        return f"/usr/bin/{command}" if command == "aplay" else None

    def fake_run(command: list[str], **kwargs: object) -> object:
        commands.append(command)
        if command[0] == str(piper):
            Path(command[command.index("--output_file") + 1]).write_bytes(b"RIFF")
        return object()

    monkeypatch.setattr("beddington.narrator.shutil.which", fake_which)
    monkeypatch.setattr("beddington.narrator.subprocess.run", fake_run)

    base = dict(voice_enabled=True, piper_binary=str(piper), piper_model=str(model))
    # A multi-speaker voice with an id -> --speaker is passed.
    speak("hello", NarratorConfig(**base, piper_speaker="259"))
    assert "--speaker" in commands[0] and "259" in commands[0]
    # No speaker id -> no --speaker arg (single-speaker voices keep working).
    commands.clear()
    speak("hello", NarratorConfig(**base))
    assert "--speaker" not in commands[0]


def test_speak_translates_piper_speed_to_length_scale(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    piper = tmp_path / "piper"
    model = tmp_path / "voice.onnx"
    piper.write_text("", encoding="utf-8")
    model.write_text("", encoding="utf-8")
    commands: list[list[str]] = []

    def fake_which(command: str) -> str | None:
        return f"/usr/bin/{command}" if command == "aplay" else None

    def fake_run(command: list[str], **kwargs: object) -> object:
        commands.append(command)
        if command[0] == str(piper):
            Path(command[command.index("--output_file") + 1]).write_bytes(b"RIFF")
        return object()

    monkeypatch.setattr("beddington.narrator.shutil.which", fake_which)
    monkeypatch.setattr("beddington.narrator.subprocess.run", fake_run)

    speak(
        "hello",
        NarratorConfig(
            voice_enabled=True,
            piper_binary=str(piper),
            piper_model=str(model),
            piper_speed=0.85,
        ),
    )

    assert "--length_scale" in commands[0]
    scale = float(commands[0][commands[0].index("--length_scale") + 1])
    assert scale == pytest.approx(1 / 0.85)


def test_speak_degrades_when_binary_absent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("beddington.narrator.shutil.which", lambda command: None)

    result = speak(
        "Crying was detected once.",
        NarratorConfig(
            voice_enabled=True,
            piper_binary=str(tmp_path / "missing-piper"),
            piper_model=str(tmp_path / "missing-voice.onnx"),
        ),
    )

    assert result == {"spoken": False, "reason": "tts_engine_not_found"}


def test_narrator_config_does_not_change_pipeline_event_log(tmp_path: Path) -> None:
    scores = [0.1, 0.8, 0.9, 0.7, 0.1, 0.1]
    started_at = datetime(2026, 6, 28, tzinfo=UTC)
    base_config = AppConfig(
        detection=DetectionConfig(
            threshold=0.4,
            sustained_seconds=1.0,
            release_seconds=0.5,
            notification_cooldown_seconds=30.0,
        ),
        notifications=NotificationConfig(desktop=False),
    )
    narrator_config = AppConfig(
        detection=base_config.detection,
        notifications=base_config.notifications,
        narrator=NarratorConfig(enabled=True),
    )

    off = run_pipeline(
        source=FakeSource(scores),
        detector=FakeDetector(scores),
        notifier=FakeNotifier(),
        config=base_config,
        output_dir=tmp_path / "off",
        started_at=started_at,
    )
    on = run_pipeline(
        source=FakeSource(scores),
        detector=FakeDetector(scores),
        notifier=FakeNotifier(),
        config=narrator_config,
        output_dir=tmp_path / "on",
        started_at=started_at,
    )

    assert [event.to_dict() for event in on.report.events] == [
        event.to_dict() for event in off.report.events
    ]


def _sample_report() -> NightReport:
    started = datetime(2026, 6, 28, tzinfo=UTC)
    events = (
        Event(
            kind="cry_started",
            occurred_at=started + timedelta(seconds=1),
            offset_seconds=1.0,
            score=0.81,
        ),
        Event(
            kind="soothe_attempted",
            occurred_at=started + timedelta(seconds=2),
            offset_seconds=2.0,
            score=0.82,
            details={"name": "white noise"},
        ),
        Event(
            kind="environment_sample",
            occurred_at=started + timedelta(seconds=2),
            offset_seconds=2.0,
            details={
                "room_temperature_c": 20.5,
                "room_humidity_pct": 47.0,
                "motion_detected": True,
            },
        ),
        Event(
            kind="environment_sample",
            occurred_at=started + timedelta(seconds=4),
            offset_seconds=4.0,
            details={
                "room_temperature_c": 21.5,
                "room_humidity_pct": 48.2,
                "motion_detected": False,
            },
        ),
        Event(
            kind="cry_ended",
            occurred_at=started + timedelta(seconds=6),
            offset_seconds=6.0,
            score=0.12,
            duration_seconds=5.0,
        ),
        Event(
            kind="soothe_quiet_confirmed",
            occurred_at=started + timedelta(seconds=7),
            offset_seconds=7.0,
            score=0.1,
            details={"quiet_checks": 2},
        ),
        Event(
            kind="environment_sample",
            occurred_at=started + timedelta(seconds=8),
            offset_seconds=8.0,
            details={"motion_detected": True},
        ),
    )
    return NightReport(
        started_at=started,
        finished_at=started + timedelta(seconds=10),
        source="/private/recordings/raw.wav",
        detector="fake",
        threshold=0.4,
        sustained_seconds=1.0,
        windows_processed=20,
        peak_score=0.82,
        events=events,
    )


def _report_without_sensor_context() -> NightReport:
    started = datetime(2026, 6, 28, tzinfo=UTC)
    events = (
        Event(
            kind="cry_started",
            occurred_at=started + timedelta(seconds=1),
            offset_seconds=1.0,
            score=0.81,
        ),
        Event(
            kind="cry_ended",
            occurred_at=started + timedelta(seconds=6),
            offset_seconds=6.0,
            score=0.12,
            duration_seconds=5.0,
        ),
    )
    return NightReport(
        started_at=started,
        finished_at=started + timedelta(seconds=10),
        source="/private/recordings/raw.wav",
        detector="fake",
        threshold=0.4,
        sustained_seconds=1.0,
        windows_processed=20,
        peak_score=0.81,
        events=events,
    )
