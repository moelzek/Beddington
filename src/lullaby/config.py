from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, replace
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
class LlmConfig:
    enabled: bool = False
    base_url: str = ""
    model: str = ""
    api_key: str = ""


@dataclass(frozen=True)
class SootheStepConfig:
    name: str
    sound_path: Path | None = None
    wait_seconds: float = 30.0


@dataclass(frozen=True)
class SootheConfig:
    enabled: bool = False
    player: str = "none"
    steps: tuple[SootheStepConfig, ...] = (
        SootheStepConfig(name="white noise dry run", wait_seconds=30.0),
    )


@dataclass(frozen=True)
class AppConfig:
    detection: DetectionConfig = DetectionConfig()
    notifications: NotificationConfig = NotificationConfig()
    llm: LlmConfig = LlmConfig()
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
        soothe = raw.get("soothe", {})
        raw_soothe_steps = soothe.get("steps")
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
            soothe=SootheConfig(
                enabled=bool(soothe.get("enabled", config.soothe.enabled)),
                player=str(soothe.get("player", config.soothe.player)),
                steps=(
                    _load_soothe_steps(raw_soothe_steps, path.parent)
                    if raw_soothe_steps is not None
                    else config.soothe.steps
                ),
            ),
        )

    config = replace(
        config,
        llm=replace(
            config.llm,
            enabled=_env_bool("LULLABY_LLM_ENABLED", config.llm.enabled),
            base_url=os.getenv("LULLABY_LLM_BASE_URL", config.llm.base_url),
            model=os.getenv("LULLABY_LLM_MODEL", config.llm.model),
            api_key=os.getenv("LULLABY_LLM_API_KEY", ""),
        ),
        soothe=replace(
            config.soothe,
            enabled=_env_bool("LULLABY_SOOTHE_ENABLED", config.soothe.enabled),
            player=os.getenv("LULLABY_SOOTHE_PLAYER", config.soothe.player),
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
            )
        )
    return tuple(steps)


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
        raise ValueError("soothe.steps must include at least one step when soothe is enabled")
    for index, step in enumerate(config.soothe.steps, start=1):
        if not step.name.strip():
            raise ValueError(f"soothe.steps[{index}].name must not be empty")
        if step.wait_seconds < 0:
            raise ValueError(f"soothe.steps[{index}].wait_seconds must be non-negative")
