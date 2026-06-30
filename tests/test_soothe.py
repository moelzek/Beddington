from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from beddington import soothe
from beddington.config import (
    QuietCheckConfig,
    SootheConfig,
    SootheLearnConfig,
    SootheStepConfig,
)
from beddington.models import Event
from beddington.soothe import SootheController, SubprocessSoothePlayer


class FakeProcess:
    pid = 12345

    def __init__(self, command: list[str], **kwargs: object) -> None:
        self.command = command
        self.kwargs = kwargs
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return 0 if self.terminated or self.killed else None

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        return 0

    def kill(self) -> None:
        self.killed = True


class StubbornProcess(FakeProcess):
    def __init__(self, command: list[str], **kwargs: object) -> None:
        super().__init__(command, **kwargs)

    def poll(self) -> int | None:
        return 0 if self.killed else None

    def wait(self, timeout: float | None = None) -> int:
        raise subprocess.TimeoutExpired(self.command, timeout)


class FakeControllerPlayer:
    def __init__(self) -> None:
        self.played_steps: list[SootheStepConfig] = []
        self.pause_calls = 0
        self.resume_steps: list[SootheStepConfig] = []
        self.stop_calls = 0

    def play(self, step: SootheStepConfig) -> dict[str, object]:
        self.played_steps.append(step)
        return {"played": True, "play_seconds": step.play_seconds}

    def pause_for_listen(self) -> dict[str, object]:
        self.pause_calls += 1
        return {"paused": True}

    def resume(self, step: SootheStepConfig) -> dict[str, object]:
        self.resume_steps.append(step)
        return {"resumed": True, "play_seconds": step.play_seconds}

    def stop_all(self) -> None:
        self.stop_calls += 1


def test_soothe_settle_waits_for_min_play_seconds() -> None:
    started = datetime(2026, 6, 29, tzinfo=UTC)
    player = FakeControllerPlayer()
    controller = SootheController(
        SootheConfig(
            enabled=True,
            min_play_seconds=60.0,
            hold_after_stop_seconds=0.0,
            steps=(
                SootheStepConfig(
                    name="short noise",
                    wait_seconds=10.0,
                    play_seconds=5.0,
                ),
            ),
        ),
        started,
        player,
        quiet_threshold=0.4,
    )

    attempted = controller.observe(0.0, 0.9, (), escalation_due=True)
    cry_ended = Event(
        kind="cry_ended",
        occurred_at=started + timedelta(seconds=30.0),
        offset_seconds=30.0,
        score=0.1,
        duration_seconds=30.0,
    )
    early = controller.observe(30.0, 0.1, (cry_ended,), escalation_due=False)
    before_minimum = controller.observe(59.0, 0.1, (), escalation_due=False)
    released = controller.observe(60.0, 0.1, (), escalation_due=False)

    assert attempted.events[0].details["play_seconds"] == 60.0
    assert player.played_steps[0].play_seconds == 60.0
    assert early == soothe.SootheResult()
    assert before_minimum == soothe.SootheResult()
    assert player.stop_calls == 1
    assert [event.kind for event in released.events] == ["soothe_settled"]
    assert released.events[0].offset_seconds == 60.0
    assert released.events[0].details == {
        "reason": "crying_settled_before_notification"
    }


def test_soothe_holds_until_after_last_cry_stops() -> None:
    started = datetime(2026, 6, 29, tzinfo=UTC)
    player = FakeControllerPlayer()
    controller = SootheController(
        SootheConfig(
            enabled=True,
            min_play_seconds=0.0,
            hold_after_stop_seconds=45.0,
            steps=(
                SootheStepConfig(
                    name="white noise",
                    wait_seconds=180.0,
                    play_seconds=180.0,
                ),
            ),
        ),
        started,
        player,
        quiet_threshold=0.4,
    )

    controller.observe(0.0, 0.9, (), escalation_due=True)
    cry_ended = Event(
        kind="cry_ended",
        occurred_at=started + timedelta(seconds=30.0),
        offset_seconds=30.0,
        score=0.1,
        duration_seconds=30.0,
    )
    early = controller.observe(30.0, 0.1, (cry_ended,), escalation_due=False)
    before_hold = controller.observe(74.9, 0.1, (), escalation_due=False)
    released = controller.observe(75.0, 0.1, (), escalation_due=False)

    assert early == soothe.SootheResult()
    assert before_hold == soothe.SootheResult()
    assert player.stop_calls == 1
    assert [event.kind for event in released.events] == ["soothe_settled"]
    assert released.events[0].offset_seconds == 75.0


