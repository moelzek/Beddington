from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

from .live_snapshot import SnapshotThresholds


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
    enabled: bool = True
    backend: str = "ollama"
    model: str = "llama3.2:1b"
    host: str = "http://127.0.0.1:11434"
    # Optional, more capable desktop endpoint (e.g. gemma3:12b on a LAN box).
    # When set and reachable, voice calls prefer it; otherwise they fall back to
    # the Pi baseline above. Empty upgrade_host disables it (Pi-only default).
    upgrade_host: str = ""
    upgrade_model: str = ""
    upgrade_keep_alive: str = "10m"
    upgrade_probe_timeout: float = 1.0
    upgrade_probe_cache_seconds: float = 60.0
    num_predict: int = 140
    temperature: float = 0.3
    voice_enabled: bool = False
    voice_engine: str = "piper"
    piper_binary: str = "~/piper/piper"
    piper_model: str = "~/piper-voices/en_GB-jenny_dioco-medium.onnx"
    # Multi-speaker voices (e.g. en_GB-vctk) select a speaker by id; empty = the
    # voice's single/default speaker (no --speaker arg passed to Piper).
    piper_speaker: str = ""
    # User-facing speech speed: 1.0 is normal, 0.85 is a little slower.
    piper_speed: float = 1.0
    # Beddington persona: a local LLM re-voices each (benign) deterministic answer
    # in character, grounded + validated so it can never change a fact (see
    # persona.py). Reuses model/host above. Fails closed to the plain answer.
    persona_enabled: bool = True
    # Only restyle via the desktop upgrade endpoint: when the upgrade host is
    # absent/unreachable the persona step is skipped entirely, so Pi-only
    # answers keep their snappy deterministic latency.
    persona_upgrade_only: bool = False
    persona_temperature: float = 0.4
    persona_num_predict: int = 80
    persona_timeout: float = 8.0
    intent_num_predict: int = 8
    intent_temperature: float = 0.0
    intent_timeout: float = 8.0
    lead_num_predict: int = 70
    lead_temperature: float = 0.4
    lead_timeout: float = 8.0
    soothe_intent_num_predict: int = 80
    soothe_intent_temperature: float = 0.0
    soothe_intent_timeout: float = 8.0


@dataclass(frozen=True)
class LlmTranslatorConfig:
    enabled: bool = False
    intent_num_predict: int = 8
    intent_temperature: float = 0.0
    intent_timeout: float = 8.0
    lead_num_predict: int = 70
    lead_temperature: float = 0.4
    lead_timeout: float = 8.0
    soothe_intent_num_predict: int = 80
    soothe_intent_temperature: float = 0.0
    soothe_intent_timeout: float = 8.0


@dataclass(frozen=True)
class ConversationConfig:
    """Free-flowing chat mode (demo). Only active while the desktop upgrade
    endpoint is reachable: after Beddington answers, the mic stays open for a
    follow-up without a new wake word, replies may run 2-3 sentences, and the
    last few exchanges are fed back into the lead prompt as context."""

    enabled: bool = False
    window_seconds: float = 20.0
    num_predict: int = 120
    history_turns: int = 6


@dataclass(frozen=True)
class WeatherConfig:
    """Optional outside-weather answers via the free Open-Meteo API. The ONLY
    internet-bound call in the product; off by default (local-only)."""

    enabled: bool = False
    latitude: float = 0.0
    longitude: float = 0.0
    cache_seconds: float = 600.0


@dataclass(frozen=True)
class AssistantConfig:
    chime_enabled: bool = True
    llm_translator: LlmTranslatorConfig = LlmTranslatorConfig()
    conversation: ConversationConfig = ConversationConfig()
    weather: WeatherConfig = WeatherConfig()


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
class SootheLearnConfig:
    enabled: bool = False
    min_samples: int = 10


