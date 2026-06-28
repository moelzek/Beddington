from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from beddington import soothe
from beddington.config import SootheStepConfig
from beddington.soothe import SubprocessSoothePlayer


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
    player = SubprocessSoothePlayer()

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
    assert processes[0].terminated is True


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
    player = SubprocessSoothePlayer()
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
    player = SubprocessSoothePlayer()

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

    playback = SubprocessSoothePlayer().play(
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
