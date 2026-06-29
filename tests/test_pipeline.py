from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from beddington.config import (
    AppConfig,
    DetectionConfig,
    NotificationConfig,
    QuietCheckConfig,
    SensorsConfig,
    SootheConfig,
    SootheStepConfig,
    SoundsConfig,
    load_config,
)
from beddington.models import AudioWindow
from beddington.pipeline import run_pipeline


@dataclass
class FakeSource:
    scores: list[float]
    name: str = "fake.wav"

    @property
    def duration_seconds(self) -> float:
        return len(self.scores) * 0.4875 + 0.975

    def windows(self) -> Iterator[AudioWindow]:
        for index in range(len(self.scores)):
            yield AudioWindow(index * 0.4875, np.zeros(15_600, dtype=np.float32))


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


class FakeSoothePlayer:
    def __init__(self) -> None:
        self.steps: list[str] = []
        self.pause_calls = 0
        self.resume_steps: list[str] = []
        self.stop_calls = 0

    def play(self, step: SootheStepConfig) -> dict[str, object]:
        self.steps.append(step.name)
        return {"played": True, "player": "fake", "play_seconds": step.play_seconds}

    def pause_for_listen(self) -> dict[str, object]:
        self.pause_calls += 1
        return {"paused": True, "player": "fake"}

    def resume(self, step: SootheStepConfig) -> dict[str, object]:
        self.resume_steps.append(step.name)
        return {"resumed": True, "player": "fake"}

    def stop_all(self) -> None:
        self.stop_calls += 1


def test_pipeline_writes_events_log_and_digest(tmp_path: Path) -> None:
    scores = [0.1, 0.8, 0.9, 0.7, 0.1, 0.1]
    notifier = FakeNotifier()
    config = AppConfig(
        detection=DetectionConfig(
            threshold=0.4,
            sustained_seconds=1.0,
            release_seconds=0.5,
            notification_cooldown_seconds=30.0,
        ),
        notifications=NotificationConfig(desktop=False),
    )

    result = run_pipeline(
        source=FakeSource(scores),
        detector=FakeDetector(scores),
        notifier=notifier,
        config=config,
        output_dir=tmp_path,
        started_at=datetime(2026, 6, 18, tzinfo=UTC),
    )

    assert notifier.calls == 1
    assert result.paths.events_json.exists()
    assert result.paths.readable_log.exists()
    assert result.paths.digest.exists()
    assert "1 sustained crying episode" in result.digest
    payload = json.loads(result.paths.events_json.read_text())
    assert [event["kind"] for event in payload["events"]] == [
        "cry_started",
        "notification_sent",
        "cry_ended",
    ]


def test_selected_soothe_preset_runs_before_notification(tmp_path: Path) -> None:
    scores = [0.8, 0.9, 0.7, 0.1, 0.1]
    notifier = FakeNotifier()
    soothe_player = FakeSoothePlayer()
    config = AppConfig(
        detection=DetectionConfig(
            threshold=0.4,
            sustained_seconds=1.0,
            release_seconds=0.5,
            notification_cooldown_seconds=30.0,
        ),
        notifications=NotificationConfig(desktop=False),
        soothe=SootheConfig(
            enabled=True,
            player="none",
            steps=(
                SootheStepConfig(
                    name="white noise",
                    wait_seconds=0.0,
                    play_seconds=1800.0,
                ),
            ),
        ),
    )

    result = run_pipeline(
        source=FakeSource(scores),
        detector=FakeDetector(scores),
        notifier=notifier,
        config=config,
        output_dir=tmp_path,
        started_at=datetime(2026, 6, 18, tzinfo=UTC),
        soothe_player=soothe_player,
    )

    assert notifier.calls == 1
    assert soothe_player.steps == ["white noise"]
    assert [event.kind for event in result.report.events] == [
        "cry_started",
        "soothe_attempted",
        "notification_sent",
        "cry_ended",
    ]
    assert result.report.events[1].details["play_seconds"] == 1800.0
    assert "tried 1 soothe preset" in result.digest


def test_selected_soothe_preset_notifies_after_wait_when_crying_persists(
    tmp_path: Path,
) -> None:
    scores = [0.8, 0.9, 0.8, 0.8, 0.8, 0.1, 0.1]
    notifier = FakeNotifier()
    soothe_player = FakeSoothePlayer()
    config = AppConfig(
        detection=DetectionConfig(
            threshold=0.4,
            sustained_seconds=1.0,
            release_seconds=0.5,
            notification_cooldown_seconds=30.0,
        ),
        notifications=NotificationConfig(desktop=False),
        soothe=SootheConfig(
            enabled=True,
            player="none",
            steps=(SootheStepConfig(name="white noise", wait_seconds=1.0),),
        ),
    )

    result = run_pipeline(
        source=FakeSource(scores),
        detector=FakeDetector(scores),
        notifier=notifier,
        config=config,
        output_dir=tmp_path,
        started_at=datetime(2026, 6, 18, tzinfo=UTC),
        soothe_player=soothe_player,
    )

    assert notifier.calls == 1
    assert soothe_player.steps == ["white noise"]
    assert soothe_player.stop_calls >= 1
    assert [event.kind for event in result.report.events] == [
        "cry_started",
        "soothe_attempted",
        "notification_sent",
        "cry_ended",
    ]
    soothe_event = result.report.events[1]
    notification = result.report.events[2]
    assert notification.offset_seconds >= (
        soothe_event.offset_seconds + soothe_event.details["wait_seconds"]
    )


