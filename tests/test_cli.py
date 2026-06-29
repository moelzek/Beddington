from __future__ import annotations

import json
import struct
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from beddington.cli import (
    _AutoSootheWatcher,
    _format_sensor_line,
    _record_run_soothe_outcomes,
    main,
)
from beddington.config import SootheStepConfig
from beddington.logging import OutputPaths
from beddington.models import Event, NightReport
from beddington.sensor_store import SensorStore
from beddington.video import ImageInfo, VisualChangeReport


def test_format_sensor_line_combines_all_sensors() -> None:
    line = _format_sensor_line(
        {
            "room_temperature_c": 25.2,
            "room_humidity_pct": 50.0,
            "room_pressure_hpa": 1013.0,
            "room_gas_resistance_ohms": 123456,
            "person_present": True,
            "motion_detected": False,
            "room_illuminance_lx": 31.9,
            "target_distance_cm": 57.4,
            "target_count": 2,
            "radar_respiratory_rate": 18.0,
            "radar_heart_rate_bpm": 87.0,
        }
    )
    assert "25.2 C" in line
    assert "50% RH" in line
    assert "1013 hPa" in line
    assert "123 kohm gas" in line
    assert "present" in line
    assert "still" in line
    assert "31.9 lux" in line
    assert "87 bpm heart" in line
    assert "scene: settled near the cot" in line


def test_format_sensor_line_empty() -> None:
    assert _format_sensor_line({}) == "no readings yet"


@pytest.mark.parametrize("kind", ("soothe_quiet_confirmed", "soothe_settled"))
def test_record_run_soothe_outcomes_writes_success(
    tmp_path: Path,
    kind: str,
) -> None:
    attempted = datetime(2026, 6, 29, 20, 0, tzinfo=UTC)
    resolved = datetime(2026, 6, 29, 20, 1, tzinfo=UTC)
    db_path = tmp_path / "s.db"

    _record_run_soothe_outcomes(
        (
            Event(
                kind="soothe_attempted",
                occurred_at=attempted,
                offset_seconds=10.0,
                details={"name": "rain"},
            ),
            Event(kind=kind, occurred_at=resolved, offset_seconds=70.0),
        ),
        str(db_path),
    )

    store = SensorStore(str(db_path))
    assert store.outcomes_since(0.0) == [(resolved.timestamp(), "rain", True)]
    store.close()


def test_record_run_soothe_outcomes_writes_failure(tmp_path: Path) -> None:
    attempted = datetime(2026, 6, 29, 21, 0, tzinfo=UTC)
    resolved = datetime(2026, 6, 29, 21, 2, tzinfo=UTC)
    db_path = tmp_path / "s.db"

    _record_run_soothe_outcomes(
        (
            Event(
                kind="soothe_attempted",
                occurred_at=attempted,
                offset_seconds=10.0,
                details={"name": "pink-noise"},
            ),
            Event(kind="soothe_unresolved", occurred_at=resolved, offset_seconds=130.0),
        ),
        str(db_path),
    )

    store = SensorStore(str(db_path))
    assert store.outcomes_since(0.0) == [(resolved.timestamp(), "pink-noise", False)]
    store.close()


def _auto_soothe_config(learn_enabled: bool, min_samples: int) -> SimpleNamespace:
    return SimpleNamespace(
        soothe=SimpleNamespace(
            preset="rain",
            presets={
                "rain": SootheStepConfig(name="rain"),
                "waves": SootheStepConfig(name="waves"),
            },
            learn=SimpleNamespace(enabled=learn_enabled, min_samples=min_samples),
        )
    )


def _trigger_auto_soothe(watcher: _AutoSootheWatcher) -> str | None:
    watcher._state = {"enabled": True, "preset": "rain"}
    watcher._last_state = 10.0
    watcher._watcher = SimpleNamespace(observe=lambda _elapsed, _audio: True)
    return watcher.feed(np.zeros(15_600, dtype=np.float32), 10.0)


def _patch_auto_soothe_memory(
    monkeypatch: pytest.MonkeyPatch,
    db_path: Path,
) -> None:
    monkeypatch.setattr("beddington.cli._DEFAULT_HISTORY_DB", str(db_path))
    monkeypatch.setattr(
        "beddington.cli._build_soothe_presets",
        lambda config: config.soothe.presets,
    )


def test_auto_soothe_watcher_uses_best_preset_when_learning_has_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "history.db"
    store = SensorStore(str(db_path))
    store.append_soothe_outcome(1.0, "rain", True)
    store.append_soothe_outcome(2.0, "rain", False)
    store.append_soothe_outcome(3.0, "waves", True)
    store.append_soothe_outcome(4.0, "waves", True)
    store.close()
    _patch_auto_soothe_memory(monkeypatch, db_path)

    watcher = _AutoSootheWatcher(_auto_soothe_config(True, 2), 16_000, frame_ms=1000)

    assert _trigger_auto_soothe(watcher) == "waves"


