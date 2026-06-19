"""Deterministic local monitor for Lullaby.

This module intentionally avoids medical conclusions. It turns simple local
observations into caregiver check prompts when a configured condition persists.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class Observation:
    """One local observation from a camera, mic, sensor, or replay script."""

    baby_present: bool = True
    motion: str = "settled"  # settled | restless | active | unknown
    sound: str = "quiet"  # quiet | fussing | crying | unknown
    view_clear: Optional[bool] = True
    room_temp_c: Optional[float] = None
    confidence: float = 0.0


@dataclass(frozen=True)
class MonitorPolicy:
    """Configured thresholds for caregiver check prompts."""

    crying_seconds: float = 30.0
    view_blocked_seconds: float = 10.0
    restless_seconds: Optional[float] = None
    min_room_temp_c: Optional[float] = None
    max_room_temp_c: Optional[float] = None


@dataclass(frozen=True)
class StatusLogged:
    at: float
    summary: str


@dataclass(frozen=True)
class AttentionNeeded:
    at: float
    condition: str
    reason: str
    duration: float

    def message(self) -> str:
        return f"Check baby: {self.reason} for {self.duration:.0f}s"


@dataclass(frozen=True)
class ConditionCleared:
    at: float
    condition: str
    duration: float


class LullabyMonitor:
    """Rule engine that works without an LLM or network connection."""

    def __init__(self, policy: MonitorPolicy, *, clock=time.monotonic):
        self.policy = policy
        self._clock = clock
        self._active_since: Dict[str, float] = {}
        self._flagged: set[str] = set()

    def update(self, observation: Observation, now: Optional[float] = None) -> list:
        now = self._clock() if now is None else now
        active = self._conditions(observation)
        events = [StatusLogged(now, self._summary(observation))]

        for condition in list(self._active_since):
            if condition not in active:
                started = self._active_since.pop(condition)
                self._flagged.discard(condition)
                events.append(ConditionCleared(now, condition, now - started))

        for condition, reason in active.items():
            started = self._active_since.setdefault(condition, now)
            threshold = self._threshold(condition)
            duration = now - started
            if threshold is not None and duration >= threshold and condition not in self._flagged:
                self._flagged.add(condition)
                events.append(AttentionNeeded(now, condition, reason, duration))

        return events

    def _conditions(self, observation: Observation) -> Dict[str, str]:
        conditions: Dict[str, str] = {}
        if observation.sound == "crying":
            conditions["crying"] = "crying has continued"
        if observation.view_clear is False:
            conditions["view_blocked"] = "camera view is blocked"
        if self.policy.restless_seconds is not None and observation.motion == "restless":
            conditions["restless"] = "restless movement has continued"
        if self._room_temp_out_of_range(observation.room_temp_c):
            conditions["room_comfort"] = "room comfort reading is outside the configured range"
        return conditions

    def _threshold(self, condition: str) -> Optional[float]:
        if condition == "crying":
            return self.policy.crying_seconds
        if condition == "view_blocked":
            return self.policy.view_blocked_seconds
        if condition == "restless":
            return self.policy.restless_seconds
        if condition == "room_comfort":
            return 0.0
        return None

    def _room_temp_out_of_range(self, temp: Optional[float]) -> bool:
        if temp is None:
            return False
        if self.policy.min_room_temp_c is not None and temp < self.policy.min_room_temp_c:
            return True
        if self.policy.max_room_temp_c is not None and temp > self.policy.max_room_temp_c:
            return True
        return False

    def _summary(self, observation: Observation) -> str:
        present = "present" if observation.baby_present else "not detected"
        view = "clear" if observation.view_clear else "blocked"
        return f"baby={present}; motion={observation.motion}; sound={observation.sound}; view={view}"
