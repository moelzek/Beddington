from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from beddington.audio import (
    SAMPLE_RATE,
    WINDOW_SAMPLES,
    _choose_input_sample_rate,
    iter_windows,
    read_wav,
)


def test_read_wav_converts_stereo_and_resamples(tmp_path: Path) -> None:
    path = tmp_path / "stereo.wav"
    source_rate = 8_000
    samples = np.array([[0, 0], [16_000, 8_000], [-16_000, -8_000]], dtype="<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(source_rate)
        output.writeframes(samples.tobytes())

    waveform = read_wav(path)

    assert waveform.dtype == np.float32
    assert len(waveform) == round(3 * SAMPLE_RATE / source_rate)
    assert waveform.max() <= 1.0
    assert waveform.min() >= -1.0


def test_short_audio_is_padded_to_one_model_window() -> None:
    windows = list(iter_windows(np.zeros(100, dtype=np.float32)))

    assert len(windows) == 1
    assert windows[0].samples.shape == (WINDOW_SAMPLES,)


def test_microphone_sample_rate_falls_back_to_device_default() -> None:
    class FakeSoundDevice:
        @staticmethod
        def check_input_settings(**kwargs: object) -> None:
            raise RuntimeError("invalid sample rate")

        @staticmethod
        def query_devices(device: object, kind: str) -> dict[str, float]:
            assert device == 1
            assert kind == "input"
            return {"default_samplerate": 44_100.0}

    assert _choose_input_sample_rate(FakeSoundDevice(), 1) == 44_100
