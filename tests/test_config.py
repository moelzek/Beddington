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

[sounds]
enabled = true
threshold = 0.3

[soothe]
enabled = true
player = "none"
preset = "white_noise"

[soothe.quiet_check]
enabled = true
check_interval_seconds = 5.0
listen_seconds = 1.0
required_checks = 2
quiet_threshold = 0.3
pause_during_check = true
stop_on_notify = true

[soothe.presets.white_noise]
name = "white noise"
sound_path = "white-noise.wav"
wait_seconds = 2.5
play_seconds = 1800

[narrator]
enabled = true
backend = "ollama"
model = "llama3.2:1b"
host = "http://127.0.0.1:11434"
num_predict = 100
temperature = 0.2
voice_enabled = true
voice_engine = "piper"
piper_binary = "~/piper/piper"
piper_model = "~/piper-voices/en_GB-jenny_dioco-medium.onnx"

[sensors]
sample_interval_seconds = 3.5

[sensors.air]
enabled = true
i2c_address = 0x76
gas = true

[sensors.motion]
enabled = true
gpio_pin = 4
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
    assert config.soothe.quiet_check.enabled is True
    assert config.soothe.quiet_check.check_interval_seconds == 5.0
    assert config.soothe.quiet_check.listen_seconds == 1.0
    assert config.soothe.quiet_check.required_checks == 2
    assert config.soothe.quiet_check.quiet_threshold == 0.3
    assert config.narrator.enabled is True
    assert config.narrator.backend == "ollama"
    assert config.narrator.model == "llama3.2:1b"
    assert config.narrator.host == "http://127.0.0.1:11434"
    assert config.narrator.num_predict == 100
    assert config.narrator.temperature == 0.2
    assert config.narrator.voice_enabled is True
    assert config.narrator.voice_engine == "piper"
    assert config.sounds.enabled is True
    assert config.sounds.threshold == 0.3
    assert config.sensors.sample_interval_seconds == 3.5
    assert config.sensors.air.enabled is True
    assert config.sensors.air.i2c_address == 0x76
    assert config.sensors.air.gas is True
    assert config.sensors.motion.enabled is True
    assert config.sensors.motion.gpio_pin == 4


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
    assert config.sensors.sample_interval_seconds == 10.0
    assert config.sensors.air.enabled is False
    assert config.sensors.air.i2c_address == 0x76
    assert config.sensors.motion.enabled is False
    assert config.sensors.motion.gpio_pin == 4


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


def test_quiet_check_requires_repeated_checks(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[soothe.quiet_check]
enabled = true
required_checks = 1
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="required_checks"):
        load_config(path)


def test_quiet_check_threshold_must_not_exceed_detection_threshold(
    tmp_path: Path,
) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[detection]
threshold = 0.4

[soothe.quiet_check]
enabled = true
quiet_threshold = 0.5
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="quiet_threshold"):
        load_config(path)


def test_narrator_backend_must_be_ollama(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[narrator]\nbackend = \"cloud\"\n", encoding="utf-8")

    with pytest.raises(ValueError, match="narrator.backend"):
        load_config(path)


def test_sensor_sample_interval_must_be_positive(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[sensors]\nsample_interval_seconds = 0\n", encoding="utf-8")

    with pytest.raises(ValueError, match="sensors.sample_interval_seconds"):
        load_config(path)


def test_air_sensor_address_must_be_7_bit(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[sensors.air]\ni2c_address = 0x80\n", encoding="utf-8")

    with pytest.raises(ValueError, match="sensors.air.i2c_address"):
        load_config(path)


def test_motion_sensor_gpio_pin_must_be_non_negative(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[sensors.motion]\ngpio_pin = -1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="sensors.motion.gpio_pin"):
        load_config(path)


def test_load_config_reads_radar_values(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[sensors.radar]
enabled = true
host = "192.168.1.146"
port = 6053
include_distance = false
include_target_count = true
bench_vitals = true
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.sensors.radar.enabled is True
    assert config.sensors.radar.host == "192.168.1.146"
    assert config.sensors.radar.port == 6053
    assert config.sensors.radar.include_distance is False
    assert config.sensors.radar.include_target_count is True
    assert config.sensors.radar.bench_vitals is True


def test_radar_bench_vitals_defaults_off() -> None:
    config = load_config(Path("config/default.toml"))

    assert config.sensors.radar.bench_vitals is False


def test_radar_requires_host_when_enabled(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[sensors.radar]\nenabled = true\n", encoding="utf-8")

    with pytest.raises(ValueError, match="sensors.radar.host"):
        load_config(path)


def test_sounds_threshold_must_be_in_range(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[sounds]\nthreshold = 1.5\n", encoding="utf-8")

    with pytest.raises(ValueError, match="sounds.threshold"):
        load_config(path)
