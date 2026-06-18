from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from lullaby.config import AppConfig, DetectionConfig, NotificationConfig
from lullaby.models import AudioWindow
from lullaby.pipeline import run_pipeline


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
        assert title == "Lullaby"
        assert "Sustained crying" in message
        self.calls += 1
        return {"console": True, "desktop": False}


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
