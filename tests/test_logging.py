from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from beddington.logging import write_outputs
from beddington.models import Event, NightReport


def test_readable_log_renders_soothe_and_sensor_faults(tmp_path: Path) -> None:
    started = datetime(2026, 6, 18, tzinfo=UTC)
    report = NightReport(
        started_at=started,
        finished_at=started + timedelta(seconds=10),
        source="night.wav",
        detector="fake",
        threshold=0.25,
        sustained_seconds=1.5,
        windows_processed=9,
        peak_score=0.8,
        events=(
            Event(
                kind="soothe_attempted",
                occurred_at=started,
                offset_seconds=0.0,
                details={
                    "name": "rain",
                    "wait_seconds": 30.0,
                    "play_seconds": 60.0,
                    "playback": {
                        "played": False,
                        "reason": "sound_path_not_found",
                    },
                },
            ),
            Event(
                kind="soothe_unavailable",
                occurred_at=started,
                offset_seconds=0.0,
                details={"name": "rain", "reason": "sound_path_not_found"},
            ),
            Event(
                kind="soothe_switch_failed",
                occurred_at=started + timedelta(seconds=5),
                offset_seconds=5.0,
                details={
                    "from": "rain",
                    "to": "waves",
                    "playback": {"played": False, "reason": "backend_failed"},
                },
            ),
            Event(
                kind="sensor_unavailable",
                occurred_at=started + timedelta(seconds=6),
                offset_seconds=6.0,
                details={
                    "failures": [
                        {"reader": "BME688", "error": "not found"},
                    ],
                },
            ),
        ),
    )

    paths = write_outputs(tmp_path, report, "digest text")
    text = paths.readable_log.read_text(encoding="utf-8")

    assert "dry run" not in text
    assert "not played: sound_path_not_found" in text
    assert "FAULT       soothe unavailable for rain: sound_path_not_found" in text
    assert "FAULT       soothe switch failed rain -> waves: backend_failed" in text
    assert "FAULT       sensor unavailable BME688: not found" in text
