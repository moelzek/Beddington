from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from beddington.logging import write_outputs
from beddington.models import Event, NightReport
from beddington.radar_vitals import (
    format_radar_reading,
    summarise_radar_vitals,
    summarise_radar_vitals_from_events,
)


def _report_with(details: dict) -> NightReport:
    started = datetime(2026, 6, 28, tzinfo=UTC)
    return NightReport(
        started_at=started,
        finished_at=started + timedelta(seconds=10),
        source="x",
        detector="x",
        threshold=0.4,
        sustained_seconds=1.0,
        windows_processed=1,
        peak_score=0.0,
        events=(
            Event(
                kind="environment_sample",
                occurred_at=started + timedelta(seconds=2),
                offset_seconds=2.0,
                details=details,
            ),
        ),
    )


def test_summarise_returns_none_without_vitals() -> None:
    samples = [{"person_present": True, "room_illuminance_lx": 80.0}]
    assert summarise_radar_vitals(samples) is None


def test_summarise_labels_and_reports_vitals() -> None:
    samples = [
        {"radar_respiratory_rate": 16.0, "radar_heart_rate_bpm": 90.0},
        {"radar_respiratory_rate": 18.0, "radar_heart_rate_bpm": 100.0},
    ]

    out = summarise_radar_vitals(samples)

    assert out is not None
    assert "breathing rate averaged 17 per minute" in out
    assert "heart rate averaged 95 beats per minute" in out
    assert "range 16 to 18" in out
    assert "range 90 to 100" in out
    # Never paired with reassurance about the baby. Tokenise into whole words.
    words = set(re.findall(r"[a-z]+", out.lower()))
    for word in ("safe", "fine", "healthy", "asleep", "normal", "ok", "wellbeing"):
        assert word not in words


def test_format_reading_labels_fields() -> None:
    line = format_radar_reading(
        {
            "person_present": True,
            "room_illuminance_lx": 80.0,
            "radar_heart_rate_bpm": 92.0,
        }
    )
    assert "present" in line
    assert "80 lux" in line
    assert "92 bpm" in line


def test_format_reading_shows_vital_without_disclaimer() -> None:
    with_vital = format_radar_reading(
        {"person_present": True, "radar_heart_rate_bpm": 92.0}
    )
    # The vital reading itself is present, with no medical/bench-data disclaimer.
    assert "92 bpm" in with_vital
    assert "not a medical" not in with_vital.lower()
    assert "bench data" not in with_vital.lower()


def test_format_reading_handles_empty() -> None:
    assert format_radar_reading({}) == "no radar data yet"


def test_events_json_captures_vitals_without_disclaimer(tmp_path: Path) -> None:
    report = _report_with({"radar_heart_rate_bpm": 90.0, "radar_respiratory_rate": 16.0})

    paths = write_outputs(tmp_path / "out", report, "digest text")
    data = json.loads(paths.events_json.read_text(encoding="utf-8"))

    # No medical disclaimer key, but the captured vitals are still persisted.
    assert "radar_vitals_disclaimer" not in data
    sample = next(
        event for event in data["events"] if event["kind"] == "environment_sample"
    )
    assert sample["details"]["radar_heart_rate_bpm"] == 90.0
    assert sample["details"]["radar_respiratory_rate"] == 16.0


def test_events_json_has_no_disclaimer_without_vitals(tmp_path: Path) -> None:
    report = _report_with({"person_present": True, "room_illuminance_lx": 80.0})

    paths = write_outputs(tmp_path / "out", report, "digest text")
    data = json.loads(paths.events_json.read_text(encoding="utf-8"))

    assert "radar_vitals_disclaimer" not in data


def test_summarise_ignores_nan_vitals() -> None:
    samples = [
        {"radar_heart_rate_bpm": float("nan")},
        {"radar_heart_rate_bpm": 90.0},
    ]

    out = summarise_radar_vitals(samples)

    assert out is not None
    assert "heart rate averaged 90 beats per minute" in out
    assert "1 sample" in out


def test_summarise_from_events() -> None:
    started = datetime(2026, 6, 28, tzinfo=UTC)
    events = (
        Event(
            kind="environment_sample",
            occurred_at=started,
            offset_seconds=0.0,
            details={"radar_heart_rate_bpm": 90.0, "radar_respiratory_rate": 16.0},
        ),
        Event(
            kind="cry_started",
            occurred_at=started + timedelta(seconds=1),
            offset_seconds=1.0,
            score=0.8,
        ),
    )

    out = summarise_radar_vitals_from_events(events)

    assert out is not None
    assert "heart rate averaged 90 beats per minute" in out
