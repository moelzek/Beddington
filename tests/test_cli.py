from __future__ import annotations

import json
import struct
from datetime import UTC, datetime

import pytest

from lullaby.cli import main
from lullaby.video import ImageInfo, VisualChangeReport


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

    monkeypatch.setattr("lullaby.cli.capture_rpicam_visual_change", fake_capture)

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
