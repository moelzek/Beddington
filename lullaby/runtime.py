"""Runtime seams for Lullaby: perceivers, journals, alerts, and the loop."""

from __future__ import annotations

import time
from typing import Iterable, Optional
from typing import Protocol as Interface
from typing import runtime_checkable

from .monitor import (
    AttentionNeeded,
    ConditionCleared,
    LullabyMonitor,
    MonitorPolicy,
    Observation,
    StatusLogged,
)


@runtime_checkable
class Perceiver(Interface):
    """Frame or audio chunk in, local Observation out."""

    def observe(self, frame: bytes) -> Observation:
        ...


class MockPerceiver:
    """Replays scripted observations for demos and tests."""

    def __init__(self, script: Iterable[Observation]):
        self._script = list(script)
        self._i = 0

    def observe(self, frame: bytes = b"") -> Observation:
        observation = self._script[self._i] if self._i < len(self._script) else Observation()
        self._i += 1
        return observation


class LocalVisionPerceiver:  # pragma: no cover - hardware dependent stub
    """Placeholder for a local camera/mic implementation.

    It must return simple observations and must not upload raw media.
    """

    def observe(self, frame: bytes) -> Observation:
        raise NotImplementedError("Wire a local camera/mic perceiver before using this.")


@runtime_checkable
class Journal(Interface):
    def entry(self, text: str, at: float) -> None:
        ...


@runtime_checkable
class Alert(Interface):
    def check(self, message: str) -> None:
        ...


class ConsoleJournal:
    def entry(self, text: str, at: float) -> None:
        print(f"  [local log {at:7.1f}s] {text}")


class ConsoleAlert:
    def check(self, message: str) -> None:
        print(f"  CHECK: {message}")


class Lullaby:
    """The loop: local signal -> observation -> deterministic rules -> outputs."""

    def __init__(
        self,
        perceiver: Perceiver,
        *,
        policy: Optional[MonitorPolicy] = None,
        journal: Journal,
        alert: Alert,
        clock=time.monotonic,
    ):
        self.monitor = LullabyMonitor(policy or MonitorPolicy(), clock=clock)
        self.perceiver = perceiver
        self.journal = journal
        self.alert = alert

    def step(self, frame: bytes = b"", now: Optional[float] = None) -> None:
        observation = self.perceiver.observe(frame)
        for event in self.monitor.update(observation, now=now):
            self._route(event)

    def _route(self, event) -> None:
        if isinstance(event, StatusLogged):
            self.journal.entry(event.summary, event.at)
        elif isinstance(event, AttentionNeeded):
            self.alert.check(event.message())
        elif isinstance(event, ConditionCleared):
            self.journal.entry(
                f"cleared: {event.condition} after {event.duration:.0f}s",
                event.at,
            )
