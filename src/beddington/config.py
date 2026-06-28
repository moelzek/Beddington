from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path


@dataclass(frozen=True)
class DetectionConfig:
    threshold: float = 0.40
    sustained_seconds: float = 1.5
    release_seconds: float = 1.0
    notification_cooldown_seconds: float = 30.0


@dataclass(frozen=True)
class NotificationConfig:
    desktop: bool = True


@dataclass(frozen=True)
class SoundsConfig:
    # Record non-cry baby/room sounds the mic hears (cooing, laughter, snoring...)
    # as observer-only context. Off by default; never affects cry detection.
    enabled: bool = False
    threshold: float = 0.2


@dataclass(frozen=True)
class LlmConfig:
    enabled: bool = False
    base_url: str = ""
    model: str = ""
    api_key: str = ""


@dataclass(frozen=True)
class NarratorConfig:
    enabled: bool = False
    backend: str = "ollama"
    model: str = "llama3.2:1b"
    host: str = "http://127.0.0.1:11434"
    num_predict: int = 140
    temperature: float = 0.3
    voice_enabled: bool = False
    voice_engine: str = "piper"
    piper_binary: str = "~/piper/piper"
    piper_model: str = "~/piper-voices/en_GB-jenny_dioco-medium.onnx"
    # Multi-speaker voices (e.g. en_GB-vctk) select a speaker by id; empty = the
    # voice's single/default speaker (no --speaker arg passed to Piper).
    piper_speaker: str = ""
    # Beddington persona: a local LLM re-voices each (benign) deterministic answer
    # in character, grounded + validated so it can never change a fact (see
    # persona.py). Reuses model/host above. Fails closed to the plain answer.
    persona_enabled: bool = True
    persona_temperature: float = 0.4
    persona_num_predict: int = 80
    persona_timeout: float = 8.0


@dataclass(frozen=True)
class AirSensorConfig:
    enabled: bool = False
    i2c_address: int = 0x76
    # Also read the BME688 gas/VOC channel (experimental nappy-VOC best guess).
    # The gas heater needs a few seconds to stabilise before readings appear.
    gas: bool = False


@dataclass(frozen=True)
class MotionSensorConfig:
    enabled: bool = False
    gpio_pin: int = 4


@dataclass(frozen=True)
class RadarSensorConfig:
    enabled: bool = False
    host: str = ""
    port: int = 6053
    password: str = ""
    include_distance: bool = True
    include_target_count: bool = True
    # Bench/research only: capture the radar's respiratory + heart-rate values as
    # raw, clearly-labelled bench data. Off by default. These are never fed into
    # the product narration and are never a medical or safety signal.
    bench_vitals: bool = False


@dataclass(frozen=True)
class SensorsConfig:
    air: AirSensorConfig = AirSensorConfig()
    motion: MotionSensorConfig = MotionSensorConfig()
    radar: RadarSensorConfig = RadarSensorConfig()
    sample_interval_seconds: float = 10.0


@dataclass(frozen=True)
class SootheStepConfig:
    name: str
    sound_path: Path | None = None
    wait_seconds: float = 30.0
    play_seconds: float | None = None


@dataclass(frozen=True)
class QuietCheckConfig:
    enabled: bool = False
    check_interval_seconds: float = 120.0
    listen_seconds: float = 5.0
    required_checks: int = 2
    quiet_threshold: float | None = None
    pause_during_check: bool = True
    stop_on_notify: bool = True


@dataclass(frozen=True)
class SootheConfig:
    enabled: bool = False
    player: str = "none"
    preset: str = "white_noise"
    presets: dict[str, SootheStepConfig] = field(default_factory=dict)
    steps: tuple[SootheStepConfig, ...] = (
        SootheStepConfig(name="white noise dry run", wait_seconds=30.0),
    )
    quiet_check: QuietCheckConfig = QuietCheckConfig()