def test_soothe_hold_cancels_when_crying_returns() -> None:
    started = datetime(2026, 6, 29, tzinfo=UTC)
    player = FakeControllerPlayer()
    controller = SootheController(
        SootheConfig(
            enabled=True,
            min_play_seconds=0.0,
            hold_after_stop_seconds=45.0,
            steps=(
                SootheStepConfig(
                    name="white noise",
                    wait_seconds=180.0,
                    play_seconds=180.0,
                ),
            ),
        ),
        started,
        player,
        quiet_threshold=0.4,
    )

    controller.observe(0.0, 0.9, (), escalation_due=True)
    first_ended = Event(
        kind="cry_ended",
        occurred_at=started + timedelta(seconds=30.0),
        offset_seconds=30.0,
        score=0.1,
        duration_seconds=30.0,
    )
    crying_returned = Event(
        kind="cry_started",
        occurred_at=started + timedelta(seconds=50.0),
        offset_seconds=50.0,
        score=0.8,
    )
    second_ended = Event(
        kind="cry_ended",
        occurred_at=started + timedelta(seconds=90.0),
        offset_seconds=90.0,
        score=0.1,
        duration_seconds=40.0,
    )

    controller.observe(30.0, 0.1, (first_ended,), escalation_due=False)
    resumed = controller.observe(50.0, 0.8, (crying_returned,), escalation_due=False)
    old_deadline = controller.observe(75.0, 0.8, (), escalation_due=False)
    controller.observe(90.0, 0.1, (second_ended,), escalation_due=False)
    before_new_deadline = controller.observe(134.9, 0.1, (), escalation_due=False)
    released = controller.observe(135.0, 0.1, (), escalation_due=False)

    assert resumed == soothe.SootheResult()
    assert old_deadline == soothe.SootheResult()
    assert before_new_deadline == soothe.SootheResult()
    assert player.stop_calls == 1
    assert [event.kind for event in released.events] == ["soothe_settled"]
    assert released.events[0].offset_seconds == 135.0


def test_soothe_switches_to_best_other_preset_after_escalate() -> None:
    started = datetime(2026, 6, 29, tzinfo=UTC)
    player = FakeControllerPlayer()
    presets = {
        "rain": SootheStepConfig(
            name="rain",
            wait_seconds=600.0,
            play_seconds=600.0,
        ),
        "waves": SootheStepConfig(
            name="waves",
            wait_seconds=600.0,
            play_seconds=600.0,
        ),
        "bells": SootheStepConfig(
            name="bells",
            wait_seconds=600.0,
            play_seconds=600.0,
        ),
    }
    controller = SootheController(
        SootheConfig(
            enabled=True,
            preset="rain",
            min_play_seconds=0.0,
            escalate_after_seconds=5.0,
            presets=presets,
            steps=(presets["rain"],),
            learn=SootheLearnConfig(enabled=True, min_samples=2),
        ),
        started,
        player,
        quiet_threshold=0.4,
        soothe_outcomes=(
            (1.0, "rain", True),
            (2.0, "rain", True),
            (3.0, "waves", True),
            (4.0, "waves", True),
            (5.0, "bells", False),
            (6.0, "bells", False),
        ),
    )

    attempted = controller.observe(0.0, 0.9, (), escalation_due=True)
    early = controller.observe(4.9, 0.9, (), escalation_due=False)
    switched = controller.observe(5.0, 0.9, (), escalation_due=False)

    assert [event.kind for event in attempted.events] == ["soothe_attempted"]
    assert early == soothe.SootheResult()
    assert [step.name for step in player.played_steps] == ["rain", "waves"]
    assert player.stop_calls == 1
    assert [event.kind for event in switched.events] == ["soothe_switched"]
    assert switched.events[0].details == {"from": "rain", "to": "waves"}


