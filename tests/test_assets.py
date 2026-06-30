from __future__ import annotations

import json
import wave
from pathlib import Path


EXPECTED_SOOTHE_MP3S = {
    "dreams",
    "drums",
    "fan_hum",
    "forest_breeze",
    "heartbeat",
    "impromptu",
    "lofi_rain",
    "meditation",
    "music_box_lullaby",
    "music_chimes",
    "night_sky",
    "ocean_waves",
    "piano",
    "pink_noise",
    "rain",
    "river",
    "shushing",
    "soothing_music",
    "uterine_whoosh",
    "white_noise",
}


def test_soothe_assets_are_local_mp3s() -> None:
    asset_names = {path.stem for path in Path("assets/soothe").glob("*.mp3")}

    assert asset_names == EXPECTED_SOOTHE_MP3S

    for path in sorted(Path("assets/soothe").glob("*.mp3")):
        assert path.stat().st_size > 0


def test_soothe_catalog_covers_dashboard_assets() -> None:
    catalog = json.loads(Path("assets/soothe/catalog.json").read_text(encoding="utf-8"))
    presets = catalog["presets"]

    assert set(presets) == EXPECTED_SOOTHE_MP3S
    assert {
        key
        for key, entry in presets.items()
        if entry["category"] == "sounds"
    } == {
        "fan_hum",
        "forest_breeze",
        "heartbeat",
        "night_sky",
        "ocean_waves",
        "pink_noise",
        "rain",
        "shushing",
        "uterine_whoosh",
        "white_noise",
    }
    assert {key for key, entry in presets.items() if entry["category"] == "music"} == {
        "dreams",
        "drums",
        "impromptu",
        "lofi_rain",
        "meditation",
        "music_box_lullaby",
        "music_chimes",
        "piano",
        "river",
        "soothing_music",
    }
    for entry in presets.values():
        assert entry["label"]
        assert " " not in entry["label"]
        assert entry["feel"]
        assert entry["use"]
        assert entry["avoid"]


def test_chime_asset_is_short() -> None:
    with wave.open("assets/soothe/chime.wav", "rb") as wav:
        assert wav.getnchannels() == 1
        assert wav.getframerate() == 16_000
        assert wav.getsampwidth() == 2
        assert wav.getnframes() == 4_800