@dataclass(frozen=True)
class AppConfig:
    detection: DetectionConfig = DetectionConfig()
    notifications: NotificationConfig = NotificationConfig()
    llm: LlmConfig = LlmConfig()
    narrator: NarratorConfig = NarratorConfig()
    sensors: SensorsConfig = SensorsConfig()
    sounds: SoundsConfig = SoundsConfig()
    soothe: SootheConfig = SootheConfig()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_config(path: Path | None = None) -> AppConfig:
    config = AppConfig()
    if path:
        with path.open("rb") as file:
            raw = tomllib.load(file)
        detection = raw.get("detection", {})
        notifications = raw.get("notifications", {})
        llm = raw.get("llm", {})
        narrator = raw.get("narrator", {})
        sensors = raw.get("sensors", {})
        sounds = raw.get("sounds", {})
        soothe = raw.get("soothe", {})
        raw_soothe_presets = soothe.get("presets")
        raw_soothe_steps = soothe.get("steps")
        soothe_preset = str(soothe.get("preset", config.soothe.preset))
        soothe_presets = _load_soothe_presets(raw_soothe_presets, path.parent)
        quiet_check = _load_quiet_check(
            soothe.get("quiet_check", {}),
            config.soothe.quiet_check,
        )
        soothe_steps = (
            (soothe_presets[soothe_preset],)
            if soothe_presets and soothe_preset in soothe_presets
            else (
                _load_soothe_steps(raw_soothe_steps, path.parent)
                if raw_soothe_steps is not None
                else config.soothe.steps
            )
        )
        config = AppConfig(
            detection=DetectionConfig(
                threshold=float(detection.get("threshold", config.detection.threshold)),
                sustained_seconds=float(
                    detection.get("sustained_seconds", config.detection.sustained_seconds)
                ),
                release_seconds=float(
                    detection.get("release_seconds", config.detection.release_seconds)
                ),
                notification_cooldown_seconds=float(
                    detection.get(
                        "notification_cooldown_seconds",
                        config.detection.notification_cooldown_seconds,
                    )
                ),
            ),
            notifications=NotificationConfig(
                desktop=bool(notifications.get("desktop", config.notifications.desktop))
            ),
            llm=LlmConfig(
                enabled=bool(llm.get("enabled", config.llm.enabled)),
                base_url=str(llm.get("base_url", config.llm.base_url)),
                model=str(llm.get("model", config.llm.model)),
            ),
            narrator=_load_narrator(narrator, config.narrator),
            sensors=_load_sensors(sensors, config.sensors),
            sounds=_load_sounds(sounds, config.sounds),
            soothe=SootheConfig(
                enabled=bool(soothe.get("enabled", config.soothe.enabled)),
                player=str(soothe.get("player", config.soothe.player)),
                preset=soothe_preset,
                presets=soothe_presets,
                steps=soothe_steps,
                quiet_check=quiet_check,
            ),
        )

    config = replace(
        config,
        llm=replace(
            config.llm,
            enabled=_env_bool("BEDDINGTON_LLM_ENABLED", config.llm.enabled),
            base_url=os.getenv("BEDDINGTON_LLM_BASE_URL", config.llm.base_url),
            model=os.getenv("BEDDINGTON_LLM_MODEL", config.llm.model),
            api_key=os.getenv("BEDDINGTON_LLM_API_KEY", ""),
        ),
        soothe=replace(
            config.soothe,
            enabled=_env_bool("BEDDINGTON_SOOTHE_ENABLED", config.soothe.enabled),
            player=os.getenv("BEDDINGTON_SOOTHE_PLAYER", config.soothe.player),
        ),
    )
    _validate(config)
    return config


def _load_soothe_steps(raw_steps: object, config_dir: Path) -> tuple[SootheStepConfig, ...]:
    if not isinstance(raw_steps, list):
        return ()

    steps: list[SootheStepConfig] = []
    for index, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, dict):
            raise ValueError(f"soothe.steps[{index}] must be a table")
        sound_path = str(raw_step.get("sound_path", "")).strip()
        path = Path(sound_path).expanduser() if sound_path else None
        if path is not None and not path.is_absolute():
            path = config_dir / path
        steps.append(
            SootheStepConfig(
                name=str(raw_step.get("name", f"step {index}")),
                sound_path=path,
                wait_seconds=float(raw_step.get("wait_seconds", 30.0)),
                play_seconds=(
                    float(raw_step["play_seconds"])
                    if "play_seconds" in raw_step
                    else None
                ),
            )
        )
    return tuple(steps)


def _load_soothe_presets(
    raw_presets: object,
    config_dir: Path,
) -> dict[str, SootheStepConfig]:
    if not isinstance(raw_presets, dict):
        return {}

    presets: dict[str, SootheStepConfig] = {}
    for key, raw_step in raw_presets.items():
        if not isinstance(raw_step, dict):
            raise ValueError(f"soothe.presets.{key} must be a table")
        presets[str(key)] = _load_soothe_step(raw_step, config_dir, str(key))
    return presets


def _load_soothe_step(
    raw_step: dict[str, object],
    config_dir: Path,
    fallback_name: str,
) -> SootheStepConfig:
    sound_path = str(raw_step.get("sound_path", "")).strip()
    path = Path(sound_path).expanduser() if sound_path else None
    if path is not None and not path.is_absolute():
        path = config_dir / path
    return SootheStepConfig(
        name=str(raw_step.get("name", fallback_name.replace("_", " "))),
        sound_path=path,
        wait_seconds=float(raw_step.get("wait_seconds", 30.0)),
        play_seconds=(
            float(raw_step["play_seconds"])
            if "play_seconds" in raw_step
            else None
        ),
    )


