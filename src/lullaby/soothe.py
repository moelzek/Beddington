from __future__ import annotations

import shutil
import subprocess
import sys
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

    def pause_for_listen(self) -> dict[str, Any]: ...

    def resume(self, step: SootheStepConfig) -> dict[str, Any]: ...

    def stop_all(self) -> None: ...


class DryRunSoothePlayer:
    def play(self, step: SootheStepConfig) -> dict[str, Any]:
        return {
            "played": False,
            "player": "none",
            "reason": "dry_run",
            "play_seconds": _play_seconds(step),
            "sound_path": str(step.sound_path) if step.sound_path else "",
        }

    def stop_all(self) -> None:
        return None

    def pause_for_listen(self) -> dict[str, Any]:
        return {"paused": False, "player": "none", "reason": "dry_run"}

    def resume(self, step: SootheStepConfig) -> dict[str, Any]:
        return {
            "resumed": False,
            "player": "none",
            "reason": "dry_run",
            "play_seconds": _play_seconds(step),
            "sound_path": str(step.sound_path) if step.sound_path else "",
        }


class SubprocessSoothePlayer:
    def __init__(self) -> None:
        self._processes: list[subprocess.Popen[bytes]] = []

    def play(self, step: SootheStepConfig) -> dict[str, Any]:
        self.stop_all()
        if step.sound_path is None:
            return {"played": False, "reason": "no_sound_path"}
        if not step.sound_path.exists():
            return {
                "played": False,
                "reason": "sound_path_not_found",
                "sound_path": str(step.sound_path),
            }

        command = _playback_command(step.sound_path, _play_seconds(step))
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
        self._processes.append(process)
        return {
            "played": True,
            "player": _player_name(command),
            "pid": process.pid,
            "play_seconds": _play_seconds(step),
            "sound_path": str(step.sound_path),
        }

    def stop_all(self) -> None:
        alive = [process for process in self._processes if process.poll() is None]
        for process in alive:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
        for process in alive:
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
        self._processes = [
            process for process in self._processes if process.poll() is None
        ]

    def pause_for_listen(self) -> dict[str, Any]:
        self.stop_all()
        return {"paused": True, "player": "auto"}

    def resume(self, step: SootheStepConfig) -> dict[str, Any]:
        playback = self.play(step)
        return {"resumed": bool(playback.get("played")), "playback": playback}


