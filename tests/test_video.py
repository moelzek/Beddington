from __future__ import annotations

import json
import struct
import subprocess
from pathlib import Path

from lullaby import video


def minimal_png(width: int, height: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(
        ">II", width, height
    )


def minimal_jpeg(width: int, height: int) -> bytes:
    return b"".join(
        (
            b"\xff\xd8",
            b"\xff\xe0\x00\x04JF",
            b"\xff\xc0\x00\x11\x08",
            height.to_bytes(2, "big"),
            width.to_bytes(2, "big"),
            b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00",
            b"\xff\xd9",
        )
    )


def test_inspect_png_metadata_without_raw_pixels(tmp_path: Path) -> None:
    image = tmp_path / "frame.png"
    image.write_bytes(minimal_png(320, 240))

    info = video.inspect_image(image)

    assert info.format == "PNG"
    assert info.width == 320
    assert info.height == 240
    assert info.byte_count == image.stat().st_size


def test_inspect_jpeg_metadata_without_raw_pixels(tmp_path: Path) -> None:
    image = tmp_path / "frame.jpg"
    image.write_bytes(minimal_jpeg(640, 480))

    info = video.inspect_image(image)

    assert info.format == "JPEG"
    assert info.width == 640
    assert info.height == 480


def test_rpicam_capture_deletes_default_test_frame(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fake_run(command, capture_output, text, check):
        assert capture_output is True
        assert text is True
        assert check is False
        if command[0] == "rpicam-hello":
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="0 : imx708 [4608x2592 10-bit RGGB]\n",
                stderr="",
            )
        output = Path(command[command.index("--output") + 1])
        metadata = Path(command[command.index("--metadata") + 1])
        output.write_bytes(minimal_jpeg(640, 480))
        metadata.write_text(
            json.dumps({"SensorTimestamp": 1, "ExposureTime": 1000}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="Still capture image received\n",
            stderr="WARNING: Capture will not make use of temporal denoise\n",
        )

    monkeypatch.setattr(video.subprocess, "run", fake_run)

    report = video.capture_rpicam_still(tmp_path)

    assert report.source == "rpicam-still"
    assert report.camera_summary == "0 : imx708 [4608x2592 10-bit RGGB]"
    assert report.image.width == 640
    assert report.image.height == 480
    assert report.image.path == "deleted temporary frame"
    assert report.raw_frame_retained is False
    assert "SensorTimestamp" in report.metadata_keys
    assert report.warnings