def test_soothe_does_not_switch_if_crying_stops_before_escalate() -> None:
    started = datetime(2026, 6, 29, tzinfo=UTC)
    player = FakeControllerPlayer()
    presets = {
        "rain": SootheStepConfig(
            name="rain",
            wait_seconds=600.0,
            play_seconds=600.0,
        ),
        "waves": SootheStepConfig(
            name="waves",
            wait_seconds=600.0,
            play_seconds=600.0,
        ),
    }
    controller = SootheController(
        SootheConfig(
            enabled=True,
            preset="rain",
            min_play_seconds=0.0,
            hold_after_stop_seconds=20.0,
            escalate_after_seconds=5.0,
            presets=presets,
            steps=(presets["rain"],),
        ),
        started,
        player,
        quiet_threshold=0.4,
    )
    cry_ended = Event(
        kind="cry_ended",
        occurred_at=started + timedelta(seconds=2.0),
        offset_seconds=2.0,
        score=0.1,
        duration_seconds=2.0,
    )

    controller.observe(0.0, 0.9, (), escalation_due=True)
    stopped = controller.observe(2.0, 0.1, (cry_ended,), escalation_due=False)
    past_escalate = controller.observe(5.0, 0.1, (), escalation_due=False)

    assert stopped == soothe.SootheResult()
    assert past_escalate == soothe.SootheResult()
    assert [step.name for step in player.played_steps] == ["rain"]
    assert player.stop_calls == 0


def test_quiet_check_resolution_waits_for_min_play_seconds() -> None:
    started = datetime(2026, 6, 29, tzinfo=UTC)
    player = FakeControllerPlayer()
    controller = SootheController(
        SootheConfig(
            enabled=True,
            min_play_seconds=60.0,
            steps=(
                SootheStepConfig(
                    name="short noise",
                    wait_seconds=120.0,
                    play_seconds=5.0,
                ),
            ),
            quiet_check=QuietCheckConfig(
                enabled=True,
                check_interval_seconds=10.0,
                listen_seconds=5.0,
                required_checks=2,
            ),
        ),
        started,
        player,
        quiet_threshold=0.4,
    )

    controller.observe(0.0, 0.9, (), escalation_due=True)
    controller.observe(10.0, 0.1, (), escalation_due=False)
    first_quiet = controller.observe(15.0, 0.1, (), escalation_due=False)
    controller.observe(25.0, 0.1, (), escalation_due=False)
    second_quiet = controller.observe(30.0, 0.1, (), escalation_due=False)
    before_minimum = controller.observe(59.0, 0.1, (), escalation_due=False)
    released = controller.observe(60.0, 0.1, (), escalation_due=False)

    assert [event.kind for event in first_quiet.events] == ["soothe_quiet_check"]
    assert [event.kind for event in second_quiet.events] == ["soothe_quiet_check"]
    assert second_quiet.events[0].details["consecutive_quiet"] == 2
    assert before_minimum == soothe.SootheResult()
    assert player.stop_calls == 1
    assert len(player.resume_steps) == 2
    assert [event.kind for event in released.events] == ["soothe_quiet_confirmed"]
    assert released.events[0].offset_seconds == 60.0
    assert released.events[0].details == {
        "reason": "quiet_checks_passed",
        "quiet_checks": 2,
    }


def test_playback_command_loops_selected_supported_backend(
    monkeypatch,
    tmp_path: Path,
) -> None:
    sound = tmp_path / "white-noise.wav"
    sound.write_bytes(b"RIFF")
    play_seconds = 5.0

    monkeypatch.setattr(
        soothe.shutil,
        "which",
        lambda command: f"/usr/bin/{command}" if command == "aplay" else None,
    )

    command = soothe._playback_command(sound, play_seconds=play_seconds)

    assert command is not None
    assert command[:4] == [
        soothe.sys.executable,
        "-c",
        soothe._LOOP_PLAYBACK_SCRIPT,
        str(play_seconds),
    ]
    assert command[4:] == ["aplay", str(sound)]
    assert soothe._player_name(command) == "loop:aplay"


def test_playback_command_prefers_first_supported_backend(
    monkeypatch,
    tmp_path: Path,
) -> None:
    sound = tmp_path / "white-noise.wav"
    sound.write_bytes(b"RIFF")

    monkeypatch.setattr(
        soothe.shutil,
        "which",
        lambda command: f"/usr/bin/{command}" if command in {"afplay", "aplay"} else None,
    )

    command = soothe._playback_command(sound, play_seconds=0.0)

    assert command == ["afplay", str(sound)]


