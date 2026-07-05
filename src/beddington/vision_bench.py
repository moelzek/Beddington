from __future__ import annotations

import csv
import json
import logging
import re
import tempfile
import time
import urllib.error
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .worker import WorkerHTTPError

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    box: tuple[float, float, float, float]
    keypoints: list[tuple[float, float, float]] | None = None


@dataclass(frozen=True)
class FrameResult:
    detections: list[Detection]
    poses: list[Detection]
    image_w: int
    image_h: int
    inference_ms: float


class VisionBackend(Protocol):
    def analyze_jpeg(self, data: bytes) -> FrameResult:
        ...

    def save_annotated(self, data: bytes, out_path: Path) -> None:
        ...


class UltralyticsBackend:
    def __init__(
        self,
        det_model: str = "yolov8s.pt",
        pose_model: str = "yolov8s-pose.pt",
        conf: float = 0.25,
    ) -> None:
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError(
                "vision-bench needs the optional vision extra: "
                "pip install 'beddington-monitor[vision]'"
            ) from exc
        self._det_model = YOLO(det_model)
        self._pose_model = YOLO(pose_model)
        self._conf = float(conf)

    def analyze_jpeg(self, data: bytes) -> FrameResult:
        with tempfile.NamedTemporaryFile(suffix=".jpg") as image_file:
            image_file.write(data)
            image_file.flush()
            started = time.perf_counter()
            det_results = list(self._det_model(str(image_file.name), conf=self._conf))
            pose_results = list(self._pose_model(str(image_file.name), conf=self._conf))
            inference_ms = (time.perf_counter() - started) * 1000.0

        image_h, image_w = _result_shape(det_results)
        if image_h <= 0 or image_w <= 0:
            image_h, image_w = _result_shape(pose_results)
        return FrameResult(
            detections=_extract_detections(det_results, self._det_model),
            poses=_extract_detections(
                pose_results,
                self._pose_model,
                include_keypoints=True,
            ),
            image_w=image_w,
            image_h=image_h,
            inference_ms=inference_ms,
        )

    def save_annotated(self, data: bytes, out_path: Path) -> None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".jpg") as image_file:
            image_file.write(data)
            image_file.flush()
            results = list(self._pose_model(str(image_file.name), conf=self._conf))
            first = next(iter(results), None)
            if first is not None:
                first.save(filename=str(out_path))