@dataclass(frozen=True)
class SootheConfig:
    enabled: bool = False
    player: str = "none"
    preset: str = "white_noise"
    min_play_seconds: float = 600.0
    hold_after_stop_seconds: float = 600.0
    escalate_after_seconds: float = 300.0
    presets: dict[str, SootheStepConfig] = field(default_factory=dict)
    steps: tuple[SootheStepConfig, ...] = (
        SootheStepConfig(name="white noise dry run", wait_seconds=30.0),
    )
    quiet_check: QuietCheckConfig = QuietCheckConfig()
    learn: SootheLearnConfig = SootheLearnConfig()


@dataclass(frozen=True)
class LiveviewAudioConfig:
    enabled: bool = False
    device: str | None = None
    max_listeners: int = 3
    talk_max_seconds: float = 20.0


@dataclass(frozen=True)
class LiveviewConfig:
    state: SnapshotThresholds = SnapshotThresholds()
    audio: LiveviewAudioConfig = LiveviewAudioConfig()


@dataclass(frozen=True)
class WorkerConfig:
    base_url: str = ""
    snapshot_interval_s: float = 3.0
    events_interval_s: float = 15.0
    request_timeout_s: float = 5.0
    analyzers: tuple[str, ...] = ()


@dataclass(frozen=True)
class AppConfig:
    detection: DetectionConfig = DetectionConfig()
    notifications: NotificationConfig = NotificationConfig()
    llm: LlmConfig = LlmConfig()
    narrator: NarratorConfig = NarratorConfig()
    assistant: AssistantConfig = AssistantConfig()
    sensors: SensorsConfig = SensorsConfig()
    sounds: SoundsConfig = SoundsConfig()
    soothe: SootheConfig = SootheConfig()
    liveview: LiveviewConfig = LiveviewConfig()
    worker: WorkerConfig = WorkerConfig()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return _coerce_bool(value, default)