def test_playback_command_does_not_use_aplay_for_mp3(
    monkeypatch,
    tmp_path: Path,
) -> None:
    sound = tmp_path / "white-noise.mp3"
    sound.write_bytes(b"ID3")

    monkeypatch.setattr(
        soothe.shutil,
        "which",
        lambda command: f"/usr/bin/{command}" if command == "aplay" else None,
    )

    assert soothe._playback_command(sound, play_seconds=0.0) is None


def test_playback_command_prefers_pw_play_for_mp3(
    monkeypatch,
    tmp_path: Path,
) -> None:
    sound = tmp_path / "white-noise.mp3"
    sound.write_bytes(b"ID3")

    monkeypatch.delenv("BEDDINGTON_SOOTHE_VOLUME", raising=False)
    monkeypatch.setattr(
        soothe.shutil,
        "which",
        lambda command: f"/usr/bin/{command}"
        if command in {"pw-play", "ffplay"}
        else None,
    )

    assert soothe._playback_command(sound, play_seconds=0.0) == [
        "pw-play",
        "--volume",
        "0.45",
        str(sound),
    ]


def test_playback_command_uses_mpg123_for_mp3(
    monkeypatch,
    tmp_path: Path,
) -> None:
    sound = tmp_path / "white-noise.mp3"
    sound.write_bytes(b"ID3")

    monkeypatch.setattr(
        soothe.shutil,
        "which",
        lambda command: f"/usr/bin/{command}" if command == "mpg123" else None,
    )

    assert soothe._playback_command(sound, play_seconds=0.0) == [
        "mpg123",
        "-q",
        str(sound),
    ]


def test_playback_command_uses_bounded_env_volume_for_pw_play(
    monkeypatch,
    tmp_path: Path,
) -> None:
    sound = tmp_path / "white-noise.mp3"
    sound.write_bytes(b"ID3")

    monkeypatch.setenv("BEDDINGTON_SOOTHE_VOLUME", "1.4")
    monkeypatch.setattr(
        soothe.shutil,
        "which",
        lambda command: f"/usr/bin/{command}" if command == "pw-play" else None,
    )

    assert soothe._playback_command(sound, play_seconds=0.0) == [
        "pw-play",
        "--volume",
        "1",
        str(sound),
    ]


def test_playback_command_loops_afplay_backend(
    monkeypatch,
    tmp_path: Path,
) -> None:
    sound = tmp_path / "white-noise.wav"
    sound.write_bytes(b"RIFF")
    play_seconds = 5.0

    monkeypatch.setattr(
        soothe.shutil,
        "which",
        lambda command: f"/usr/bin/{command}" if command == "afplay" else None,
    )

    command = soothe._playback_command(sound, play_seconds=play_seconds)

    assert command is not None
    assert command[:4] == [
        soothe.sys.executable,
        "-c",
        soothe._LOOP_PLAYBACK_SCRIPT,
        str(play_seconds),
    ]
    assert command[4:] == ["afplay", str(sound)]
    assert soothe._player_name(command) == "loop:afplay"


