from __future__ import annotations

import json
import struct
import subprocess
from pathlib import Path

import pytest

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


def binary_pgm(width: int, height: int, values: bytes) -> bytes:
    assert len(values) == width * height
    return f"P5\n{width} {height}\n255\n".encode("ascii") + values


def bmp24(width: int, height: int, pixels: list[tuple[int, int, int]]) -> bytes:
    assert len(pixels) == width * height
    row_stride = ((width * 24 + 31) // 32) * 4
    pixel_bytes = bytearray()
    for row in range(height):
        row_values = pixels[row * width : (row + 1) * width]
        row_bytes = bytearray()
        for red, green, blue in row_values:
            row_bytes.extend([blue, green, red])
        row_bytes.extend(b"\x00" * (row_stride - len(row_bytes)))
        pixel_bytes.extend(row_bytes)
    file_size = 54 + len(pixel_bytes)
    return b"".join(
        (
            b"BM",
            file_size.to_bytes(4, "little"),
            b"\x00\x00\x00\x00",
            (54).to_bytes(4, "little"),
            (40).to_bytes(4, "little"),
            width.to_bytes(4, "little", signed=True),
            (-height).to_bytes(4, "little", signed=True),
            (1).to_bytes(2, "little"),
            (24).to_bytes(2, "little"),
            (0).to_bytes(4, "little"),
            len(pixel_bytes).to_bytes(4, "little"),
            (0).to_bytes(4, "little"),
            (0).to_bytes(4, "little"),
            (0).to_bytes(4, "little"),
            (0).to_bytes(4, "little"),
            bytes(pixel_bytes),
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


def test_compare_frames_reports_little_visual_change(tmp_path: Path) -> None:
    before = tmp_path / "before.pgm"
    after = tmp_path / "after.pgm"
    before.write_bytes(binary_pgm(2, 2, bytes([10, 10, 10, 10])))
    after.write_bytes(binary_pgm(2, 2, bytes([10, 10, 10, 10])))

    report = video.compare_frames(before, after)

    assert report.observation == "little_visual_change_detected"
    assert report.changed_pixel_ratio == 0.0
    assert report.mean_absolute_difference == 0.0
    assert "not a safety" in report.wording_note


def test_compare_frames_reports_visual_change(tmp_path: Path) -> None:
    before = tmp_path / "before.pgm"
    after = tmp_path / "after.pgm"
    before.write_bytes(binary_pgm(2, 2, bytes([0, 0, 0, 0])))
    after.write_bytes(binary_pgm(2, 2, bytes([255, 0, 255, 0])))

    report = video.compare_frames(
        before,
        after,
        pixel_threshold=0.5,
        changed_ratio_threshold=0.25,
    )

    assert report.observation == "visual_change_detected"
    assert report.changed_pixel_ratio == 0.5
    assert report.mean_absolute_difference == 0.5
    assert report.before.format == "PGM"
    assert report.after.format == "PGM"


def test_compare_frames_supports_bmp(tmp_path: Path) -> None:
    before = tmp_path / "before.bmp"
    after = tmp_path / "after.bmp"
    before.write_bytes(
        bmp24(2, 1, [(0, 0, 0), (0, 0, 0)])
    )
    after.write_bytes(
        bmp24(2, 1, [(255, 255, 255), (0, 0, 0)])
    )

    report = video.compare_frames(
        before,
        after,
        pixel_threshold=0.5,
        changed_ratio_threshold=0.25,
    )

    assert report.observation == "visual_change_detected"
    assert report.changed_pixel_ratio == 0.5
    assert report.before.format == "BMP"
    assert report.after.format == "BMP"
    assert report.before.height == 1
    assert report.after.height == 1


def test_compare_frames_rejects_mismatched_dimensions(tmp_path: Path) -> None:
    before = tmp_path / "before.pgm"
    after = tmp_path / "after.pgm"
    before.write_bytes(binary_pgm(2, 2, bytes([0, 0, 0, 0])))
    after.write_bytes(binary_pgm(1, 2, bytes([0, 0])))

    with pytest.raises(ValueError, match="Frame dimensions must match"):
        video.compare_frames(before, after)


def test_camera_visual_change_deletes_default_frames(
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
        if "before" in output.name:
            output.write_bytes(bmp24(2, 1, [(0, 0, 0), (0, 0, 0)]))
        else:
            output.write_bytes(bmp24(2, 1, [(255, 255, 255), (0, 0, 0)]))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="Still capture image received\n",
            stderr="WARNING: Capture will not make use of temporal denoise\n",
        )

    monkeypatch.setattr(video.subprocess, "run", fake_run)

    report = video.capture_rpicam_visual_change(
        tmp_path,
        width=2,
        height=1,
        interval_seconds=0.0,
        pixel_threshold=0.5,
        changed_ratio_threshold=0.25,
    )

    assert report.source == "rpicam-still-pair"
    assert report.observation == "visual_change_detected"
    assert report.changed_pixel_ratio == 0.5
    assert report.raw_frames_retained is False
    assert report.retained_frame_paths == ()
    assert report.before.path == "deleted temporary before frame"
    assert report.after.path == "deleted temporary after frame"
