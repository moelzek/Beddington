from __future__ import annotations

import json
import re
import struct
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np


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


@dataclass(frozen=True)
class FramePixels:
    path: str
    width: int
    height: int
    grayscale: np.ndarray


@dataclass(frozen=True)
class VisualChangeReport:
    analysed_at: datetime
    before: ImageInfo
    after: ImageInfo
    mean_absolute_difference: float
    changed_pixel_ratio: float
    pixel_threshold: float
    changed_ratio_threshold: float
    observation: str
    source: str = "local-files"
    raw_frames_retained: bool = True
    retained_frame_paths: tuple[str, ...] = ()
    camera_summary: str | None = None
    warnings: tuple[str, ...] = ()
    wording_note: str = (
        "This is a local visual-change metric only, not a safety, sleep, "
        "breathing, or face-covering assessment."
    )
    privacy_note: str = "Raw frames stay local; only derived change metrics are written."

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["schema_version"] = 1
        value["analysed_at"] = self.analysed_at.isoformat()
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
    elif _looks_like_pnm(data):
        header, _ = _read_pnm_header(data)
        width, height = int(header[1]), int(header[2])
        format_name = "PGM" if header[0] in {"P2", "P5"} else "PPM"
    elif data.startswith(b"BM"):
        width, height, _ = _bmp_header(data)
        height = abs(height)
        format_name = "BMP"
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


def compare_frames(
    before_path: Path,
    after_path: Path,
    *,
    pixel_threshold: float = 0.08,
    changed_ratio_threshold: float = 0.02,
) -> VisualChangeReport:
    if not 0.0 <= pixel_threshold <= 1.0:
        raise ValueError("pixel_threshold must be between 0 and 1")
    if not 0.0 <= changed_ratio_threshold <= 1.0:
        raise ValueError("changed_ratio_threshold must be between 0 and 1")

    before = read_frame_pixels(before_path)
    after = read_frame_pixels(after_path)
    if before.width != after.width or before.height != after.height:
        raise ValueError(
            "Frame dimensions must match for visual-change comparison: "
            f"{before.width}x{before.height} vs {after.width}x{after.height}"
        )

    difference = np.abs(after.grayscale - before.grayscale)
    mean_absolute_difference = float(np.mean(difference))
    changed_pixel_ratio = float(np.mean(difference >= pixel_threshold))
    observation = (
        "visual_change_detected"
        if changed_pixel_ratio >= changed_ratio_threshold
        else "little_visual_change_detected"
    )
    return VisualChangeReport(
        analysed_at=datetime.now(UTC),
        before=inspect_image(before_path),
        after=inspect_image(after_path),
        mean_absolute_difference=mean_absolute_difference,
        changed_pixel_ratio=changed_pixel_ratio,
        pixel_threshold=pixel_threshold,
        changed_ratio_threshold=changed_ratio_threshold,
        observation=observation,
        retained_frame_paths=(str(before_path), str(after_path)),
    )


def capture_rpicam_visual_change(
    output_dir: Path,
    *,
    width: int = 160,
    height: int = 120,
    timeout_seconds: float = 1.0,
    interval_seconds: float = 0.5,
    pixel_threshold: float = 0.08,
    changed_ratio_threshold: float = 0.02,
    keep_frames: bool = False,
    rpicam_still: str = "rpicam-still",
    rpicam_hello: str = "rpicam-hello",
) -> VisualChangeReport:
    if width <= 0 or height <= 0:
        raise ValueError("Camera change width and height must be positive")
    if timeout_seconds <= 0:
        raise ValueError("Camera change timeout must be positive")
    if interval_seconds < 0:
        raise ValueError("Camera change interval must be non-negative")

    output_dir.mkdir(parents=True, exist_ok=True)
    camera_summary = _list_rpicam_camera(rpicam_hello)

    if keep_frames:
        before_path = output_dir / "camera-change-before.bmp"
        after_path = output_dir / "camera-change-after.bmp"
        report = _capture_rpicam_pair_to_paths(
            before_path,
            after_path,
            width=width,
            height=height,
            timeout_seconds=timeout_seconds,
            interval_seconds=interval_seconds,
            pixel_threshold=pixel_threshold,
            changed_ratio_threshold=changed_ratio_threshold,
            rpicam_still=rpicam_still,
            camera_summary=camera_summary,
            raw_frames_retained=True,
        )
        return report

    with tempfile.TemporaryDirectory(prefix="lullaby-camera-change-") as temp_dir:
        before_path = Path(temp_dir) / "camera-change-before.bmp"
        after_path = Path(temp_dir) / "camera-change-after.bmp"
        return _capture_rpicam_pair_to_paths(
            before_path,
            after_path,
            width=width,
            height=height,
            timeout_seconds=timeout_seconds,
            interval_seconds=interval_seconds,
            pixel_threshold=pixel_threshold,
            changed_ratio_threshold=changed_ratio_threshold,
            rpicam_still=rpicam_still,
            camera_summary=camera_summary,
            raw_frames_retained=False,
        )