def test_subprocess_soothe_player_starts_and_stops_backend(
    monkeypatch,
    tmp_path: Path,
) -> None:
    sound = tmp_path / "white-noise.wav"
    sound.write_bytes(b"RIFF")
    processes: list[FakeProcess] = []

    monkeypatch.setattr(
        soothe.shutil,
        "which",
        lambda command: f"/usr/bin/{command}" if command == "aplay" else None,
    )

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        process = FakeProcess(command, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(soothe.subprocess, "Popen", fake_popen)
    pid_file = tmp_path / "soothe-player.json"
    player = SubprocessSoothePlayer(pid_file=pid_file)

    playback = player.play(
        SootheStepConfig(
            name="white noise",
            sound_path=sound,
            wait_seconds=30.0,
            play_seconds=5.0,
        )
    )
    player.stop_all()

    assert playback["played"] is True
    assert playback["player"] == "loop:aplay"
    assert playback["sound_path"] == str(sound)
    assert processes[0].command[4:] == ["aplay", str(sound)]
    assert processes[0].kwargs["start_new_session"] is True
    assert processes[0].terminated is True
    assert not pid_file.exists()


def test_subprocess_soothe_player_stops_remembered_previous_instance(
    monkeypatch,
    tmp_path: Path,
) -> None:
    sound = tmp_path / "rain.wav"
    sound.write_bytes(b"RIFF")
    pid_file = tmp_path / "soothe-player.json"
    pid_file.write_text(
        json.dumps(
            {
                "version": 1,
                "processes": [{"pid": 54321, "sound_path": str(sound)}],
            }
        ),
        encoding="utf-8",
    )
    processes: list[FakeProcess] = []
    stopped: list[tuple[int, object]] = []

    monkeypatch.setattr(
        soothe.shutil,
        "which",
        lambda command: f"/usr/bin/{command}" if command == "aplay" else None,
    )
    monkeypatch.setattr(
        soothe,
        "_pid_still_matches_sound",
        lambda pid, sound_path: pid == 54321 and sound_path == str(sound),
    )
    monkeypatch.setattr(
        soothe,
        "_signal_pid_group",
        lambda pid, sig: stopped.append((pid, sig)) or True,
    )

    def fake_popen(command: list[str], **kwargs: object) -> FakeProcess:
        process = FakeProcess(command, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(soothe.subprocess, "Popen", fake_popen)
    player = SubprocessSoothePlayer(pid_file=pid_file)

    playback = player.play(SootheStepConfig(name="rain", sound_path=sound))

    assert playback["played"] is True
    assert stopped == [(54321, soothe.signal.SIGTERM)]
    remembered = json.loads(pid_file.read_text(encoding="utf-8"))
    assert remembered["processes"] == [
        {"pid": processes[0].pid, "sound_path": str(sound)}
    ]


def test_subprocess_soothe_player_kills_stubborn_process(
    monkeypatch,
    tmp_path: Path,
) -> None:
    sound = tmp_path / "white-noise.wav"
    sound.write_bytes(b"RIFF")
    processes: list[StubbornProcess] = []

    monkeypatch.setattr(
        soothe.shutil,
        "which",
        lambda command: f"/usr/bin/{command}" if command == "aplay" else None,
    )

    def fake_popen(command: list[str], **kwargs: object) -> StubbornProcess:
        process = StubbornProcess(command, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(soothe.subprocess, "Popen", fake_popen)
    player = SubprocessSoothePlayer(pid_file=tmp_path / "soothe-player.json")
    player.play(SootheStepConfig(name="white noise", sound_path=sound))

    player.stop_all()

    assert processes[0].terminated is True
    assert processes[0].killed is True


def test_subprocess_soothe_player_loop_stops_child_process(
    monkeypatch,
    tmp_path: Path,
) -> None:
    child_script = tmp_path / "child.py"
    child_pid = tmp_path / "child.pid"
    child_script.write_text(
        "\n".join(
            [
                "import pathlib",
                "import sys",
                "import time",
                "pathlib.Path(sys.argv[1]).write_text(str(__import__('os').getpid()))",
                "time.sleep(60)",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        soothe,
        "_single_playback_commands",
        lambda path: ([sys.executable, str(child_script), str(child_pid)],),
    )
    monkeypatch.setattr(soothe.shutil, "which", lambda command: command)
    player = SubprocessSoothePlayer(pid_file=tmp_path / "soothe-player.json")

    playback = player.play(
        SootheStepConfig(
            name="white noise",
            sound_path=child_script,
            wait_seconds=30.0,
            play_seconds=10.0,
        )
    )
    _wait_for_path(child_pid)
    pid = int(child_pid.read_text(encoding="utf-8"))

    player.stop_all()

    assert playback["played"] is True
    _wait_for_pid_exit(pid)


def test_subprocess_soothe_player_reports_missing_backend(
    monkeypatch,
    tmp_path: Path,
) -> None:
    sound = tmp_path / "white-noise.wav"
    sound.write_bytes(b"RIFF")
    monkeypatch.setattr(soothe.shutil, "which", lambda command: None)

    playback = SubprocessSoothePlayer(pid_file=tmp_path / "soothe-player.json").play(
        SootheStepConfig(name="white noise", sound_path=sound)
    )

    assert playback == {
        "played": False,
        "reason": "no_supported_player",
        "sound_path": str(sound),
    }


def _wait_for_path(path: Path) -> None:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.05)
    raise AssertionError(f"{path} was not created")


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _wait_for_pid_exit(pid: int) -> None:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not _pid_exists(pid):
            return
        time.sleep(0.05)
    raise AssertionError(f"process {pid} was still running")
