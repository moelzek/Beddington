from __future__ import annotations

import builtins
import csv
import json
from pathlib import Path

import pytest

from beddington import vision_bench
from beddington.cli import main
from beddington.vision_bench import (
    Detection,
    FrameResult,
    UltralyticsBackend,
    analyze_dir,
    collect_frames,
    write_labels_template,
    write_report,
)


class _FakePiClient:
    def __init__(self) -> None:
        self.snapshots = [
            {"baby_state": "still", "label": "resting", "target_count": 1},
            {"label": "moving"},
            {"presence": {"target_count": 2}},
        ]
        self.frames = [b"jpeg-1", None, b"jpeg-3"]
        self.snapshot_calls = 0
        self.frame_calls = 0

    def get_snapshot(self) -> dict:
        index = min(self.snapshot_calls, len(self.snapshots) - 1)
        self.snapshot_calls += 1
        return self.snapshots[index]

    def get_frame(self) -> bytes | None:
        index = min(self.frame_calls, len(self.frames) - 1)
        self.frame_calls += 1
        return self.frames[index]


class _FakeClock:
    def __init__(self, start: float = 1_700_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class _FakeBackend:
    def __init__(self, results: list[FrameResult] | None = None) -> None:
        self.results = results or [
            FrameResult(
                detections=[
                    Detection("person", 0.82, (10.0, 20.0, 80.0, 120.0)),
                ],
                poses=[
                    Detection(
                        "person",
                        0.77,
                        (10.0, 20.0, 80.0, 120.0),
                        keypoints=[(12.0, 22.0, 0.6)],
                    )
                ],
                image_w=160,
                image_h=200,
                inference_ms=12.5,
            )
        ]
        self.calls = 0
        self.saved: list[Path] = []

    def analyze_jpeg(self, data: bytes) -> FrameResult:
        del data
        result = self.results[min(self.calls, len(self.results) - 1)]
        self.calls += 1
        return result

    def save_annotated(self, data: bytes, out_path: Path) -> None:
        del data
        self.saved.append(Path(out_path))
        Path(out_path).write_bytes(b"annotated")


def test_collect_frames_saves_jpegs_manifest_and_counts_misses(tmp_path: Path) -> None:
    client = _FakePiClient()
    clock = _FakeClock()

    summary = collect_frames(
        client,
        tmp_path,
        interval_s=1.0,
        duration_s=3.0,
        clock=clock,
        sleep=clock.sleep,
    )

    assert summary["frames_saved"] == 2
    assert summary["misses"] == 1
    assert summary["errors"] == 0
    assert (tmp_path / "frame_1700000000.jpg").read_bytes() == b"jpeg-1"
    assert (tmp_path / "frame_1700000002.jpg").read_bytes() == b"jpeg-3"

    lines = [
        json.loads(line)
        for line in (tmp_path / "frames.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert lines == [
        {
            "baby_state": "still",
            "file": "frame_1700000000.jpg",
            "label": "resting",
            "target_count": 1,
            "ts": 1_700_000_000.0,
        },
        {
            "baby_state": None,
            "file": "frame_1700000002.jpg",
            "label": None,
            "target_count": 2,
            "ts": 1_700_000_002.0,
        },
    ]


class _FlakyPiClient:
    def __init__(self) -> None:
        self.snapshot_calls = 0
        self.frame_calls = 0

    def get_snapshot(self) -> dict:
        self.snapshot_calls += 1
        if self.snapshot_calls == 1:
            raise OSError("snapshot unavailable")
        return {
            "baby_state": "still",
            "label": "resting",
            "presence": {"target_count": self.snapshot_calls},
        }

    def get_frame(self) -> bytes:
        self.frame_calls += 1
        if self.frame_calls == 1:
            raise OSError("frame unavailable")
        return b"jpeg-after-errors"


def test_collect_frames_continues_after_transient_fetch_errors(
    tmp_path: Path,
) -> None:
    client = _FlakyPiClient()
    clock = _FakeClock()

    summary = collect_frames(
        client,
        tmp_path,
        interval_s=1.0,
        duration_s=3.0,
        clock=clock,
        sleep=clock.sleep,
    )

    assert summary["frames_saved"] == 1
    assert summary["misses"] == 0
    assert summary["errors"] == 2
    assert (tmp_path / "frame_1700000002.jpg").read_bytes() == b"jpeg-after-errors"
    lines = [
        json.loads(line)
        for line in (tmp_path / "frames.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert lines[0]["target_count"] == 3


def test_analyze_dir_writes_jsonl_and_optional_annotations(tmp_path: Path) -> None:
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "b.jpg").write_bytes(b"b")
    (frames / "a.jpg").write_bytes(b"a")
    out = tmp_path / "detections.jsonl"
    annotate = tmp_path / "annotated"
    backend = _FakeBackend()

    summary = analyze_dir(backend, frames, out, annotate)

    assert summary["frames"] == 2
    rows = [
        json.loads(line)
        for line in out.read_text(encoding="utf-8").splitlines()
    ]
    assert [row["file"] for row in rows] == ["a.jpg", "b.jpg"]
    assert rows[0]["w"] == 160
    assert rows[0]["h"] == 200
    assert rows[0]["detections"][0]["label"] == "person"
    assert rows[0]["poses"][0]["keypoints"] == [[12.0, 22.0, 0.6]]
    assert backend.saved == [annotate / "a.jpg", annotate / "b.jpg"]


def test_write_labels_template(tmp_path: Path) -> None:
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "frame_2.jpg").write_bytes(b"2")
    (frames / "frame_1.jpg").write_bytes(b"1")
    labels = tmp_path / "labels.csv"

    summary = write_labels_template(frames, labels)

    assert summary["frames"] == 2
    with labels.open(encoding="utf-8", newline="") as handle:
        assert list(csv.DictReader(handle)) == [
            {"file": "frame_1.jpg", "truth": ""},
            {"file": "frame_2.jpg", "truth": ""},
        ]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def test_write_report_with_labels_includes_baby_truth_rate(tmp_path: Path) -> None:
    detections = tmp_path / "detections.jsonl"
    labels = tmp_path / "labels.csv"
    report = tmp_path / "report.md"
    _write_jsonl(
        detections,
        [
            {
                "file": "frame_1700000000.jpg",
                "w": 100,
                "h": 200,
                "inference_ms": 10.0,
                "detections": [
                    {
                        "label": "person",
                        "confidence": 0.80,
                        "box": [0, 50, 50, 150],
                        "keypoints": None,
                    }
                ],
                "poses": [
                    {
                        "label": "person",
                        "confidence": 0.70,
                        "box": [0, 50, 50, 150],
                        "keypoints": [[10, 10, 0.6]],
                    }
                ],
            },
            {
                "file": "frame_1700003600.jpg",
                "w": 100,
                "h": 200,
                "inference_ms": 11.0,
                "detections": [],
                "poses": [],
            },
            {
                "file": "frame_1700007200.jpg",
                "w": 100,
                "h": 200,
                "inference_ms": 12.0,
                "detections": [
                    {
                        "label": "person",
                        "confidence": 0.40,
                        "box": [0, 0, 50, 40],
                        "keypoints": None,
                    }
                ],
                "poses": [],
            },
        ],
    )
    labels.write_text(
        "file,truth\n"
        "frame_1700000000.jpg,baby\n"
        "frame_1700003600.jpg,baby\n"
        "frame_1700007200.jpg,adult\n",
        encoding="utf-8",
    )

    summary = write_report(detections, labels, report)

    text = report.read_text(encoding="utf-8")
    assert summary["frames"] == 3
    assert "Total frames: 3" in text
    assert "person-detection rate on truth == baby frames: 1/2 (50.0%)" in text
    assert "| adult | 1/1 (100.0%) |" in text
    assert "| baby | 1/2 (50.0%) |" in text
    assert "Poses with at least one keypoint confidence >= 0.5: 1" in text
    assert "| 0.75-1.00 | 1 |" in text
    assert "| 0.25-0.50 | 1 |" in text


def test_write_report_without_labels_still_writes_summary(tmp_path: Path) -> None:
    detections = tmp_path / "detections.jsonl"
    report = tmp_path / "report.md"
    _write_jsonl(
        detections,
        [
            {
                "file": "frame_1700000000.jpg",
                "w": 100,
                "h": 100,
                "inference_ms": 5.0,
                "detections": [],
                "poses": [],
            }
        ],
    )

    write_report(detections, None, report)

    text = report.read_text(encoding="utf-8")
    assert "No labels file was provided" in text
    assert "Frames with at least one person detection: 0/1 (0.0%)" in text


def test_ultralytics_backend_missing_extra_message(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "ultralytics":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(RuntimeError, match="beddington-monitor\\[vision\\]"):
        UltralyticsBackend()


def test_cli_vision_bench_modes_use_injected_fakes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frames = tmp_path / "frames"
    frames.mkdir()
    (frames / "frame_1700000000.jpg").write_bytes(b"jpeg")
    detections = tmp_path / "detections.jsonl"
    labels = tmp_path / "labels.csv"
    report = tmp_path / "report.md"

    def fake_collect(client: object, out_dir: Path, interval: float, duration: float):
        del client, interval, duration
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        return {"frames_saved": 1, "misses": 0, "manifest": str(Path(out_dir))}

    class FakePiClient:
        def __init__(self, base_url: str, token: str, timeout: float) -> None:
            assert base_url == "http://pi.local:8088"
            assert token == "worker-token"
            assert timeout > 0

    monkeypatch.setattr(vision_bench, "collect_frames", fake_collect)
    monkeypatch.setattr(vision_bench, "UltralyticsBackend", _FakeBackend)
    monkeypatch.setattr("beddington.worker.PiClient", FakePiClient)
    monkeypatch.setenv("BEDDINGTON_LIVEVIEW_TOKEN", "worker-token")

    assert (
        main(
            [
                "vision-bench",
                "--mode",
                "collect",
                "--url",
                "http://pi.local:8088",
                "--out",
                str(frames),
                "--duration",
                "1",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "vision-bench",
                "--mode",
                "analyze",
                "--frames",
                str(frames),
                "--detections",
                str(detections),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "vision-bench",
                "--mode",
                "labels-template",
                "--frames",
                str(frames),
                "--labels",
                str(labels),
            ]
        )
        == 0
    )
    labels.write_text("file,truth\nframe_1700000000.jpg,baby\n", encoding="utf-8")
    assert (
        main(
            [
                "vision-bench",
                "--mode",
                "report",
                "--detections",
                str(detections),
                "--labels",
                str(labels),
                "--report-out",
                str(report),
            ]
        )
        == 0
    )
    assert report.exists()