def read_frame_pixels(path: Path) -> FramePixels:
    data = path.read_bytes()
    if not data:
        raise ValueError(f"Empty frame file: {path}")
    if _looks_like_pnm(data):
        return read_portable_anymap(path)
    if data.startswith(b"BM"):
        return read_bmp(path)
    raise ValueError("Visual-change comparison supports PGM, PPM, and BMP files only")


def read_portable_anymap(path: Path) -> FramePixels:
    data = path.read_bytes()
    if not data:
        raise ValueError(f"Empty frame file: {path}")
    header, offset = _read_pnm_header(data)
    magic = header[0]
    width = int(header[1])
    height = int(header[2])
    max_value = int(header[3])
    if width <= 0 or height <= 0:
        raise ValueError("Frame width and height must be positive")
    if not 0 < max_value <= 65535:
        raise ValueError("Frame max value must be between 1 and 65535")

    if magic in {"P2", "P3"}:
        pixels = _read_ascii_pnm(data[offset:], magic, width, height, max_value)
    elif magic in {"P5", "P6"}:
        pixels = _read_binary_pnm(data[offset:], magic, width, height, max_value)
    else:
        raise ValueError("Visual-change comparison supports PGM/PPM files only")

    return FramePixels(path=str(path), width=width, height=height, grayscale=pixels)


