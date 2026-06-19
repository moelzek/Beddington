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
class AppConfig:
    detection: DetectionConfig = DetectionConfig()
    notifications: NotificationConfig = NotificationConfig()
    llm: LlmConfig = LlmConfig()


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
    )
    _validate(config)
    return config


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
