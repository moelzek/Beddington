from __future__ import annotations

import json
import struct

import pytest

from lullaby.cli import main


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
