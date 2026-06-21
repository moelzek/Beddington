from __future__ import annotations

import wave
from pathlib import Path


def test_soothe_assets_are_local_mono_wavs() -> None:
    for path in sorted(Path("assets/soothe").glob("*.wav")):
        with wave.open(str(path), "rb") as wav:
            assert wav.getnchannels() == 1
            assert wav.getframerate() == 16_000
            assert wav.getsampwidth() == 2
            assert wav.getnframes() > 0
