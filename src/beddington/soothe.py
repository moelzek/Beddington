from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Protocol

from .config import SootheConfig, SootheStepConfig
from .models import Event
from .soothe_memory import Outcome, best_preset


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
    def __init__(self, pid_file: Path | None = None) -> None:
        self._processes: list[subprocess.Popen[bytes]] = []
        self._pid_file = pid_file or _default_soothe_pid_file()

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
            start_new_session=True,
        )
        self._processes.append(process)
        self._write_pid_file()
        return {
            "played": True,
            "player": _player_name(command),
            "pid": process.pid,
            "play_seconds": _play_seconds(step),
            "sound_path": str(step.sound_path),
        }

    def stop_all(self) -> None:
        alive = [process for process in self._processes if process.poll() is None]
        alive_pids = {process.pid for process in alive}
        for remembered in _read_soothe_pid_file(self._pid_file):
            if remembered.pid in alive_pids:
                continue
            if _pid_still_matches_sound(remembered.pid, remembered.sound_path):
                _signal_pid_group(remembered.pid, signal.SIGTERM)
        for process in alive:
            _signal_process(process, signal.SIGTERM)
        for process in alive:
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                _signal_process(process, signal.SIGKILL)
        self._processes = [
            process for process in self._processes if process.poll() is None
        ]
        self._write_pid_file()

    def pause_for_listen(self) -> dict[str, Any]:
        self.stop_all()
        return {"paused": True, "player": "auto"}

    def resume(self, step: SootheStepConfig) -> dict[str, Any]:
        playback = self.play(step)
        return {"resumed": bool(playback.get("played")), "playback": playback}

    def _write_pid_file(self) -> None:
        alive = [process for process in self._processes if process.poll() is None]
        _write_soothe_pid_file(
            self._pid_file,
            (
                _RememberedProcess(
                    pid=process.pid,
                    sound_path=_sound_path_from_command(
                        getattr(process, "args", getattr(process, "command", ()))
                    ),
                )
                for process in alive
            ),
        )


@dataclass(frozen=True)
class _RememberedProcess:
    pid: int
    sound_path: str


def _default_soothe_pid_file() -> Path:
    configured = os.getenv("BEDDINGTON_SOOTHE_PID_FILE")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".config" / "beddington" / "soothe-player.json"


def _read_soothe_pid_file(path: Path) -> tuple[_RememberedProcess, ...]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return ()

    if isinstance(raw, dict):
        entries = raw.get("processes", ())
    else:
        entries = raw
    if not isinstance(entries, list):
        return ()

    remembered: list[_RememberedProcess] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        pid = entry.get("pid")
        sound_path = entry.get("sound_path")
        if isinstance(pid, int) and pid > 0 and isinstance(sound_path, str):
            remembered.append(_RememberedProcess(pid=pid, sound_path=sound_path))
    return tuple(remembered)


def _write_soothe_pid_file(
    path: Path,
    processes: Iterable[_RememberedProcess],
) -> None:
    entries = [
        {"pid": process.pid, "sound_path": process.sound_path}
        for process in processes
        if process.pid > 0
    ]
    if not entries:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
        return

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"version": 1, "processes": entries}),
            encoding="utf-8",
        )
    except OSError:
        pass


def _sound_path_from_command(command: object) -> str:
    if not isinstance(command, (list, tuple)):
        return ""
    for argument in reversed(command):
        if isinstance(argument, str) and ("/" in argument or "\\" in argument):
            return argument
    return ""


def _pid_still_matches_sound(pid: int, sound_path: str) -> bool:
    if not sound_path or pid == os.getpid():
        return False
    command = _process_command(pid)
    if command is None:
        return False
    return sound_path in command


def _process_command(pid: int) -> str | None:
    try:
        completed = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            check=False,
            text=True,
            timeout=0.5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    command = completed.stdout.strip()
    return command or None


def _signal_process(process: subprocess.Popen[bytes], sig: signal.Signals) -> None:
    if _signal_pid_group(process.pid, sig):
        return
    try:
        if sig == signal.SIGKILL:
            process.kill()
        else:
            process.terminate()
    except ProcessLookupError:
        pass


def _signal_pid_group(pid: int, sig: signal.Signals) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        os.killpg(os.getpgid(pid), sig)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        pass
    try:
        os.kill(pid, sig)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


