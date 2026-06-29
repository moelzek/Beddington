from __future__ import annotations

import wave
from pathlib import Path


def test_soothe_assets_are_local_mono_wavs() -> None:
    expected_new_assets = {
        "chime",
        "fan_hum",
        "forest_breeze",
        "music_box_lullaby",
        "night_sky",
        "ocean_waves",
        "pink_noise",
        "rain",
        "shushing",
    }
    asset_names = {path.stem for path in Path("assets/soothe").glob("*.wav")}

    assert expected_new_assets <= asset_names

    for path in sorted(Path("assets/soothe").glob("*.wav")):
        with wave.open(str(path), "rb") as wav:
            assert wav.getnchannels() == 1
            assert wav.getframerate() == 16_000
            assert wav.getsampwidth() == 2
            assert wav.getnframes() > 0


def test_chime_asset_is_short() -> None:
    with wave.open("assets/soothe/chime.wav", "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getframerate() == 16_000
        assert wav.getsampwidth() == 2
        assert wav.getnframes() == 4_800
