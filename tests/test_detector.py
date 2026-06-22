from __future__ import annotations

import errno
from pathlib import Path

from lullaby.detector import _move_model_file


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