def _coerce_bool(value: object, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _load_liveview(
    raw_liveview: object,
    default: LiveviewConfig,
) -> LiveviewConfig:
    if not isinstance(raw_liveview, dict):
        return default
    return LiveviewConfig(
        state=_load_liveview_state(raw_liveview.get("state", {}), default.state),
        audio=_load_liveview_audio(raw_liveview.get("audio", {}), default.audio),
    )


def _load_liveview_audio(
    raw_audio: object,
    default: LiveviewAudioConfig,
) -> LiveviewAudioConfig:
    if not isinstance(raw_audio, dict):
        return default
    raw_device = raw_audio.get("device", default.device)
    device = str(raw_device).strip() if raw_device is not None else None
    return LiveviewAudioConfig(
        enabled=_coerce_bool(raw_audio.get("enabled"), default.enabled),
        device=device or None,
        max_listeners=int(raw_audio.get("max_listeners", default.max_listeners)),
        talk_max_seconds=float(
            raw_audio.get("talk_max_seconds", default.talk_max_seconds)
        ),
    )


def _load_liveview_state(
    raw_state: object,
    default: SnapshotThresholds,
) -> SnapshotThresholds:
    if not isinstance(raw_state, dict):
        return default
    values: dict[str, object] = {}
    for item in fields(SnapshotThresholds):
        current = getattr(default, item.name)
        raw_value = raw_state.get(item.name, current)
        values[item.name] = int(raw_value) if isinstance(current, int) else float(raw_value)
    return SnapshotThresholds(**values)


def _load_worker(
    raw_worker: object,
    default: WorkerConfig,
) -> WorkerConfig:
    if not isinstance(raw_worker, dict):
        return default
    raw_analyzers = raw_worker.get("analyzers", default.analyzers)
    if isinstance(raw_analyzers, list):
        analyzers = tuple(str(item) for item in raw_analyzers)
    else:
        analyzers = default.analyzers
    return WorkerConfig(
        base_url=str(raw_worker.get("base_url", default.base_url)),
        snapshot_interval_s=float(
            raw_worker.get("snapshot_interval_s", default.snapshot_interval_s)
        ),
        events_interval_s=float(
            raw_worker.get("events_interval_s", default.events_interval_s)
        ),
        request_timeout_s=float(
            raw_worker.get("request_timeout_s", default.request_timeout_s)
        ),
        analyzers=analyzers,
    )


def load_config(path: Path | None = None) -> AppConfig:
    config = AppConfig()
    if path:
        with path.open("rb") as file:
            raw = tomllib.load(file)
        detection = raw.get("detection", {})
        notifications = raw.get("notifications", {})
        llm = raw.get("llm", {})
        narrator = raw.get("narrator", {})
        assistant = raw.get("assistant", {})
        sensors = raw.get("sensors", {})
        sounds = raw.get("sounds", {})
        soothe = raw.get("soothe", {})
        liveview = raw.get("liveview", {})
        worker = raw.get("worker", {})
        raw_soothe_presets = soothe.get("presets")
        raw_soothe_steps = soothe.get("steps")
        soothe_preset = str(soothe.get("preset", config.soothe.preset))
        soothe_presets = _load_soothe_presets(raw_soothe_presets, path.parent)
        quiet_check = _load_quiet_check(
            soothe.get("quiet_check", {}),
            config.soothe.quiet_check,
        )
        learn = _load_soothe_learn(
            soothe.get("learn", {}),
            config.soothe.learn,
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
        narrator_config = _load_narrator(narrator, config.narrator)
        assistant_config = _load_assistant(assistant, config.assistant)
        narrator_config = _apply_llm_translator_tuning(
            narrator_config,
            assistant_config.llm_translator,
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
                desktop=_coerce_bool(
                    notifications.get("desktop"),
                    config.notifications.desktop,
                )
            ),
            llm=LlmConfig(
                enabled=_coerce_bool(llm.get("enabled"), config.llm.enabled),
                base_url=str(llm.get("base_url", config.llm.base_url)),
                model=str(llm.get("model", config.llm.model)),
            ),
            narrator=narrator_config,
            assistant=assistant_config,
            sensors=_load_sensors(sensors, config.sensors),
            sounds=_load_sounds(sounds, config.sounds),
            soothe=SootheConfig(
                enabled=_coerce_bool(soothe.get("enabled"), config.soothe.enabled),
                player=str(soothe.get("player", config.soothe.player)),
                preset=soothe_preset,
                min_play_seconds=float(
                    soothe.get(
                        "min_play_seconds",
                        config.soothe.min_play_seconds,
                    )
                ),
                hold_after_stop_seconds=float(
                    soothe.get(
                        "hold_after_stop_seconds",
                        config.soothe.hold_after_stop_seconds,
                    )
                ),
                escalate_after_seconds=float(
                    soothe.get(
                        "escalate_after_seconds",
                        config.soothe.escalate_after_seconds,
                    )
                ),
                presets=soothe_presets,
                steps=soothe_steps,
                quiet_check=quiet_check,
                learn=learn,
            ),
            liveview=_load_liveview(liveview, config.liveview),
            worker=_load_worker(worker, config.worker),
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
        narrator=replace(
            config.narrator,
            upgrade_host=os.getenv(
                "BEDDINGTON_NARRATOR_UPGRADE_HOST", config.narrator.upgrade_host
            ),
            upgrade_model=os.getenv(
                "BEDDINGTON_NARRATOR_UPGRADE_MODEL", config.narrator.upgrade_model
            ),
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
        enabled=_coerce_bool(raw_quiet_check.get("enabled"), default.enabled),
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
        pause_during_check=_coerce_bool(
            raw_quiet_check.get("pause_during_check"),
            default.pause_during_check,
        ),
        stop_on_notify=_coerce_bool(
            raw_quiet_check.get("stop_on_notify"),
            default.stop_on_notify,
        ),
    )


def _load_soothe_learn(
    raw_learn: object,
    default: SootheLearnConfig,
) -> SootheLearnConfig:
    if not isinstance(raw_learn, dict):
        return default
    return SootheLearnConfig(
        enabled=_coerce_bool(raw_learn.get("enabled"), default.enabled),
        min_samples=int(raw_learn.get("min_samples", default.min_samples)),
    )


def _load_narrator(
    raw_narrator: object,
    default: NarratorConfig,
) -> NarratorConfig:
    if not isinstance(raw_narrator, dict):
        return default
    return NarratorConfig(
        enabled=_coerce_bool(raw_narrator.get("enabled"), default.enabled),
        backend=str(raw_narrator.get("backend", default.backend)),
        model=str(raw_narrator.get("model", default.model)),
        host=str(raw_narrator.get("host", default.host)),
        upgrade_host=str(raw_narrator.get("upgrade_host", default.upgrade_host)),
        upgrade_model=str(raw_narrator.get("upgrade_model", default.upgrade_model)),
        upgrade_keep_alive=str(
            raw_narrator.get("upgrade_keep_alive", default.upgrade_keep_alive)
        ),
        upgrade_probe_timeout=float(
            raw_narrator.get("upgrade_probe_timeout", default.upgrade_probe_timeout)
        ),
        upgrade_probe_cache_seconds=float(
            raw_narrator.get(
                "upgrade_probe_cache_seconds",
                default.upgrade_probe_cache_seconds,
            )
        ),
        num_predict=int(raw_narrator.get("num_predict", default.num_predict)),
        temperature=float(raw_narrator.get("temperature", default.temperature)),
        voice_enabled=_coerce_bool(
            raw_narrator.get("voice_enabled"),
            default.voice_enabled,
        ),
        voice_engine=str(raw_narrator.get("voice_engine", default.voice_engine)),
        piper_binary=str(raw_narrator.get("piper_binary", default.piper_binary)),
        piper_model=str(raw_narrator.get("piper_model", default.piper_model)),
        piper_speaker=str(raw_narrator.get("piper_speaker", default.piper_speaker)),
        piper_speed=float(raw_narrator.get("piper_speed", default.piper_speed)),
        persona_enabled=_coerce_bool(
            raw_narrator.get("persona_enabled"),
            default.persona_enabled,
        ),
        persona_upgrade_only=_coerce_bool(
            raw_narrator.get("persona_upgrade_only"),
            default.persona_upgrade_only,
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


def _load_assistant(
    raw_assistant: object,
    default: AssistantConfig,
) -> AssistantConfig:
    if not isinstance(raw_assistant, dict):
        return default
    return AssistantConfig(
        chime_enabled=_coerce_bool(
            raw_assistant.get("chime_enabled"),
            default.chime_enabled,
        ),
        llm_translator=_load_llm_translator(
            raw_assistant.get("llm_translator", {}),
            default.llm_translator,
        ),
        conversation=_load_conversation(
            raw_assistant.get("conversation", {}),
            default.conversation,
        ),
        weather=_load_weather(
            raw_assistant.get("weather", {}),
            default.weather,
        ),
    )


def _load_conversation(
    raw: object,
    default: ConversationConfig,
) -> ConversationConfig:
    if not isinstance(raw, dict):
        return default
    return ConversationConfig(
        enabled=_coerce_bool(raw.get("enabled"), default.enabled),
        window_seconds=float(raw.get("window_seconds", default.window_seconds)),
        num_predict=int(raw.get("num_predict", default.num_predict)),
        history_turns=int(raw.get("history_turns", default.history_turns)),
    )


def _load_weather(
    raw: object,
    default: WeatherConfig,
) -> WeatherConfig:
    if not isinstance(raw, dict):
        return default
    return WeatherConfig(
        enabled=_coerce_bool(raw.get("enabled"), default.enabled),
        latitude=float(raw.get("latitude", default.latitude)),
        longitude=float(raw.get("longitude", default.longitude)),
        cache_seconds=float(raw.get("cache_seconds", default.cache_seconds)),
    )


def _load_llm_translator(
    raw_translator: object,
    default: LlmTranslatorConfig,
) -> LlmTranslatorConfig:
    if not isinstance(raw_translator, dict):
        return default
    return LlmTranslatorConfig(
        enabled=_coerce_bool(raw_translator.get("enabled"), default.enabled),
        intent_num_predict=int(
            raw_translator.get("intent_num_predict", default.intent_num_predict)
        ),
        intent_temperature=float(
            raw_translator.get("intent_temperature", default.intent_temperature)
        ),
        intent_timeout=float(
            raw_translator.get("intent_timeout", default.intent_timeout)
        ),
        lead_num_predict=int(
            raw_translator.get("lead_num_predict", default.lead_num_predict)
        ),
        lead_temperature=float(
            raw_translator.get("lead_temperature", default.lead_temperature)
        ),
        lead_timeout=float(raw_translator.get("lead_timeout", default.lead_timeout)),
        soothe_intent_num_predict=int(
            raw_translator.get(
                "soothe_intent_num_predict",
                default.soothe_intent_num_predict,
            )
        ),
        soothe_intent_temperature=float(
            raw_translator.get(
                "soothe_intent_temperature",
                default.soothe_intent_temperature,
            )
        ),
        soothe_intent_timeout=float(
            raw_translator.get(
                "soothe_intent_timeout",
                default.soothe_intent_timeout,
            )
        ),
    )


def _apply_llm_translator_tuning(
    narrator: NarratorConfig,
    translator: LlmTranslatorConfig,
) -> NarratorConfig:
    return replace(
        narrator,
        intent_num_predict=translator.intent_num_predict,
        intent_temperature=translator.intent_temperature,
        intent_timeout=translator.intent_timeout,
        lead_num_predict=translator.lead_num_predict,
        lead_temperature=translator.lead_temperature,
        lead_timeout=translator.lead_timeout,
        soothe_intent_num_predict=translator.soothe_intent_num_predict,
        soothe_intent_temperature=translator.soothe_intent_temperature,
        soothe_intent_timeout=translator.soothe_intent_timeout,
    )


def _load_sounds(
    raw_sounds: object,
    default: SoundsConfig,
) -> SoundsConfig:
    if not isinstance(raw_sounds, dict):
        return default
    return SoundsConfig(
        enabled=_coerce_bool(raw_sounds.get("enabled"), default.enabled),
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
        enabled=_coerce_bool(raw_air.get("enabled"), default.enabled),
        i2c_address=int(raw_air.get("i2c_address", default.i2c_address)),
        gas=_coerce_bool(raw_air.get("gas"), default.gas),
    )


def _load_motion_sensor(
    raw_motion: object,
    default: MotionSensorConfig,
) -> MotionSensorConfig:
    if not isinstance(raw_motion, dict):
        return default
    return MotionSensorConfig(
        enabled=_coerce_bool(raw_motion.get("enabled"), default.enabled),
        gpio_pin=int(raw_motion.get("gpio_pin", default.gpio_pin)),
    )


def _load_radar_sensor(
    raw_radar: object,
    default: RadarSensorConfig,
) -> RadarSensorConfig:
    if not isinstance(raw_radar, dict):
        return default
    return RadarSensorConfig(
        enabled=_coerce_bool(raw_radar.get("enabled"), default.enabled),
        host=str(raw_radar.get("host", default.host)),
        port=int(raw_radar.get("port", default.port)),
        password=str(raw_radar.get("password", default.password)),
        include_distance=_coerce_bool(
            raw_radar.get("include_distance"),
            default.include_distance,
        ),
        include_target_count=_coerce_bool(
            raw_radar.get("include_target_count"),
            default.include_target_count,
        ),
        bench_vitals=_coerce_bool(
            raw_radar.get("bench_vitals"),
            default.bench_vitals,
        ),
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
    live_state = config.liveview.state
    for name, value in (
        ("max_reading_age_s", live_state.max_reading_age_s),
        ("max_camera_frame_age_s", live_state.max_camera_frame_age_s),
        ("max_radar_age_s", live_state.max_radar_age_s),
        ("state_min_dwell_s", live_state.state_min_dwell_s),
        ("cry_clear_grace_s", live_state.cry_clear_grace_s),
        ("presence_false_dwell_s", live_state.presence_false_dwell_s),
        ("motion_window_s", live_state.motion_window_s),
        ("motion_active_min_s", live_state.motion_active_min_s),
        ("wiggling_release_s", live_state.wiggling_release_s),
        ("still_min_s", live_state.still_min_s),
        ("still_exit_motion_s", live_state.still_exit_motion_s),
        ("quiet_window_s", live_state.quiet_window_s),
        ("room_temp_hysteresis_c", live_state.room_temp_hysteresis_c),
        ("caregiver_dwell_s", live_state.caregiver_dwell_s),
        ("caregiver_release_s", live_state.caregiver_release_s),
        ("t2_repeat_cooldown_s", live_state.t2_repeat_cooldown_s),
        ("device_restart_notice_s", live_state.device_restart_notice_s),
    ):
        if value < 0:
            raise ValueError(f"liveview.state.{name} must be non-negative")
    for name, value in (
        ("health_bad_checks_to_enter", live_state.health_bad_checks_to_enter),
        ("health_recovered_checks_to_exit", live_state.health_recovered_checks_to_exit),
        ("caregiver_min_targets", live_state.caregiver_min_targets),
        ("max_evidence_items", live_state.max_evidence_items),
    ):
        if value < 1:
            raise ValueError(f"liveview.state.{name} must be at least 1")
    if live_state.quiet_max_motion_transitions < 0:
        raise ValueError("liveview.state.quiet_max_motion_transitions must be non-negative")
    if live_state.room_cold_below_c >= live_state.room_warm_above_c:
        raise ValueError("liveview.state.room_cold_below_c must be less than room_warm_above_c")
    if live_state.room_temp_hysteresis_c > 2.0:
        raise ValueError("liveview.state.room_temp_hysteresis_c must be between 0 and 2")
    live_audio = config.liveview.audio
    if live_audio.max_listeners < 1:
        raise ValueError("liveview.audio.max_listeners must be at least 1")
    if live_audio.talk_max_seconds <= 0:
        raise ValueError("liveview.audio.talk_max_seconds must be positive")
    if config.soothe.player not in {"none", "auto"}:
        raise ValueError("soothe.player must be 'none' or 'auto'")
    if config.soothe.min_play_seconds < 0:
        raise ValueError("soothe.min_play_seconds must be non-negative")
    if config.soothe.hold_after_stop_seconds < 0:
        raise ValueError("soothe.hold_after_stop_seconds must be non-negative")
    if config.soothe.escalate_after_seconds < 0:
        raise ValueError("soothe.escalate_after_seconds must be non-negative")
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
    if config.soothe.learn.min_samples < 1:
        raise ValueError("soothe.learn.min_samples must be at least 1")
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
    if narrator.piper_speed <= 0:
        raise ValueError("narrator.piper_speed must be positive")
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
    worker = config.worker
    if worker.base_url.strip() and not worker.base_url.startswith(("http://", "https://")):
        raise ValueError("worker.base_url must start with http:// or https://")
    if worker.snapshot_interval_s <= 0:
        raise ValueError("worker.snapshot_interval_s must be positive")
    if worker.events_interval_s <= 0:
        raise ValueError("worker.events_interval_s must be positive")
    if worker.request_timeout_s <= 0:
        raise ValueError("worker.request_timeout_s must be positive")