class SootheController:
    def __init__(
        self,
        config: SootheConfig,
        started_at: datetime,
        player: SoothePlayer,
        quiet_threshold: float,
        soothe_outcomes: Iterable[Outcome] = (),
    ):
        self.config = config
        self.started_at = started_at
        self.player = player
        self.quiet_threshold = quiet_threshold
        self._soothe_outcomes = tuple(soothe_outcomes)
        self._active = False
        self._active_started_offset: float | None = None
        self._step_index = 0
        self._current_step: SootheStepConfig | None = None
        self._current_preset_key: str | None = None
        self._current_sound_started_offset: float | None = None
        self._next_step_offset: float | None = None
        self._notify_due_offset: float | None = None
        self._next_quiet_check_offset: float | None = None
        self._quiet_check_started_offset: float | None = None
        self._quiet_check_failed = False
        self._quiet_checks_passed = 0
        self._pending_resolution: _PendingResolution | None = None
        self._crying = False
        self._current_cry_started_offset: float | None = None
        self._last_cry_ended_offset: float | None = None

    def observe(
        self,
        offset_seconds: float,
        score: float,
        tracker_events: tuple[Event, ...],
        escalation_due: bool,
    ) -> SootheResult:
        events: list[Event] = []
        self._track_cry_events(tracker_events)
        events.extend(self._release_pending_resolution(offset_seconds, score))
        if events:
            return SootheResult(tuple(events), notify=False)

        if (
            not self._crying
            and any(event.kind == "cry_ended" for event in tracker_events)
        ):
            if not self._quiet_check_enabled:
                events.extend(self._settle_from(tracker_events, offset_seconds))
                return SootheResult(tuple(events), notify=False)

        if escalation_due and not self._active:
            self._active = True
            self._crying = True
            self._active_started_offset = offset_seconds
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
            if notify:
                return SootheResult(tuple(events), notify=notify)
            events.extend(self._switch_if_due(offset_seconds, score))
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
        if not self._active:
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
            configured_step = self.config.steps[self._step_index]
            step = _with_min_play_seconds(
                configured_step,
                self.config.min_play_seconds,
            )
            self._current_step = step
            self._current_preset_key = self._preset_key_for_step(self._step_index)
            self._current_sound_started_offset = offset_seconds
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
            due_offset = offset_seconds + configured_step.wait_seconds
            if self._step_index < len(self.config.steps):
                self._next_step_offset = due_offset
            else:
                self._next_step_offset = None
                self._notify_due_offset = due_offset
                self._schedule_next_quiet_check(offset_seconds)
                break
        return tuple(events)

    def _notification_due(self, offset_seconds: float) -> bool:
        if self._pending_resolution is not None:
            return False
        if self._notify_due_offset is None or offset_seconds < self._notify_due_offset:
            return False
        self._reset()
        if self.config.quiet_check.stop_on_notify:
            self.player.stop_all()
        return True

    def _settle_from(
        self,
        tracker_events: tuple[Event, ...],
        offset_seconds: float,
    ) -> tuple[Event, ...]:
        if not self._active:
            return ()
        cry_ended = next(event for event in tracker_events if event.kind == "cry_ended")
        last_cry_ended_offset = self._last_cry_ended_offset or cry_ended.offset_seconds
        release_offset = max(
            self._minimum_release_offset(),
            last_cry_ended_offset + self.config.hold_after_stop_seconds,
        )
        if offset_seconds < release_offset:
            self._pending_resolution = _PendingResolution(
                kind="settled",
                duration_seconds=cry_ended.duration_seconds,
                release_offset=release_offset,
            )
            return ()
        self.player.stop_all()
        self._reset()
        return (
            self._settled_event(
                cry_ended.offset_seconds,
                cry_ended.score,
                cry_ended.duration_seconds,
            ),
        )

    def _track_cry_events(self, tracker_events: tuple[Event, ...]) -> None:
        for event in tracker_events:
            if event.kind == "cry_started":
                self._crying = True
                self._current_cry_started_offset = event.offset_seconds
                if (
                    self._active
                    and self._pending_resolution is not None
                    and self._pending_resolution.kind == "settled"
                ):
                    self._pending_resolution = None
            elif event.kind == "cry_ended":
                self._crying = False
                self._current_cry_started_offset = None
                if self._active:
                    self._last_cry_ended_offset = event.offset_seconds

    def _preset_key_for_step(self, step_index: int) -> str | None:
        if (
            step_index == 0
            and self.config.presets
            and self.config.preset in self.config.presets
        ):
            return self.config.preset
        return None

    def _switch_if_due(self, offset_seconds: float, score: float) -> tuple[Event, ...]:
        if (
            not self._crying
            or self._current_preset_key is None
            or self._current_sound_started_offset is None
            or self.config.escalate_after_seconds < 0
        ):
            return ()

        crying_since = (
            self._current_cry_started_offset
            if self._current_cry_started_offset is not None
            else self._current_sound_started_offset
        )
        due_offset = (
            max(self._current_sound_started_offset, crying_since)
            + self.config.escalate_after_seconds
        )
        if offset_seconds < due_offset:
            return ()

        next_key = self._next_preset_key(self._current_preset_key)
        if next_key is None:
            return ()

        previous_key = self._current_preset_key
        step = _with_min_play_seconds(
            self.config.presets[next_key],
            self.config.min_play_seconds,
        )
        self.player.stop_all()
        self.player.play(step)
        self._current_step = step
        self._current_preset_key = next_key
        self._current_sound_started_offset = offset_seconds
        return (
            Event(
                kind="soothe_switched",
                occurred_at=self._at(offset_seconds),
                offset_seconds=offset_seconds,
                score=score,
                details={"from": previous_key, "to": next_key},
            ),
        )

    def _next_preset_key(self, current_key: str) -> str | None:
        available = {
            key: step for key, step in self.config.presets.items() if key != current_key
        }
        if not available:
            return None
        fallback = min(available)
        outcomes = self._soothe_outcomes if self.config.learn.enabled else ()
        return best_preset(
            outcomes,
            available,
            self.config.learn.min_samples,
            fallback,
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
            if not self._minimum_elapsed(offset_seconds):
                self._pending_resolution = _PendingResolution(
                    kind="quiet",
                    quiet_checks=self._quiet_checks_passed,
                )
                self._next_quiet_check_offset = None
                resume = (
                    self.player.resume(self._current_step)
                    if self.config.quiet_check.pause_during_check and self._current_step
                    else {"resumed": False, "reason": "pause_disabled"}
                )
                events[-1].details["resume"] = resume
                return _QuietCheckResult(events=tuple(events))
            events.append(
                self._quiet_confirmed_event(
                    offset_seconds,
                    score,
                    self._quiet_checks_passed,
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

    def _minimum_elapsed(self, offset_seconds: float) -> bool:
        return offset_seconds >= self._minimum_release_offset()

    def _minimum_release_offset(self) -> float:
        if self._active_started_offset is None:
            return 0.0
        return self._active_started_offset + self.config.min_play_seconds

    def _release_pending_resolution(
        self,
        offset_seconds: float,
        score: float,
    ) -> tuple[Event, ...]:
        pending = self._pending_resolution
        if pending is None:
            return ()
        if pending.kind == "settled" and self._crying:
            self._pending_resolution = None
            return ()

        release_offset = pending.release_offset
        if release_offset is None:
            if not self._minimum_elapsed(offset_seconds):
                return ()
        elif offset_seconds < release_offset:
            return ()

        if pending.kind == "settled":
            event = self._settled_event(
                offset_seconds,
                score,
                pending.duration_seconds,
            )
        else:
            event = self._quiet_confirmed_event(
                offset_seconds,
                score,
                pending.quiet_checks or self._quiet_checks_passed,
            )
        self.player.stop_all()
        self._reset()
        return (event,)

    def _settled_event(
        self,
        offset_seconds: float,
        score: float | None,
        duration_seconds: float | None,
    ) -> Event:
        return Event(
            kind="soothe_settled",
            occurred_at=self._at(offset_seconds),
            offset_seconds=offset_seconds,
            score=score,
            duration_seconds=duration_seconds,
            details={"reason": "crying_settled_before_notification"},
        )

    def _quiet_confirmed_event(
        self,
        offset_seconds: float,
        score: float,
        quiet_checks: int,
    ) -> Event:
        return Event(
            kind="soothe_quiet_confirmed",
            occurred_at=self._at(offset_seconds),
            offset_seconds=offset_seconds,
            score=score,
            details={
                "reason": "quiet_checks_passed",
                "quiet_checks": quiet_checks,
            },
        )

    def _at(self, offset_seconds: float) -> datetime:
        return self.started_at + timedelta(seconds=offset_seconds)

    def _reset(self) -> None:
        self._active = False
        self._active_started_offset = None
        self._step_index = 0
        self._current_step = None
        self._current_preset_key = None
        self._current_sound_started_offset = None
        self._next_step_offset = None
        self._notify_due_offset = None
        self._next_quiet_check_offset = None
        self._quiet_check_started_offset = None
        self._quiet_check_failed = False
        self._quiet_checks_passed = 0
        self._pending_resolution = None
        self._crying = False
        self._current_cry_started_offset = None
        self._last_cry_ended_offset = None


@dataclass(frozen=True)
class _QuietCheckResult:
    events: tuple[Event, ...] = ()
    resolved: bool = False


@dataclass(frozen=True)
class _PendingResolution:
    kind: str
    duration_seconds: float | None = None
    quiet_checks: int | None = None
    release_offset: float | None = None


def build_soothe_player(config: SootheConfig) -> SoothePlayer:
    if config.player == "auto":
        return SubprocessSoothePlayer()
    return DryRunSoothePlayer()


def _play_seconds(step: SootheStepConfig) -> float:
    if step.play_seconds is not None:
        return step.play_seconds
    return step.wait_seconds


def _with_min_play_seconds(
    step: SootheStepConfig,
    min_play_seconds: float,
) -> SootheStepConfig:
    if _play_seconds(step) >= min_play_seconds:
        return step
    return replace(step, play_seconds=min_play_seconds)


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
    volume = _playback_volume()
    commands = (["afplay", str(path)],)
    if path.suffix.lower() == ".mp3":
        return (
            *commands,
            ["pw-play", "--volume", volume, str(path)],
            ["mpg123", "-q", str(path)],
            [
                "ffplay",
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "quiet",
                "-volume",
                str(round(float(volume) * 100)),
                str(path),
            ],
        )
    return (
        *commands,
        ["pw-play", "--volume", volume, str(path)],
        ["paplay", str(path)],
        ["aplay", str(path)],
    )


def _playback_volume() -> str:
    raw = os.getenv("BEDDINGTON_SOOTHE_VOLUME", "0.45")
    try:
        value = float(raw)
    except ValueError:
        value = 0.45
    value = min(1.0, max(0.0, value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


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