def test_selected_soothe_preset_suppresses_notification_when_crying_settles(
    tmp_path: Path,
) -> None:
    scores = [0.8, 0.9, 0.1, 0.1]
    notifier = FakeNotifier()
    config = AppConfig(
        detection=DetectionConfig(
            threshold=0.4,
            sustained_seconds=1.0,
            release_seconds=0.5,
            notification_cooldown_seconds=30.0,
        ),
        notifications=NotificationConfig(desktop=False),
        soothe=SootheConfig(
            enabled=True,
            player="none",
            min_play_seconds=0.0,
            hold_after_stop_seconds=0.0,
            steps=(SootheStepConfig(name="white noise", wait_seconds=10.0),),
        ),
    )

    result = run_pipeline(
        source=FakeSource(scores),
        detector=FakeDetector(scores),
        notifier=notifier,
        config=config,
        output_dir=tmp_path,
        started_at=datetime(2026, 6, 18, tzinfo=UTC),
        soothe_player=FakeSoothePlayer(),
    )

    assert notifier.calls == 0
    assert [event.kind for event in result.report.events] == [
        "cry_started",
        "soothe_attempted",
        "cry_ended",
        "soothe_settled",
    ]
    assert result.report.events[3].details == {
        "reason": "crying_settled_before_notification"
    }


def test_pi_product_soothe_plays_continuously_and_tracks_crying(
    tmp_path: Path,
) -> None:
    scores = [0.8] * 36 + [0.1] * 4
    notifier = FakeNotifier()
    soothe_player = FakeSoothePlayer()
    config = load_config(Path("config/pi-product.toml"))

    result = run_pipeline(
        source=FakeSource(scores),
        detector=FakeDetector(scores),
        notifier=notifier,
        config=config,
        output_dir=tmp_path,
        started_at=datetime(2026, 6, 18, tzinfo=UTC),
        soothe_player=soothe_player,
    )

    kinds = [event.kind for event in result.report.events]
    assert notifier.calls == 0
    assert soothe_player.steps == ["white noise"]
    assert soothe_player.pause_calls == 0
    assert "cry_started" in kinds
    assert "cry_ended" in kinds
    assert "soothe_quiet_check_started" not in kinds
    assert "soothe_quiet_check" not in kinds


def test_quiet_check_requires_repeated_quiet_before_resolving(
    tmp_path: Path,
) -> None:
    scores = [0.8, 0.9, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]
    notifier = FakeNotifier()
    soothe_player = FakeSoothePlayer()
    config = AppConfig(
        detection=DetectionConfig(
            threshold=0.4,
            sustained_seconds=1.0,
            release_seconds=10.0,
            notification_cooldown_seconds=30.0,
        ),
        notifications=NotificationConfig(desktop=False),
        soothe=SootheConfig(
            enabled=True,
            player="none",
            min_play_seconds=0.0,
            steps=(SootheStepConfig(name="white noise", wait_seconds=10.0),),
            quiet_check=QuietCheckConfig(
                enabled=True,
                check_interval_seconds=0.5,
                listen_seconds=0.4,
                required_checks=2,
            ),
        ),
    )

    result = run_pipeline(
        source=FakeSource(scores),
        detector=FakeDetector(scores),
        notifier=notifier,
        config=config,
        output_dir=tmp_path,
        started_at=datetime(2026, 6, 18, tzinfo=UTC),
        soothe_player=soothe_player,
    )

    kinds = [event.kind for event in result.report.events]
    assert notifier.calls == 0
    assert soothe_player.pause_calls == 2
    assert soothe_player.resume_steps == ["white noise"]
    assert soothe_player.stop_calls >= 1
    assert kinds.count("soothe_quiet_check") == 2
    assert "soothe_quiet_confirmed" in kinds
    assert "notification_sent" not in kinds

    log_text = result.paths.readable_log.read_text(encoding="utf-8")
    digest = result.paths.digest.read_text(encoding="utf-8")
    assert "crying no longer detected after 2 quiet checks" in log_text
    assert log_text.count("crying no longer detected") == 1
    for banned in ("baby is safe", "asleep", "settled to sleep", "fine"):
        assert banned not in log_text.lower()
        assert banned not in digest.lower()


