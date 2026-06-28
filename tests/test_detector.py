from __future__ import annotations

import errno
from pathlib import Path

from beddington.detector import _move_model_file, dominant_baby_sound


def test_dominant_baby_sound_picks_highest_above_threshold() -> None:
    assert dominant_baby_sound({"cooing": 0.5, "laughing": 0.3}, 0.2) == "cooing"


def test_dominant_baby_sound_returns_none_below_threshold() -> None:
    assert dominant_baby_sound({"cooing": 0.1, "snoring": 0.15}, 0.2) is None


def test_dominant_baby_sound_excludes_categories() -> None:
    scores = {"crying": 0.9, "cooing": 0.5}
    assert dominant_baby_sound(scores, 0.2, exclude=("crying",)) == "cooing"


def test_move_model_file_handles_cross_device_cache_move(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "model.tmp"
    destination = tmp_path / "model.tflite"
    source.write_bytes(b"model")

    def fail_with_cross_device_link(self: Path, target: Path) -> Path:
        del target
        if self == source:
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        return self

    monkeypatch.setattr(Path, "replace", fail_with_cross_device_link)

    _move_model_file(source, destination)

    assert destination.read_bytes() == b"model"
    assert not source.exists()