def _load_quiet_check(
    raw_quiet_check: object,
    default: QuietCheckConfig,
) -> QuietCheckConfig:
    if not isinstance(raw_quiet_check, dict):
        return default
    quiet_threshold = (
        float(raw_quiet_check["quiet_threshold"])
        if "quiet_threshold" in raw_quiet_check
        else default.quiet_threshold
    )
    return QuietCheckConfig(
        enabled=bool(raw_quiet_check.get("enabled", default.enabled)),
        check_interval_seconds=float(
            raw_quiet_check.get(
                "check_interval_seconds",
                default.check_interval_seconds,
            )
        ),
        listen_seconds=float(
            raw_quiet_check.get("listen_seconds", default.listen_seconds)
        ),
        required_checks=int(
            raw_quiet_check.get("required_checks", default.required_checks)
        ),
        quiet_threshold=quiet_threshold,
        pause_during_check=bool(
            raw_quiet_check.get("pause_during_check", default.pause_during_check)
        ),
        stop_on_notify=bool(
            raw_quiet_check.get("stop_on_notify", default.stop_on_notify)
        ),
    )


def _load_narrator(
    raw_narrator: object,
    default: NarratorConfig,
) -> NarratorConfig:
    if not isinstance(raw_narrator, dict):
        return default
    return NarratorConfig(
        enabled=bool(raw_narrator.get("enabled", default.enabled)),
        backend=str(raw_narrator.get("backend", default.backend)),
        model=str(raw_narrator.get("model", default.model)),
        host=str(raw_narrator.get("host", default.host)),
        num_predict=int(raw_narrator.get("num_predict", default.num_predict)),
        temperature=float(raw_narrator.get("temperature", default.temperature)),
        voice_enabled=bool(
            raw_narrator.get("voice_enabled", default.voice_enabled)
        ),
        voice_engine=str(raw_narrator.get("voice_engine", default.voice_engine)),
        piper_binary=str(raw_narrator.get("piper_binary", default.piper_binary)),
        piper_model=str(raw_narrator.get("piper_model", default.piper_model)),
        piper_speaker=str(raw_narrator.get("piper_speaker", default.piper_speaker)),
        persona_enabled=bool(
            raw_narrator.get("persona_enabled", default.persona_enabled)
        ),
        persona_temperature=float(
            raw_narrator.get("persona_temperature", default.persona_temperature)
        ),
        persona_num_predict=int(
            raw_narrator.get("persona_num_predict", default.persona_num_predict)
        ),
        persona_timeout=float(
            raw_narrator.get("persona_timeout", default.persona_timeout)
        ),
    )


def _load_sounds(
    raw_sounds: object,
    default: SoundsConfig,
) -> SoundsConfig:
    if not isinstance(raw_sounds, dict):
        return default
    return SoundsConfig(
        enabled=bool(raw_sounds.get("enabled", default.enabled)),
        threshold=float(raw_sounds.get("threshold", default.threshold)),
    )


def _load_sensors(
    raw_sensors: object,
    default: SensorsConfig,
) -> SensorsConfig:
    if not isinstance(raw_sensors, dict):
        return default
    raw_air = raw_sensors.get("air", {})
    raw_motion = raw_sensors.get("motion", {})
    raw_radar = raw_sensors.get("radar", {})
    return SensorsConfig(
        air=_load_air_sensor(raw_air, default.air),
        motion=_load_motion_sensor(raw_motion, default.motion),
        radar=_load_radar_sensor(raw_radar, default.radar),
        sample_interval_seconds=float(
            raw_sensors.get(
                "sample_interval_seconds",
                default.sample_interval_seconds,
            )
        ),
    )


def _load_air_sensor(
    raw_air: object,
    default: AirSensorConfig,
) -> AirSensorConfig:
    if not isinstance(raw_air, dict):
        return default
    return AirSensorConfig(
        enabled=bool(raw_air.get("enabled", default.enabled)),
        i2c_address=int(raw_air.get("i2c_address", default.i2c_address)),
        gas=bool(raw_air.get("gas", default.gas)),
    )


def _load_motion_sensor(
    raw_motion: object,
    default: MotionSensorConfig,
) -> MotionSensorConfig:
    if not isinstance(raw_motion, dict):
        return default
    return MotionSensorConfig(
        enabled=bool(raw_motion.get("enabled", default.enabled)),
        gpio_pin=int(raw_motion.get("gpio_pin", default.gpio_pin)),
    )