def test_auto_soothe_watcher_keeps_configured_preset_when_learning_off(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "history.db"
    store = SensorStore(str(db_path))
    store.append_soothe_outcome(1.0, "rain", False)
    store.append_soothe_outcome(2.0, "rain", False)
    store.append_soothe_outcome(3.0, "waves", True)
    store.append_soothe_outcome(4.0, "waves", True)
    store.close()
    _patch_auto_soothe_memory(monkeypatch, db_path)

    watcher = _AutoSootheWatcher(_auto_soothe_config(False, 2), 16_000, frame_ms=1000)

    assert _trigger_auto_soothe(watcher) == "rain"


def test_auto_soothe_watcher_keeps_configured_preset_with_sparse_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "history.db"
    store = SensorStore(str(db_path))
    store.append_soothe_outcome(1.0, "waves", True)
    store.close()
    _patch_auto_soothe_memory(monkeypatch, db_path)

    watcher = _AutoSootheWatcher(_auto_soothe_config(True, 2), 16_000, frame_ms=1000)

    assert _trigger_auto_soothe(watcher) == "rain"


def test_preview_soothe_dry_run_uses_selected_preset(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = main(
        [
            "--config",
            "config/default.toml",
            "preview-soothe",
            "--dry-run",
            "--seconds",
            "0.1",
        ]
    )

    output = capsys.readouterr().out

    assert result == 0
    assert "Preset: white_noise (white noise)" in output
    assert "Dry run: dry_run" in output


def test_preview_soothe_rejects_non_positive_seconds() -> None:
    with pytest.raises(SystemExit, match="--seconds must be positive"):
        main(
            [
                "--config",
                "config/default.toml",
                "preview-soothe",
                "--dry-run",
                "--seconds",
                "0",
            ]
        )


def test_preview_soothe_rejects_unknown_preset() -> None:
    with pytest.raises(SystemExit, match="Unknown soothe preset"):
        main(
            [
                "--config",
                "config/default.toml",
                "preview-soothe",
                "--dry-run",
                "--preset",
                "rain",
            ]
        )


def test_analyze_passes_configured_sensor_readers(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[sensors]
sample_interval_seconds = 2.0

[sensors.motion]
enabled = true
gpio_pin = 4
""",
        encoding="utf-8",
    )
    wav_path = tmp_path / "sample.wav"
    wav_path.write_bytes(b"RIFF")
    readers = [object()]
    captured = {}

    def fake_build_sensor_readers(sensors_config):
        assert sensors_config.motion.enabled is True
        assert sensors_config.motion.gpio_pin == 4
        return readers

    def fake_run_pipeline(**kwargs):
        captured.update(kwargs)
        started = datetime(2026, 6, 28, tzinfo=UTC)
        report = NightReport(
            started_at=started,
            finished_at=started + timedelta(seconds=1),
            source="fake.wav",
            detector="fake",
            threshold=0.4,
            sustained_seconds=1.5,
            windows_processed=0,
            peak_score=0.0,
            events=(),
        )
        return SimpleNamespace(
            report=report,
            digest="digest",
            paths=OutputPaths(
                events_json=tmp_path / "events.json",
                readable_log=tmp_path / "night-log.txt",
                digest=tmp_path / "morning-digest.txt",
            ),
        )

    monkeypatch.setattr("beddington.cli.YamNetTFLiteDetector", lambda model: object())
    monkeypatch.setattr("beddington.cli.WavFileAudioSource", lambda path: object())
    monkeypatch.setattr("beddington.cli.build_sensor_readers", fake_build_sensor_readers)
    monkeypatch.setattr("beddington.cli.run_pipeline", fake_run_pipeline)

    result = main(
        [
            "--config",
            str(config_path),
            "analyze",
            str(wav_path),
            "--output",
            str(tmp_path / "output"),
        ]
    )

    assert result == 0
    assert captured["sensor_readers"] is readers
    assert captured["config"].sensors.sample_interval_seconds == 2.0
    assert "digest" in capsys.readouterr().out


def test_analyze_records_soothe_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")
    wav_path = tmp_path / "sample.wav"
    wav_path.write_bytes(b"RIFF")
    history_db = tmp_path / "history.db"

    def fake_run_pipeline(**kwargs):
        started = datetime(2026, 6, 29, 22, 0, tzinfo=UTC)
        resolved = started + timedelta(seconds=90)
        report = NightReport(
            started_at=started,
            finished_at=resolved,
            source="fake.wav",
            detector="fake",
            threshold=0.4,
            sustained_seconds=1.5,
            windows_processed=0,
            peak_score=0.0,
            events=(
                Event(
                    kind="soothe_attempted",
                    occurred_at=started,
                    offset_seconds=0.0,
                    details={"name": "rain"},
                ),
                Event(
                    kind="soothe_unresolved",
                    occurred_at=resolved,
                    offset_seconds=90.0,
                ),
            ),
        )
        return SimpleNamespace(
            report=report,
            digest="digest",
            paths=OutputPaths(
                events_json=tmp_path / "events.json",
                readable_log=tmp_path / "night-log.txt",
                digest=tmp_path / "morning-digest.txt",
            ),
        )

    monkeypatch.setattr("beddington.cli.YamNetTFLiteDetector", lambda model: object())
    monkeypatch.setattr("beddington.cli.WavFileAudioSource", lambda path: object())
    monkeypatch.setattr("beddington.cli.build_sensor_readers", lambda config: ())
    monkeypatch.setattr("beddington.cli.run_pipeline", fake_run_pipeline)

    result = main(
        [
            "--config",
            str(config_path),
            "analyze",
            str(wav_path),
            "--history-db",
            str(history_db),
            "--output",
            str(tmp_path / "output"),
        ]
    )

    store = SensorStore(str(history_db))
    assert result == 0
    assert store.outcomes_since(0.0) == [
        (datetime(2026, 6, 29, 22, 1, 30, tzinfo=UTC).timestamp(), "rain", False)
    ]
    store.close()


def test_camera_smoke_image_mode_writes_derived_report(tmp_path, capsys) -> None:
    image = tmp_path / "frame.png"
    image.write_bytes(
        b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 123, 45)
    )
    output_dir = tmp_path / "camera-output"

    result = main(
        [
            "--config",
            "config/default.toml",
            "camera-smoke",
            "--image",
            str(image),
            "--output",
            str(output_dir),
        ]
    )

    output = capsys.readouterr().out
    report = json.loads((output_dir / "camera-smoke.json").read_text(encoding="utf-8"))

    assert result == 0
    assert "Camera smoke source: image-file" in output
    assert "Image metadata: PNG 123x45" in output
    assert report["image"]["width"] == 123
    assert report["image"]["height"] == 45
    assert "Raw camera frames stay local" in report["privacy_note"]


def test_camera_smoke_rejects_invalid_dimensions() -> None:
    with pytest.raises(SystemExit, match="--width and --height must be positive"):
        main(
            [
                "--config",
                "config/default.toml",
                "camera-smoke",
                "--width",
                "0",
            ]
        )


def test_visual_change_writes_derived_report(tmp_path, capsys) -> None:
    before = tmp_path / "before.pgm"
    after = tmp_path / "after.pgm"
    before.write_bytes(b"P5\n2 2\n255\n" + bytes([0, 0, 0, 0]))
    after.write_bytes(b"P5\n2 2\n255\n" + bytes([255, 0, 255, 0]))
    output_dir = tmp_path / "visual-output"

    result = main(
        [
            "--config",
            "config/default.toml",
            "visual-change",
            "--before",
            str(before),
            "--after",
            str(after),
            "--output",
            str(output_dir),
            "--pixel-threshold",
            "0.5",
            "--changed-ratio-threshold",
            "0.25",
        ]
    )

    output = capsys.readouterr().out
    report = json.loads((output_dir / "visual-change.json").read_text(encoding="utf-8"))

    assert result == 0
    assert "Observation: visual_change_detected" in output
    assert report["changed_pixel_ratio"] == 0.5
    assert report["observation"] == "visual_change_detected"
    assert "not a safety" in report["wording_note"]


def test_camera_change_writes_derived_report(tmp_path, capsys, monkeypatch) -> None:
    def fake_capture(output_dir, **kwargs):
        assert output_dir == tmp_path / "camera-change-output"
        assert kwargs["keep_frames"] is False
        return VisualChangeReport(
            analysed_at=datetime(2026, 6, 23, tzinfo=UTC),
            before=ImageInfo("deleted temporary before frame", "BMP", 2, 1, 62),
            after=ImageInfo("deleted temporary after frame", "BMP", 2, 1, 62),
            mean_absolute_difference=0.5,
            changed_pixel_ratio=0.5,
            pixel_threshold=0.5,
            changed_ratio_threshold=0.25,
            observation="visual_change_detected",
            source="rpicam-still-pair",
            raw_frames_retained=False,
            camera_summary="0 : imx708 [4608x2592 10-bit RGGB]",
        )

    monkeypatch.setattr("beddington.cli.capture_rpicam_visual_change", fake_capture)

    result = main(
        [
            "--config",
            "config/default.toml",
            "camera-change",
            "--output",
            str(tmp_path / "camera-change-output"),
            "--pixel-threshold",
            "0.5",
            "--changed-ratio-threshold",
            "0.25",
        ]
    )

    output = capsys.readouterr().out
    report = json.loads(
        (tmp_path / "camera-change-output" / "visual-change.json").read_text(
            encoding="utf-8"
        )
    )

    assert result == 0
    assert "Observation: visual_change_detected" in output
    assert "Raw camera frames deleted" in output
    assert report["source"] == "rpicam-still-pair"
    assert report["raw_frames_retained"] is False
    assert report["before"]["path"] == "deleted temporary before frame"