def test_quiet_check_does_not_resolve_after_one_quiet_window(
    tmp_path: Path,
) -> None:
    scores = [0.8, 0.9, 0.1, 0.1]
    notifier = FakeNotifier()
    soothe_player = FakeSoothePlayer()
    config = AppConfig(
        detection=DetectionConfig(
            threshold=0.4,
            sustained_seconds=1.0,
            release_seconds=10.0,
            notification_cooldown_seconds=30.0,
        ),
        notifications=NotificationConfig(desktop=False),
        soothe=SootheConfig(
            enabled=True,
            player="none",
            steps=(SootheStepConfig(name="white noise", wait_seconds=10.0),),
            quiet_check=QuietCheckConfig(
                enabled=True,
                check_interval_seconds=0.5,
                listen_seconds=0.4,
                required_checks=2,
            ),
        ),
    )

    result = run_pipeline(
        source=FakeSource(scores),
        detector=FakeDetector(scores),
        notifier=notifier,
        config=config,
        output_dir=tmp_path,
        started_at=datetime(2026, 6, 18, tzinfo=UTC),
        soothe_player=soothe_player,
    )

    assert notifier.calls == 0
    assert "soothe_quiet_confirmed" not in [
        event.kind for event in result.report.events
    ]
    assert [event.kind for event in result.report.events][-2:] == [
        "soothe_unresolved",
        "cry_ended",
    ]


def test_quiet_check_failure_notifies_and_stops_playback(
    tmp_path: Path,
) -> None:
    scores = [0.8, 0.9, 0.8, 0.8, 0.8, 0.8, 0.8]
    notifier = FakeNotifier()
    soothe_player = FakeSoothePlayer()
    config = AppConfig(
        detection=DetectionConfig(
            threshold=0.4,
            sustained_seconds=1.0,
            release_seconds=10.0,
            notification_cooldown_seconds=30.0,
        ),
        notifications=NotificationConfig(desktop=False),
        soothe=SootheConfig(
            enabled=True,
            player="none",
            steps=(SootheStepConfig(name="white noise", wait_seconds=2.0),),
            quiet_check=QuietCheckConfig(
                enabled=True,
                check_interval_seconds=0.5,
                listen_seconds=0.4,
                required_checks=2,
            ),
        ),
    )

    result = run_pipeline(
        source=FakeSource(scores),
        detector=FakeDetector(scores),
        notifier=notifier,
        config=config,
        output_dir=tmp_path,
        started_at=datetime(2026, 6, 18, tzinfo=UTC),
        soothe_player=soothe_player,
    )

    quiet_checks = [
        event
        for event in result.report.events
        if event.kind == "soothe_quiet_check"
    ]

    assert notifier.calls == 1
    assert soothe_player.pause_calls >= 1
    assert soothe_player.stop_calls >= 1
    assert quiet_checks
    assert quiet_checks[0].details["result"] == "crying_detected"
    assert "notification_sent" in [event.kind for event in result.report.events]


def test_soothe_unresolved_when_recording_ends_before_wait(tmp_path: Path) -> None:
    scores = [0.8, 0.9]
    notifier = FakeNotifier()
    soothe_player = FakeSoothePlayer()
    config = AppConfig(
        detection=DetectionConfig(
            threshold=0.4,
            sustained_seconds=1.0,
            release_seconds=0.5,
            notification_cooldown_seconds=30.0,
        ),
        notifications=NotificationConfig(desktop=False),
        soothe=SootheConfig(
            enabled=True,
            player="none",
            steps=(SootheStepConfig(name="white noise", wait_seconds=10.0),),
        ),
    )

    result = run_pipeline(
        source=FakeSource(scores),
        detector=FakeDetector(scores),
        notifier=notifier,
        config=config,
        output_dir=tmp_path,
        started_at=datetime(2026, 6, 18, tzinfo=UTC),
        soothe_player=soothe_player,
    )

    assert notifier.calls == 0
    assert soothe_player.stop_calls == 1
    assert [event.kind for event in result.report.events] == [
        "cry_started",
        "soothe_attempted",
        "soothe_unresolved",
        "cry_ended",
    ]
    assert result.report.events[2].details == {
        "reason": "recording_ended_before_escalation"
    }


def test_pipeline_records_non_cry_sounds(tmp_path: Path) -> None:
    scores = [0.1, 0.1, 0.1, 0.1]
    config = AppConfig(
        detection=DetectionConfig(
            threshold=0.4,
            sustained_seconds=1.0,
            release_seconds=0.5,
            notification_cooldown_seconds=30.0,
        ),
        sensors=SensorsConfig(sample_interval_seconds=0.5),
        sounds=SoundsConfig(enabled=True, threshold=0.2),
    )

    def classifier(samples: np.ndarray) -> dict[str, float]:
        del samples
        return {"crying": 0.9, "cooing": 0.6, "snoring": 0.05}

    result = run_pipeline(
        source=FakeSource(scores),
        detector=FakeDetector(scores),
        notifier=FakeNotifier(),
        config=config,
        output_dir=tmp_path,
        started_at=datetime(2026, 6, 28, tzinfo=UTC),
        sound_classifier=classifier,
    )

    sounds = [e for e in result.report.events if e.kind == "sound_observed"]
    assert sounds
    # Crying is excluded (it has its own detector); cooing is the recorded sound.
    assert all(event.details["sound"] == "cooing" for event in sounds)