def read_bmp(path: Path) -> FramePixels:
    data = path.read_bytes()
    width, signed_height, bits_per_pixel = _bmp_header(data)
    if bits_per_pixel not in {24, 32}:
        raise ValueError("BMP visual-change comparison supports 24-bit and 32-bit files")
    height = abs(signed_height)
    top_down = signed_height < 0
    pixel_offset = int.from_bytes(data[10:14], "little")
    channels = bits_per_pixel // 8
    row_stride = ((width * bits_per_pixel + 31) // 32) * 4
    needed = pixel_offset + row_stride * height
    if len(data) < needed:
        raise ValueError("BMP file is shorter than its header declares")

    rows: list[np.ndarray] = []
    for row_index in range(height):
        source_row = row_index if top_down else height - 1 - row_index
        start = pixel_offset + source_row * row_stride
        raw_row = np.frombuffer(
            data[start : start + width * channels],
            dtype=np.uint8,
        ).reshape(width, channels)
        bgr = raw_row[:, :3].astype(np.float32)
        rows.append(bgr.mean(axis=1) / 255.0)
    grayscale = np.vstack(rows).astype(np.float32, copy=False)
    return FramePixels(path=str(path), width=width, height=height, grayscale=grayscale)


def write_visual_change_report(output_dir: Path, report: VisualChangeReport) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "visual-change.json"
    path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


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


def _capture_rpicam_pair_to_paths(
    before_path: Path,
    after_path: Path,
    *,
    width: int,
    height: int,
    timeout_seconds: float,
    interval_seconds: float,
    pixel_threshold: float,
    changed_ratio_threshold: float,
    rpicam_still: str,
    camera_summary: str | None,
    raw_frames_retained: bool,
) -> VisualChangeReport:
    warnings: list[str] = []
    _capture_rpicam_bmp(
        before_path,
        width=width,
        height=height,
        timeout_seconds=timeout_seconds,
        rpicam_still=rpicam_still,
        warnings=warnings,
    )
    if interval_seconds:
        import time

        time.sleep(interval_seconds)
    _capture_rpicam_bmp(
        after_path,
        width=width,
        height=height,
        timeout_seconds=timeout_seconds,
        rpicam_still=rpicam_still,
        warnings=warnings,
    )
    report = compare_frames(
        before_path,
        after_path,
        pixel_threshold=pixel_threshold,
        changed_ratio_threshold=changed_ratio_threshold,
    )
    if raw_frames_retained:
        before_info = report.before
        after_info = report.after
        retained_paths = (str(before_path), str(after_path))
    else:
        before_info = ImageInfo(
            path="deleted temporary before frame",
            format=report.before.format,
            width=report.before.width,
            height=report.before.height,
            byte_count=report.before.byte_count,
        )
        after_info = ImageInfo(
            path="deleted temporary after frame",
            format=report.after.format,
            width=report.after.width,
            height=report.after.height,
            byte_count=report.after.byte_count,
        )
        retained_paths = ()
    return VisualChangeReport(
        analysed_at=report.analysed_at,
        before=before_info,
        after=after_info,
        mean_absolute_difference=report.mean_absolute_difference,
        changed_pixel_ratio=report.changed_pixel_ratio,
        pixel_threshold=report.pixel_threshold,
        changed_ratio_threshold=report.changed_ratio_threshold,
        observation=report.observation,
        source="rpicam-still-pair",
        raw_frames_retained=raw_frames_retained,
        retained_frame_paths=retained_paths,
        camera_summary=camera_summary,
        warnings=tuple(warnings),
    )


def _capture_rpicam_bmp(
    path: Path,
    *,
    width: int,
    height: int,
    timeout_seconds: float,
    rpicam_still: str,
    warnings: list[str],
) -> None:
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
        "--encoding",
        "bmp",
        "--output",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise RuntimeError(f"rpicam-still failed: {message}")
    if result.stderr.strip():
        warnings.append(_summarise_stderr(result.stderr))


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


def _looks_like_pnm(data: bytes) -> bool:
    return len(data) >= 3 and data[:2] in {b"P2", b"P3", b"P5", b"P6"} and chr(
        data[2]
    ).isspace()


def _bmp_header(data: bytes) -> tuple[int, int, int]:
    if len(data) < 54 or not data.startswith(b"BM"):
        raise ValueError("BMP file is too short")
    dib_header_size = int.from_bytes(data[14:18], "little")
    if dib_header_size < 40:
        raise ValueError("Unsupported BMP DIB header")
    width = int.from_bytes(data[18:22], "little", signed=True)
    height = int.from_bytes(data[22:26], "little", signed=True)
    planes = int.from_bytes(data[26:28], "little")
    bits_per_pixel = int.from_bytes(data[28:30], "little")
    compression = int.from_bytes(data[30:34], "little")
    if width <= 0 or height == 0 or planes != 1 or compression != 0:
        raise ValueError("Unsupported BMP layout")
    return width, height, bits_per_pixel


def _read_pnm_header(data: bytes) -> tuple[tuple[str, str, str, str], int]:
    tokens: list[str] = []
    index = 0
    while len(tokens) < 4:
        while index < len(data) and chr(data[index]).isspace():
            index += 1
        if index >= len(data):
            break
        if data[index] == ord("#"):
            while index < len(data) and data[index] not in b"\r\n":
                index += 1
            continue
        start = index
        while index < len(data) and not chr(data[index]).isspace():
            index += 1
        tokens.append(data[start:index].decode("ascii"))
    if len(tokens) != 4:
        raise ValueError("PNM header must include magic, width, height, and max value")
    if index < len(data) and chr(data[index]).isspace():
        index += 1
    return (tokens[0], tokens[1], tokens[2], tokens[3]), index


def _read_ascii_pnm(
    payload: bytes,
    magic: str,
    width: int,
    height: int,
    max_value: int,
) -> np.ndarray:
    text = re.sub(rb"#.*", b"", payload).decode("ascii")
    values = np.fromstring(text, dtype=np.float32, sep=" ")
    channels = 1 if magic == "P2" else 3
    expected = width * height * channels
    if values.size != expected:
        raise ValueError(f"PNM pixel count mismatch: expected {expected}, got {values.size}")
    values = values / float(max_value)
    if channels == 3:
        values = values.reshape(height, width, 3).mean(axis=2)
    else:
        values = values.reshape(height, width)
    return np.clip(values.astype(np.float32, copy=False), 0.0, 1.0)


def _read_binary_pnm(
    payload: bytes,
    magic: str,
    width: int,
    height: int,
    max_value: int,
) -> np.ndarray:
    channels = 1 if magic == "P5" else 3
    dtype = np.uint8 if max_value <= 255 else ">u2"
    expected = width * height * channels
    values = np.frombuffer(payload, dtype=dtype, count=expected).astype(np.float32)
    if values.size != expected:
        raise ValueError(f"PNM pixel count mismatch: expected {expected}, got {values.size}")
    values = values / float(max_value)
    if channels == 3:
        values = values.reshape(height, width, 3).mean(axis=2)
    else:
        values = values.reshape(height, width)
    return np.clip(values.astype(np.float32, copy=False), 0.0, 1.0)
