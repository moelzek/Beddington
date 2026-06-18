from __future__ import annotations

import hashlib
import os
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Protocol

import numpy as np

from .audio import WINDOW_SAMPLES

MODEL_URL = (
    "https://www.kaggle.com/api/v1/models/google/yamnet/"
    "tfLite/classification-tflite/1/download"
)
MODEL_SHA256 = "10c95ea3eb9a7bb4cb8bddf6feb023250381008177ac162ce169694d05c317de"
MODEL_FILENAME = "yamnet-classification-tflite-v1.tflite"
CRY_LABEL = "Baby cry, infant cry"


class CryDetector(Protocol):
    name: str

    def score(self, samples: np.ndarray) -> float: ...


class YamNetTFLiteDetector:
    name = "YAMNet TFLite: Baby cry, infant cry"

    def __init__(self, model_path: Path | None = None):
        self.model_path = ensure_model(model_path)
        self._interpreter = _make_interpreter(self.model_path)
        input_details = self._interpreter.get_input_details()
        output_details = self._interpreter.get_output_details()
        self._input_index = input_details[0]["index"]
        self._output_index = output_details[0]["index"]
        self._interpreter.resize_tensor_input(
            self._input_index, [WINDOW_SAMPLES], strict=True
        )
        self._interpreter.allocate_tensors()
        self._cry_index = _read_labels(self.model_path).index(CRY_LABEL)

    def score(self, samples: np.ndarray) -> float:
        if samples.shape != (WINDOW_SAMPLES,):
            raise ValueError(
                f"YAMNet expects {WINDOW_SAMPLES} samples; received {samples.shape}"
            )
        self._interpreter.set_tensor(
            self._input_index, samples.astype(np.float32, copy=False)
        )
        self._interpreter.invoke()
        scores = self._interpreter.get_tensor(self._output_index)
        return float(scores[0, self._cry_index])


def default_model_path() -> Path:
    configured = os.getenv("LULLABY_YAMNET_MODEL")
    if configured:
        return Path(configured).expanduser()
    cache_root = Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache"))
    return cache_root / "lullaby" / "models" / MODEL_FILENAME


def ensure_model(model_path: Path | None = None) -> Path:
    destination = (model_path or default_model_path()).expanduser()
    if destination.exists():
        _verify_hash(destination)
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading the official YAMNet TFLite model to {destination} ...")
    request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "lullaby/0.1"})
    with tempfile.TemporaryDirectory(prefix="lullaby-yamnet-") as temp_dir:
        archive_path = Path(temp_dir) / "yamnet.tar.gz"
        with urllib.request.urlopen(request, timeout=90) as response:
            archive_path.write_bytes(response.read())
        with tarfile.open(archive_path, "r:gz") as archive:
            member = next(
                (item for item in archive.getmembers() if item.name.endswith(".tflite")),
                None,
            )
            if member is None:
                raise RuntimeError("Downloaded YAMNet archive did not contain a .tflite file")
            extracted = archive.extractfile(member)
            if extracted is None:
                raise RuntimeError("Could not read YAMNet model from downloaded archive")
            model_bytes = extracted.read()
        temporary_model = Path(temp_dir) / MODEL_FILENAME
        temporary_model.write_bytes(model_bytes)
        _verify_hash(temporary_model)
        temporary_model.replace(destination)
    return destination


def _verify_hash(path: Path) -> None:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != MODEL_SHA256:
        raise RuntimeError(
            f"YAMNet model checksum mismatch for {path}. "
            "Delete the file and retry the download."
        )


def _read_labels(model_path: Path) -> list[str]:
    with zipfile.ZipFile(model_path) as archive:
        with archive.open("yamnet_label_list.txt") as labels:
            return [line.decode("utf-8").strip() for line in labels.readlines()]


def _make_interpreter(model_path: Path):
    try:
        from ai_edge_litert.interpreter import Interpreter
    except ImportError:
        try:
            from tflite_runtime.interpreter import Interpreter
        except ImportError as exc:
            raise RuntimeError(
                "No LiteRT interpreter is installed. Run the README install command."
            ) from exc
    return Interpreter(model_path=str(model_path))