def _load_radar_sensor(
    raw_radar: object,
    default: RadarSensorConfig,
) -> RadarSensorConfig:
    if not isinstance(raw_radar, dict):
        return default
    return RadarSensorConfig(
        enabled=bool(raw_radar.get("enabled", default.enabled)),
        host=str(raw_radar.get("host", default.host)),
        port=int(raw_radar.get("port", default.port)),
        password=str(raw_radar.get("password", default.password)),
        include_distance=bool(
            raw_radar.get("include_distance", default.include_distance)
        ),
        include_target_count=bool(
            raw_radar.get("include_target_count", default.include_target_count)
        ),
        bench_vitals=bool(raw_radar.get("bench_vitals", default.bench_vitals)),
    )


def _validate(config: AppConfig) -> None:
    if not 0.0 <= config.detection.threshold <= 1.0:
        raise ValueError("detection.threshold must be between 0 and 1")
    for name, value in (
        ("sustained_seconds", config.detection.sustained_seconds),
        ("release_seconds", config.detection.release_seconds),
        (
            "notification_cooldown_seconds",
            config.detection.notification_cooldown_seconds,
        ),
    ):
        if value < 0:
            raise ValueError(f"detection.{name} must be non-negative")
    if config.soothe.player not in {"none", "auto"}:
        raise ValueError("soothe.player must be 'none' or 'auto'")
    if config.soothe.enabled and not config.soothe.steps:
        raise ValueError(
            "soothe must include one selected preset or one step when enabled"
        )
    if config.soothe.presets and config.soothe.preset not in config.soothe.presets:
        options = ", ".join(sorted(config.soothe.presets))
        raise ValueError(f"soothe.preset must be one of: {options}")
    if len(config.soothe.steps) > 1:
        raise ValueError("soothe must select exactly one preset or one step")
    for index, step in enumerate(config.soothe.steps, start=1):
        if not step.name.strip():
            raise ValueError(f"soothe.steps[{index}].name must not be empty")
        if step.wait_seconds < 0:
            raise ValueError(f"soothe.steps[{index}].wait_seconds must be non-negative")
        if step.play_seconds is not None and step.play_seconds < 0:
            raise ValueError(f"soothe.steps[{index}].play_seconds must be non-negative")
    quiet_check = config.soothe.quiet_check
    if quiet_check.check_interval_seconds <= 0:
        raise ValueError("soothe.quiet_check.check_interval_seconds must be positive")
    if quiet_check.listen_seconds <= 0:
        raise ValueError("soothe.quiet_check.listen_seconds must be positive")
    if quiet_check.required_checks < 2:
        raise ValueError("soothe.quiet_check.required_checks must be at least 2")
    if quiet_check.quiet_threshold is not None:
        if not 0.0 <= quiet_check.quiet_threshold <= 1.0:
            raise ValueError("soothe.quiet_check.quiet_threshold must be between 0 and 1")
        if quiet_check.quiet_threshold > config.detection.threshold:
            raise ValueError(
                "soothe.quiet_check.quiet_threshold must be less than or equal "
                "to detection.threshold"
            )
    narrator = config.narrator
    if narrator.backend != "ollama":
        raise ValueError("narrator.backend must be 'ollama'")
    if not narrator.model.strip():
        raise ValueError("narrator.model must not be empty")
    if not narrator.host.strip():
        raise ValueError("narrator.host must not be empty")
    if narrator.num_predict <= 0:
        raise ValueError("narrator.num_predict must be positive")
    if narrator.temperature < 0:
        raise ValueError("narrator.temperature must be non-negative")
    if narrator.voice_engine not in {"piper", "espeak-ng"}:
        raise ValueError("narrator.voice_engine must be 'piper' or 'espeak-ng'")
    if not narrator.piper_binary.strip():
        raise ValueError("narrator.piper_binary must not be empty")
    if not narrator.piper_model.strip():
        raise ValueError("narrator.piper_model must not be empty")
    sensors = config.sensors
    if sensors.sample_interval_seconds <= 0:
        raise ValueError("sensors.sample_interval_seconds must be positive")
    if not 0 <= sensors.air.i2c_address <= 0x7F:
        raise ValueError("sensors.air.i2c_address must be a 7-bit I2C address")
    if sensors.motion.gpio_pin < 0:
        raise ValueError("sensors.motion.gpio_pin must be non-negative")
    if sensors.radar.enabled and not sensors.radar.host.strip():
        raise ValueError("sensors.radar.host must be set when sensors.radar.enabled")
    if not 1 <= sensors.radar.port <= 65535:
        raise ValueError("sensors.radar.port must be a valid TCP port")
    if not 0.0 <= config.sounds.threshold <= 1.0:
        raise ValueError("sounds.threshold must be between 0 and 1")