def collect_frames(
    client: object,
    out_dir: Path,
    interval_s: float,
    duration_s: float,
    *,
    clock=time.time,
    sleep=time.sleep,
) -> dict[str, int | str]:
    if interval_s <= 0:
        raise ValueError("interval_s must be positive")
    if duration_s < 0:
        raise ValueError("duration_s must be non-negative")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "frames.jsonl"
    deadline = clock() + duration_s
    frames_saved = 0
    misses = 0
    errors = 0

    with manifest_path.open("a", encoding="utf-8") as manifest:
        while clock() < deadline:
            try:
                snapshot = client.get_snapshot()
                frame = client.get_frame()
            except (WorkerHTTPError, urllib.error.URLError, OSError):
                LOGGER.warning("vision-bench frame fetch failed; retrying", exc_info=True)
                errors += 1
                remaining = deadline - clock()
                if remaining <= 0:
                    break
                sleep(min(interval_s, remaining))
                continue
            ts = float(clock())
            if frame is None:
                misses += 1
            else:
                filename = _frame_filename(ts)
                (out_dir / filename).write_bytes(frame)
                manifest.write(
                    json.dumps(
                        {
                            "file": filename,
                            "ts": ts,
                            "baby_state": _snapshot_value(snapshot, "baby_state"),
                            "label": _snapshot_value(snapshot, "label"),
                            "target_count": _snapshot_value(snapshot, "target_count"),
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
                frames_saved += 1

            remaining = deadline - clock()
            if remaining <= 0:
                break
            sleep(min(interval_s, remaining))

    return {
        "frames_saved": frames_saved,
        "misses": misses,
        "errors": errors,
        "manifest": str(manifest_path),
    }


def analyze_dir(
    backend: VisionBackend,
    frames_dir: Path,
    out_path: Path,
    annotate_dir: Path | None = None,
) -> dict[str, int | str]:
    frames_dir = Path(frames_dir)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if annotate_dir is not None:
        annotate_dir = Path(annotate_dir)
        annotate_dir.mkdir(parents=True, exist_ok=True)

    frame_count = 0
    with out_path.open("w", encoding="utf-8") as out_file:
        for frame_path in sorted(frames_dir.glob("*.jpg")):
            data = frame_path.read_bytes()
            result = backend.analyze_jpeg(data)
            out_file.write(
                json.dumps(
                    {
                        "file": frame_path.name,
                        "w": result.image_w,
                        "h": result.image_h,
                        "inference_ms": result.inference_ms,
                        "detections": [
                            _detection_to_dict(detection)
                            for detection in result.detections
                        ],
                        "poses": [_detection_to_dict(pose) for pose in result.poses],
                    },
                    sort_keys=True,
                )
                + "\n"
            )
            if annotate_dir is not None:
                backend.save_annotated(data, annotate_dir / frame_path.name)
            frame_count += 1

    return {"frames": frame_count, "out": str(out_path)}


def write_labels_template(frames_dir: Path, out_csv: Path) -> dict[str, int | str]:
    frames_dir = Path(frames_dir)
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    frames = sorted(frames_dir.glob("*.jpg"))
    with out_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("file", "truth"))
        writer.writeheader()
        for frame_path in frames:
            writer.writerow({"file": frame_path.name, "truth": ""})
    return {"frames": len(frames), "out": str(out_csv)}


def write_report(
    detections_path: Path,
    labels_path: Path | None,
    out_md: Path,
) -> dict[str, int | str]:
    rows = _read_detections(detections_path)
    labels = _read_labels(labels_path) if labels_path is not None else {}
    total = len(rows)
    person_frames = {
        str(row.get("file"))
        for row in rows
        if any(_is_person_detection(detection) for detection in row.get("detections", []))
    }
    person_detections = [
        detection
        for row in rows
        for detection in row.get("detections", [])
        if _is_person_detection(detection)
    ]
    pose_with_keypoints = sum(
        1
        for row in rows
        for pose in row.get("poses", [])
        if _has_confident_keypoint(pose)
    )

    lines = [
        "# Vision Bench Report",
        "",
        "Stock COCO person-detection measurement on collected nursery frames.",
        "",
        "## Summary",
        "",
        f"- Total frames: {total}",
        f"- Frames with at least one person detection: "
        f"{_rate(len(person_frames), total)}",
        f"- Person detections: {len(person_detections)}",
        f"- Poses with at least one keypoint confidence >= 0.5: "
        f"{pose_with_keypoints}",
    ]

    if labels:
        truth_counts = _truth_counts(rows, labels, person_frames)
        baby_detected, baby_total = truth_counts.get("baby", (0, 0))
        lines.extend(
            [
                f"- Headline: person-detection rate on truth == baby frames: "
                f"{_rate(baby_detected, baby_total)}",
                "",
                "## Truth Breakdown",
                "",
                "| Truth | Person-detection rate |",
                "| --- | ---: |",
            ]
        )
        for truth in sorted(truth_counts):
            detected, count = truth_counts[truth]
            lines.append(f"| {truth} | {_rate(detected, count)} |")
    else:
        lines.extend(
            [
                "- No labels file was provided, so truth-class recall is not reported.",
            ]
        )

    lines.extend(
        [
            "",
            "## Confidence Distribution",
            "",
            "| Confidence | Person detections |",
            "| --- | ---: |",
        ]
    )
    for label, count in _bucket_confidences(person_detections):
        lines.append(f"| {label} | {count} |")

    lines.extend(
        [
            "",
            "## Box Height Fraction",
            "",
            "| Box height / image height | Person detections |",
            "| --- | ---: |",
        ]
    )
    for label, count in _bucket_box_heights(rows):
        lines.append(f"| {label} | {count} |")

    lines.extend(
        [
            "",
            "## Hour Of Day",
            "",
            "| Hour | Frames | With person | Rate |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for hour, count, detected in _hour_breakdown(rows, person_frames):
        lines.append(f"| {hour:02d}:00 | {count} | {detected} | {_rate(detected, count)} |")

    out_md = Path(out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"frames": total, "out": str(out_md)}


def _frame_filename(ts: float) -> str:
    if ts.is_integer():
        return f"frame_{int(ts)}.jpg"
    return f"frame_{ts:.6f}.jpg"


def _snapshot_value(snapshot: object, key: str) -> object:
    if not isinstance(snapshot, dict):
        return None
    value = snapshot.get(key)
    if value is not None:
        return value
    presence = snapshot.get("presence")
    if isinstance(presence, dict):
        return presence.get(key)
    return None


def _to_list(value: object) -> list:
    if value is None:
        return []
    detach = getattr(value, "detach", None)
    if callable(detach):
        value = detach()
    cpu = getattr(value, "cpu", None)
    if callable(cpu):
        value = cpu()
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        result = tolist()
        return result if isinstance(result, list) else list(result)
    if isinstance(value, list):
        return value
    return list(value)  # type: ignore[arg-type]


def _result_shape(results: object) -> tuple[int, int]:
    for result in results:
        shape = getattr(result, "orig_shape", None)
        if (
            isinstance(shape, (list, tuple))
            and len(shape) >= 2
            and shape[0] is not None
            and shape[1] is not None
        ):
            return int(shape[0]), int(shape[1])
    return (0, 0)


def _model_label(model: object, class_id: int) -> str:
    names = getattr(model, "names", {})
    if isinstance(names, dict):
        return str(names.get(class_id, class_id))
    if isinstance(names, (list, tuple)) and 0 <= class_id < len(names):
        return str(names[class_id])
    return str(class_id)


def _extract_detections(
    results: object,
    model: object,
    *,
    include_keypoints: bool = False,
) -> list[Detection]:
    detections: list[Detection] = []
    for result in results:
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            continue
        xyxy_rows = _to_list(getattr(boxes, "xyxy", []))
        conf_rows = _to_list(getattr(boxes, "conf", []))
        cls_rows = _to_list(getattr(boxes, "cls", []))
        keypoint_rows: list = []
        if include_keypoints:
            keypoints = getattr(result, "keypoints", None)
            keypoint_rows = _to_list(getattr(keypoints, "data", []))
        for index, box in enumerate(xyxy_rows):
            class_id = int(cls_rows[index]) if index < len(cls_rows) else -1
            keypoints = None
            if include_keypoints and index < len(keypoint_rows):
                keypoints = [
                    (float(point[0]), float(point[1]), float(point[2]))
                    for point in keypoint_rows[index]
                    if len(point) >= 3
                ]
            detections.append(
                Detection(
                    label=_model_label(model, class_id),
                    confidence=(
                        float(conf_rows[index]) if index < len(conf_rows) else 0.0
                    ),
                    box=(
                        float(box[0]),
                        float(box[1]),
                        float(box[2]),
                        float(box[3]),
                    ),
                    keypoints=keypoints,
                )
            )
    return detections


def _detection_to_dict(detection: Detection) -> dict[str, object]:
    return {
        "label": detection.label,
        "confidence": detection.confidence,
        "box": list(detection.box),
        "keypoints": (
            None
            if detection.keypoints is None
            else [list(point) for point in detection.keypoints]
        ),
    }


def _read_detections(path: Path) -> list[dict]:
    rows: list[dict] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _read_labels(path: Path | None) -> dict[str, str]:
    labels: dict[str, str] = {}
    if path is None:
        return labels
    with Path(path).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            filename = str(row.get("file", "")).strip()
            truth = str(row.get("truth", "")).strip().lower()
            if filename and truth:
                labels[filename] = truth
    return labels


def _is_person_detection(detection: object) -> bool:
    return (
        isinstance(detection, dict)
        and str(detection.get("label", "")).strip().lower() == "person"
    )


def _has_confident_keypoint(pose: object) -> bool:
    if not isinstance(pose, dict):
        return False
    keypoints = pose.get("keypoints")
    if not isinstance(keypoints, list):
        return False
    for point in keypoints:
        if (
            isinstance(point, list)
            and len(point) >= 3
            and isinstance(point[2], (int, float))
            and float(point[2]) >= 0.5
        ):
            return True
    return False


def _truth_counts(
    rows: list[dict],
    labels: dict[str, str],
    person_frames: set[str],
) -> dict[str, tuple[int, int]]:
    counts: dict[str, list[int]] = {}
    for row in rows:
        filename = str(row.get("file", ""))
        truth = labels.get(filename)
        if truth is None:
            continue
        detected, total = counts.setdefault(truth, [0, 0])
        total += 1
        if filename in person_frames:
            detected += 1
        counts[truth] = [detected, total]
    return {truth: (values[0], values[1]) for truth, values in counts.items()}


def _rate(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "n/a"
    return f"{numerator}/{denominator} ({(numerator / denominator) * 100:.1f}%)"


def _bucket_confidences(detections: list[dict]) -> list[tuple[str, int]]:
    buckets = [
        ("0.00-0.25", 0.0, 0.25, 0),
        ("0.25-0.50", 0.25, 0.50, 0),
        ("0.50-0.75", 0.50, 0.75, 0),
        ("0.75-1.00", 0.75, 1.01, 0),
    ]
    counts = [0, 0, 0, 0]
    for detection in detections:
        confidence = detection.get("confidence")
        if not isinstance(confidence, (int, float)):
            continue
        value = float(confidence)
        for index, (_label, lower, upper, _count) in enumerate(buckets):
            if lower <= value < upper:
                counts[index] += 1
                break
    return [(label, counts[index]) for index, (label, *_rest) in enumerate(buckets)]


def _bucket_box_heights(rows: list[dict]) -> list[tuple[str, int]]:
    labels = ("0.00-0.25", "0.25-0.50", "0.50-0.75", "0.75-1.00")
    counts = [0, 0, 0, 0]
    for row in rows:
        image_h = row.get("h")
        if not isinstance(image_h, (int, float)) or float(image_h) <= 0:
            continue
        for detection in row.get("detections", []):
            if not _is_person_detection(detection):
                continue
            box = detection.get("box")
            if not isinstance(box, list) or len(box) < 4:
                continue
            height_fraction = max(0.0, float(box[3]) - float(box[1])) / float(image_h)
            if height_fraction < 0.25:
                counts[0] += 1
            elif height_fraction < 0.50:
                counts[1] += 1
            elif height_fraction < 0.75:
                counts[2] += 1
            else:
                counts[3] += 1
    return list(zip(labels, counts, strict=True))


_FRAME_TS_RE = re.compile(r"^frame_([0-9]+(?:\.[0-9]+)?)")


def _hour_breakdown(
    rows: list[dict],
    person_frames: set[str],
) -> list[tuple[int, int, int]]:
    counts: dict[int, list[int]] = {}
    for row in rows:
        filename = str(row.get("file", ""))
        match = _FRAME_TS_RE.match(Path(filename).stem)
        if match is None:
            continue
        try:
            hour = datetime.fromtimestamp(float(match.group(1))).hour
        except (OverflowError, OSError, ValueError):
            continue
        values = counts.setdefault(hour, [0, 0])
        values[0] += 1
        if filename in person_frames:
            values[1] += 1
    return [(hour, values[0], values[1]) for hour, values in sorted(counts.items())]
