from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from .config import SootheConfig, SootheStepConfig
from .models import Event


@dataclass(frozen=True)
class SootheResult:
    events: tuple[Event, ...] = ()
    notify: bool = False


class SoothePlayer(Protocol):
    def play(self, step: SootheStepConfig) -> dict[str, Any]: ...


class DryRunSoothePlayer:
    def play(self, step: SootheStepConfig) -> dict[str, Any]:
        return {
            "played": False,
            "player": "none",
            "reason": "dry_run",
            "sound_path": str(step.sound_path) if step.sound_path else "",
        }


class SubprocessSoothePlayer:
    def play(self, step: SootheStepConfig) -> dict[str, Any]:
        if step.sound_path is None:
            return {"played": False, "reason": "no_sound_path"}
        if not step.sound_path.exists():
            return {
                "played": False,
                "reason": "sound_path_not_found",
                "sound_path": str(step.sound_path),
            }

        command = _playback_command(step.sound_path)
        if command is None:
            return {
                "played": False,
                "reason": "no_supported_player",
                "sound_path": str(step.sound_path),
            }

        process = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {
            "played": True,
            "player": command[0],
            "pid": process.pid,
            "sound_path": str(step.sound_path),
        }


class SootheController:
    def __init__(
        self,
        config: SootheConfig,
        started_at: datetime,
        player: SoothePlayer,
    ):
        self.config = config
        self.started_at = started_at
        self.player = player
        self._active = False
        self._step_index = 0
        self._next_step_offset: float | None = None
        self._notify_due_offset: float | None = None

    def observe(
        self,
        offset_seconds: float,
        score: float,
        tracker_events: tuple[Event, ...],
        escalation_due: bool,
    ) -> SootheResult:
        events: list[Event] = []
        if any(event.kind == "cry_ended" for event in tracker_events):
            events.extend(self._settle_from(tracker_events))
            return SootheResult(tuple(events), notify=False)

        if escalation_due and not self._active:
            self._active = True
            self._step_index = 0
            events.extend(self._attempt_due_steps(offset_seconds, score))
            notify = self._notification_due(offset_seconds)
            return SootheResult(tuple(events), notify=notify)

        if self._active:
            events.extend(self._attempt_due_steps(offset_seconds, score))
            notify = self._notification_due(offset_seconds)
            return SootheResult(tuple(events), notify=notify)

        return SootheResult()

    def finish(self, offset_seconds: float, score: float) -> SootheResult:
        if not self._active:
            return SootheResult()
        result = self.observe(offset_seconds, score, (), escalation_due=False)
        if result.notify:
            self._reset()
            return result
        event = Event(
            kind="soothe_unresolved",
            occurred_at=self._at(offset_seconds),
            offset_seconds=offset_seconds,
            score=score,
            details={"reason": "recording_ended_before_escalation"},
        )
        self._reset()
        return SootheResult(result.events + (event,), notify=False)

    def _attempt_due_steps(self, offset_seconds: float, score: float) -> tuple[Event, ...]:
        events: list[Event] = []
        while self._step_index < len(self.config.steps) and (
            self._next_step_offset is None or offset_seconds >= self._next_step_offset
        ):
            step = self.config.steps[self._step_index]
            playback = self.player.play(step)
            events.append(
                Event(
                    kind="soothe_attempted",
                    occurred_at=self._at(offset_seconds),
                    offset_seconds=offset_seconds,
                    score=score,
                    details={
                        "step": self._step_index + 1,
                        "name": step.name,
                        "wait_seconds": step.wait_seconds,
                        "sound_path": str(step.sound_path) if step.sound_path else "",
                        "playback": playback,
                    },
                )
            )
            self._step_index += 1
            due_offset = offset_seconds + step.wait_seconds
            if self._step_index < len(self.config.steps):
                self._next_step_offset = due_offset
            else:
                self._next_step_offset = None
                self._notify_due_offset = due_offset
                break
        return tuple(events)

    def _notification_due(self, offset_seconds: float) -> bool:
        if self._notify_due_offset is None or offset_seconds < self._notify_due_offset:
            return False
        self._reset()
        return True

    def _settle_from(self, tracker_events: tuple[Event, ...]) -> tuple[Event, ...]:
        if not self._active:
            return ()
        cry_ended = next(event for event in tracker_events if event.kind == "cry_ended")
        self._reset()
        return (
            Event(
                kind="soothe_settled",
                occurred_at=cry_ended.occurred_at,
                offset_seconds=cry_ended.offset_seconds,
                score=cry_ended.score,
                duration_seconds=cry_ended.duration_seconds,
                details={"reason": "crying_settled_before_notification"},
            ),
        )

    def _at(self, offset_seconds: float) -> datetime:
        return self.started_at + timedelta(seconds=offset_seconds)

    def _reset(self) -> None:
        self._active = False
        self._step_index = 0
        self._next_step_offset = None
        self._notify_due_offset = None


def build_soothe_player(config: SootheConfig) -> SoothePlayer:
    if config.player == "auto":
        return SubprocessSoothePlayer()
    return DryRunSoothePlayer()


def _playback_command(path: Path) -> list[str] | None:
    for command in (
        ["afplay", str(path)],
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)],
        ["paplay", str(path)],
        ["aplay", str(path)],
    ):
        if shutil.which(command[0]):
            return command
    return None
