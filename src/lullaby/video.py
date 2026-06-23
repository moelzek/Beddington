from __future__ import annotations

import json
import struct
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PRIVACY_NOTE = (
    "Raw camera frames stay local. The default camera smoke test deletes the "
    "test image after recording derived metadata."
)


@dataclass(frozen=True)
class ImageInfo:
    path: str
    format: str
    width: int
    height: int
    byte_count: int


@dataclass(frozen=True)
class CameraSmokeReport:
    captured_at: datetime
    source: str
    image: ImageInfo
    raw_frame_retained: bool
    retained_frame_path: str | None = None
    camera_summary: str | None = None
    metadata_keys: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    privacy_note: str = PRIVACY_NOTE

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["schema_version"] = 1
        value["captured_at"] = self.captured_at.isoformat()
        return value


def inspect_image(path: Path) -> ImageInfo:
    """Return derived image metadata without decoding or storing raw pixels."""

    if not path.exists():
        raise FileNotFoundError(f"Image not found: {path}")
    data = path.read_bytes()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        width, height = _png_dimensions(data)
        format_name = "PNG"
    elif data.startswith(b"\xff\xd8"):
        width, height = _jpeg_dimensions(data)
        format_name = "JPEG"
    else:
        raise ValueError(f"Unsupported image format: {path}")
    return ImageInfo(
        path=str(path),
        format=format_name,
        width=width,
        height=height,
        byte_count=len(data),
    )


def inspect_image_file(path: Path) -> CameraSmokeReport:
    info = inspect_image(path)
    return CameraSmokeReport(
        captured_at=datetime.now(UTC),
        source="image-file",
        image=info,
        raw_frame_retained=True,
        retained_frame_path=str(path),
    )


def capture_rpicam_still(
    output_dir: Path,
    *,
    width: int = 640,
    height: int = 480,
    timeout_seconds: float = 1.0,
    keep_frame: bool = False,
    rpicam_still: str = "rpicam-still",
    rpicam_hello: str = "rpicam-hello",
) -> CameraSmokeReport:
    if width <= 0 or height <= 0:
        raise ValueError("Camera smoke width and height must be positive")
    if timeout_seconds <= 0:
        raise ValueError("Camera smoke timeout must be positive")

    output_dir.mkdir(parents=True, exist_ok=True)
    camera_summary = _list_rpicam_camera(rpicam_hello)
    warnings: list[str] = []

    if keep_frame:
        image_path = output_dir / "camera-smoke.jpg"
        metadata_path = output_dir / "camera-smoke-metadata.json"
        report = _capture_to_paths(
            image_path,
            metadata_path,
            width=width,
            height=height,
            timeout_seconds=timeout_seconds,
            rpicam_still=rpicam_still,
            camera_summary=camera_summary,
            raw_frame_retained=True,
            retained_frame_path=str(image_path),
            warnings=warnings,
        )
        return report

    with tempfile.TemporaryDirectory(prefix="lullaby-camera-") as temp_dir:
        image_path = Path(temp_dir) / "camera-smoke.jpg"
        metadata_path = Path(temp_dir) / "camera-smoke-metadata.json"
        return _capture_to_paths(
            image_path,
            metadata_path,
            width=width,
            height=height,
            timeout_seconds=timeout_seconds,
            rpicam_still=rpicam_still,
            camera_summary=camera_summary,
            raw_frame_retained=False,
            retained_frame_path=None,
            warnings=warnings,
        )


def write_camera_smoke_report(output_dir: Path, report: CameraSmokeReport) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "camera-smoke.json"
    path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def _capture_to_paths(
    image_path: Path,
    metadata_path: Path,
    *,
    width: int,
    height: int,
    timeout_seconds: float,
    rpicam_still: str,
    camera_summary: str | None,
    raw_frame_retained: bool,
    retained_frame_path: str | None,
    warnings: list[str],
) -> CameraSmokeReport:
    command = [
        rpicam_still,
        "-n",
        "--immediate",
        "--timeout",
        f"{timeout_seconds:g}s",
        "--width",
        str(width),
        "--height",
        str(height),
        "--output",
        str(image_path),
        "--metadata",
        str(metadata_path),
        "--metadata-format",
        "json",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise RuntimeError(f"rpicam-still failed: {message}")

    info = inspect_image(image_path)
    if not raw_frame_retained:
        info = ImageInfo(
            path="deleted temporary frame",
            format=info.format,
            width=info.width,
            height=info.height,
            byte_count=info.byte_count,
        )
    metadata_keys = _metadata_keys(metadata_path)
    if result.stderr.strip():
        warnings.append(_summarise_stderr(result.stderr))
    return CameraSmokeReport(
        captured_at=datetime.now(UTC),
        source="rpicam-still",
        image=info,
        raw_frame_retained=raw_frame_retained,
        retained_frame_path=retained_frame_path,
        camera_summary=camera_summary,
        metadata_keys=metadata_keys,
        warnings=tuple(warnings),
    )


def _list_rpicam_camera(command: str) -> str | None:
    result = subprocess.run(
        [command, "--list-cameras"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        return None
    lines = [line.strip() for line in result.stdout.splitlines()]
    for line in lines:
        if " : " in line and "[" in line:
            return line
    return None


def _metadata_keys(path: Path) -> tuple[str, ...]:
    if not path.exists():
        return ()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return ()
    preferred = (
        "SensorTimestamp",
        "ExposureTime",
        "AnalogueGain",
        "ColourGains",
        "AfState",
        "LensPosition",
    )
    keys = [key for key in preferred if key in raw]
    keys.extend(sorted(str(key) for key in raw if key not in preferred))
    return tuple(keys)


def _summarise_stderr(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    interesting = [
        line
        for line in lines
        if "WARN" in line or "WARNING" in line or "ERROR" in line
    ]
    if interesting:
        return " | ".join(interesting[:3])
    return " | ".join(lines[:3])


def _png_dimensions(data: bytes) -> tuple[int, int]:
    if len(data) < 24:
        raise ValueError("PNG file is too short")
    return struct.unpack(">II", data[16:24])


def _jpeg_dimensions(data: bytes) -> tuple[int, int]:
    index = 2
    while index < len(data):
        while index < len(data) and data[index] == 0xFF:
            index += 1
        if index >= len(data):
            break
        marker = data[index]
        index += 1
        if marker in {0xD8, 0xD9} or 0xD0 <= marker <= 0xD7:
            continue
        if index + 2 > len(data):
            break
        segment_length = int.from_bytes(data[index : index + 2], "big")
        if segment_length < 2:
            raise ValueError("Invalid JPEG segment length")
        segment_start = index + 2
        segment_end = index + segment_length
        if segment_end > len(data):
            break
        if marker in {
            0xC0,
            0xC1,
            0xC2,
            0xC3,
            0xC5,
            0xC6,
            0xC7,
            0xC9,
            0xCA,
            0xCB,
            0xCD,
            0xCE,
            0xCF,
        }:
            if segment_start + 5 > len(data):
                break
            height = int.from_bytes(data[segment_start + 1 : segment_start + 3], "big")
            width = int.from_bytes(data[segment_start + 3 : segment_start + 5], "big")
            return width, height
        index = segment_end
    raise ValueError("Could not find JPEG dimensions")
