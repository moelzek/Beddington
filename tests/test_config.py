from pathlib import Path

import pytest

from lullaby.config import load_config


def test_load_config_reads_detection_values(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[detection]
threshold = 0.4
sustained_seconds = 2.0
release_seconds = 0.5
notification_cooldown_seconds = 20

[notifications]
desktop = false

[soothe]
enabled = true
player = "none"
preset = "white_noise"

[soothe.presets.white_noise]
name = "white noise"
sound_path = "white-noise.wav"
wait_seconds = 2.5
play_seconds = 1800
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.detection.threshold == 0.4
    assert config.detection.sustained_seconds == 2.0
    assert config.notifications.desktop is False
    assert config.soothe.enabled is True
    assert config.soothe.preset == "white_noise"
    assert config.soothe.steps[0].name == "white noise"
    assert config.soothe.steps[0].sound_path == tmp_path / "white-noise.wav"
    assert config.soothe.steps[0].wait_seconds == 2.5
    assert config.soothe.steps[0].play_seconds == 1800.0


def test_default_config_points_at_generated_soothe_assets() -> None:
    config = load_config(Path("config/default.toml"))

    assert config.soothe.preset == "white_noise"
    assert sorted(config.soothe.presets) == [
        "heartbeat",
        "soothing_music",
        "uterine_whoosh",
        "white_noise",
    ]
    assert [step.name for step in config.soothe.steps] == ["white noise"]
    assert config.soothe.steps[0].play_seconds == 1800.0
    assert all(step.sound_path is not None for step in config.soothe.steps)
    assert all(step.sound_path.exists() for step in config.soothe.steps if step.sound_path)


def test_invalid_threshold_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[detection]\nthreshold = 1.5\n", encoding="utf-8")

    with pytest.raises(ValueError, match="between 0 and 1"):
        load_config(path)


def test_enabled_soothe_requires_steps(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[soothe]\nenabled = true\nsteps = []\n", encoding="utf-8")

    with pytest.raises(ValueError, match="selected preset"):
        load_config(path)


def test_soothe_preset_must_exist(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[soothe]
enabled = true
preset = "rain"

[soothe.presets.white_noise]
name = "white noise"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="soothe.preset"):
        load_config(path)