class SootheController:
    def __init__(
        self,
        config: SootheConfig,
        started_at: datetime,
        player: SoothePlayer,
        quiet_threshold: float,
    ):
        self.config = config
        self.started_at = started_at
        self.player = player
        self.quiet_threshold = quiet_threshold
        self._active = False
        self._step_index = 0
        self._current_step: SootheStepConfig | None = None
        self._next_step_offset: float | None = None
        self._notify_due_offset: float | None = None
        self._next_quiet_check_offset: float | None = None
        self._quiet_check_started_offset: float | None = None
        self._quiet_check_failed = False
        self._quiet_checks_passed = 0

    def observe(
        self,
        offset_seconds: float,
        score: float,
        tracker_events: tuple[Event, ...],
        escalation_due: bool,
    ) -> SootheResult:
        events: list[Event] = []
        if any(event.kind == "cry_ended" for event in tracker_events):
            if not self._quiet_check_enabled:
                events.extend(self._settle_from(tracker_events))
                return SootheResult(tuple(events), notify=False)

        if escalation_due and not self._active:
            self._active = True
            self._step_index = 0
            events.extend(self._attempt_due_steps(offset_seconds, score))
            notify = self._notification_due(offset_seconds)
            return SootheResult(tuple(events), notify=notify)

        if self._active:
            quiet_result = self._observe_quiet_check(offset_seconds, score)
            events.extend(quiet_result.events)
            if quiet_result.resolved:
                return SootheResult(tuple(events), notify=False)
            events.extend(self._attempt_due_steps(offset_seconds, score))
            notify = self._notification_due(offset_seconds)
            return SootheResult(tuple(events), notify=notify)

        return SootheResult()

    def finish(self, offset_seconds: float, score: float) -> SootheResult:
        if not self._active:
            self.player.stop_all()
            return SootheResult()
        result = self.observe(offset_seconds, score, (), escalation_due=False)
        if result.notify:
            self._reset()
            self.player.stop_all()
            return result
        event = Event(
            kind="soothe_unresolved",
            occurred_at=self._at(offset_seconds),
            offset_seconds=offset_seconds,
            score=score,
            details={"reason": "recording_ended_before_escalation"},
        )
        self._reset()
        self.player.stop_all()
        return SootheResult(result.events + (event,), notify=False)

    def _attempt_due_steps(self, offset_seconds: float, score: float) -> tuple[Event, ...]:
        events: list[Event] = []
        while self._step_index < len(self.config.steps) and (
            self._next_step_offset is None or offset_seconds >= self._next_step_offset
        ):
            step = self.config.steps[self._step_index]
            self._current_step = step
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
                        "play_seconds": _play_seconds(step),
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
                self._schedule_next_quiet_check(offset_seconds)
                break
        return tuple(events)

    def _notification_due(self, offset_seconds: float) -> bool:
        if self._notify_due_offset is None or offset_seconds < self._notify_due_offset:
            return False
        self._reset()
        if self.config.quiet_check.stop_on_notify:
            self.player.stop_all()
        return True

    def _settle_from(self, tracker_events: tuple[Event, ...]) -> tuple[Event, ...]:
        if not self._active:
            return ()
        cry_ended = next(event for event in tracker_events if event.kind == "cry_ended")
        self.player.stop_all()
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

    @property
    def _quiet_check_enabled(self) -> bool:
        return self.config.quiet_check.enabled

    def _observe_quiet_check(
        self,
        offset_seconds: float,
        score: float,
    ) -> "_QuietCheckResult":
        if not self._quiet_check_enabled or self._current_step is None:
            return _QuietCheckResult()

        if self._quiet_check_started_offset is not None:
            return self._continue_quiet_check(offset_seconds, score)

        if (
            self._next_quiet_check_offset is None
            or offset_seconds < self._next_quiet_check_offset
        ):
            return _QuietCheckResult()

        return self._start_quiet_check(offset_seconds, score)

    def _start_quiet_check(
        self,
        offset_seconds: float,
        score: float,
    ) -> "_QuietCheckResult":
        self._quiet_check_started_offset = offset_seconds
        self._quiet_check_failed = False
        pause = (
            self.player.pause_for_listen()
            if self.config.quiet_check.pause_during_check
            else {"paused": False, "reason": "pause_disabled"}
        )
        event = Event(
            kind="soothe_quiet_check_started",
            occurred_at=self._at(offset_seconds),
            offset_seconds=offset_seconds,
            score=score,
            details={
                "listen_seconds": self.config.quiet_check.listen_seconds,
                "required_checks": self.config.quiet_check.required_checks,
                "consecutive_quiet": self._quiet_checks_passed,
                "paused": pause,
            },
        )
        return _QuietCheckResult(events=(event,))

    def _continue_quiet_check(
        self,
        offset_seconds: float,
        score: float,
    ) -> "_QuietCheckResult":
        assert self._quiet_check_started_offset is not None
        if score >= self.quiet_threshold:
            self._quiet_check_failed = True

        listen_finished = (
            offset_seconds
            >= self._quiet_check_started_offset
            + self.config.quiet_check.listen_seconds
        )
        if not listen_finished:
            return _QuietCheckResult()

        quiet = not self._quiet_check_failed
        if quiet:
            self._quiet_checks_passed += 1
        else:
            self._quiet_checks_passed = 0

        events: list[Event] = [
            Event(
                kind="soothe_quiet_check",
                occurred_at=self._at(offset_seconds),
                offset_seconds=offset_seconds,
                score=score,
                details={
                    "result": "quiet" if quiet else "crying_detected",
                    "consecutive_quiet": self._quiet_checks_passed,
                    "required_checks": self.config.quiet_check.required_checks,
                    "listen_seconds": self.config.quiet_check.listen_seconds,
                },
            )
        ]

        self._quiet_check_started_offset = None
        self._quiet_check_failed = False

        if self._quiet_checks_passed >= self.config.quiet_check.required_checks:
            events.append(
                Event(
                    kind="soothe_quiet_confirmed",
                    occurred_at=self._at(offset_seconds),
                    offset_seconds=offset_seconds,
                    score=score,
                    details={
                        "reason": "quiet_checks_passed",
                        "quiet_checks": self._quiet_checks_passed,
                    },
                )
            )
            self.player.stop_all()
            self._reset()
            return _QuietCheckResult(events=tuple(events), resolved=True)

        resume = (
            self.player.resume(self._current_step)
            if self.config.quiet_check.pause_during_check and self._current_step
            else {"resumed": False, "reason": "pause_disabled"}
        )
        events[-1].details["resume"] = resume
        self._schedule_next_quiet_check(offset_seconds)
        return _QuietCheckResult(events=tuple(events))

    def _schedule_next_quiet_check(self, offset_seconds: float) -> None:
        if not self._quiet_check_enabled:
            self._next_quiet_check_offset = None
            return
        self._next_quiet_check_offset = (
            offset_seconds + self.config.quiet_check.check_interval_seconds
        )

    def _at(self, offset_seconds: float) -> datetime:
        return self.started_at + timedelta(seconds=offset_seconds)

    def _reset(self) -> None:
        self._active = False
        self._step_index = 0
        self._current_step = None
        self._next_step_offset = None
        self._notify_due_offset = None
        self._next_quiet_check_offset = None
        self._quiet_check_started_offset = None
        self._quiet_check_failed = False
        self._quiet_checks_passed = 0


@dataclass(frozen=True)
class _QuietCheckResult:
    events: tuple[Event, ...] = ()
    resolved: bool = False


def build_soothe_player(config: SootheConfig) -> SoothePlayer:
    if config.player == "auto":
        return SubprocessSoothePlayer()
    return DryRunSoothePlayer()


def _play_seconds(step: SootheStepConfig) -> float:
    if step.play_seconds is not None:
        return step.play_seconds
    return step.wait_seconds


def _playback_command(path: Path, play_seconds: float) -> list[str] | None:
    for command in _single_playback_commands(path):
        if shutil.which(command[0]):
            if play_seconds <= 0:
                return command
            return [
                sys.executable,
                "-c",
                _LOOP_PLAYBACK_SCRIPT,
                str(play_seconds),
                *command,
            ]
    return None


def _single_playback_commands(path: Path) -> tuple[list[str], ...]:
    return (
        ["afplay", str(path)],
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)],
        ["paplay", str(path)],
        ["aplay", str(path)],
    )


def _player_name(command: list[str]) -> str:
    if command[:2] == [sys.executable, "-c"] and len(command) >= 5:
        return f"loop:{command[4]}"
    return command[0]


_LOOP_PLAYBACK_SCRIPT = """
import signal
import subprocess
import sys
import time

duration = float(sys.argv[1])
command = sys.argv[2:]
deadline = time.monotonic() + duration
running = True
child = None

def stop(signum, frame):
    global running
    running = False
    if child is not None and child.poll() is None:
        child.terminate()

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)

while running and time.monotonic() < deadline:
    child = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    while running and child.poll() is None and time.monotonic() < deadline:
        time.sleep(0.2)
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            child.kill()
"""
