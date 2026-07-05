from __future__ import annotations

import queue
import subprocess
import threading
import time
import wave
from pathlib import Path

import pytest

from beddington.config import LiveviewAudioConfig, load_config
from beddington.liveaudio import (
    AudioBroker,
    AudioClientTooSlow,
    TalkPlaybackError,
    TalkPlayer,
)


def test_liveview_audio_config_defaults_and_loading(tmp_path: Path) -> None:
    default = load_config()
    assert default.liveview.audio == LiveviewAudioConfig()

    path = tmp_path / "config.toml"
    path.write_text(
        """
[liveview.audio]
enabled = true
device = "USB PnP"
max_listeners = 2
talk_max_seconds = 12.5
""",
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.liveview.audio.enabled is True
    assert config.liveview.audio.device == "USB PnP"
    assert config.liveview.audio.max_listeners == 2
    assert config.liveview.audio.talk_max_seconds == 12.5


def test_liveview_audio_config_validates_limits(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[liveview.audio]\nmax_listeners = 0\n", encoding="utf-8")

    with pytest.raises(ValueError, match="liveview.audio.max_listeners"):
        load_config(path)

    path.write_text("[liveview.audio]\ntalk_max_seconds = 0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="liveview.audio.talk_max_seconds"):
        load_config(path)


def test_audio_broker_fanout_slow_client_and_lazy_stop() -> None:
    blocks: queue.Queue[bytes] = queue.Queue()
    started = threading.Event()
    restarted = threading.Event()
    idle_boundary = threading.Event()
    allow_idle_exit = threading.Event()
    starts = 0
    starts_lock = threading.Lock()

    def source(stop: threading.Event):
        nonlocal starts
        with starts_lock:
            starts += 1
            start_number = starts
        if start_number == 1:
            started.set()
        else:
            restarted.set()
        try:
            while not stop.is_set():
                try:
                    yield blocks.get(timeout=0.02)
                except queue.Empty:
                    continue
        finally:
            if start_number == 1:
                idle_boundary.set()
                allow_idle_exit.wait(1.0)

    broker = AudioBroker(
        max_blocks=2,
        idle_timeout_s=0.05,
        source=source,
    )
    assert not started.is_set()

    broker.add_listener()
    broker.add_listener()
    assert started.wait(0.5)

    blocks.put(b"a")
    seq1, block1 = broker.wait_for_block(0, timeout=0.5)
    seq2, block2 = broker.wait_for_block(0, timeout=0.5)
    assert (seq1, block1) == (1, b"a")
    assert (seq2, block2) == (1, b"a")

    blocks.put(b"b")
    blocks.put(b"c")
    blocks.put(b"d")
    deadline = time.monotonic() + 1.0
    while broker.latest_seq() < 4 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert broker.latest_seq() == 4

    with pytest.raises(AudioClientTooSlow):
        broker.wait_for_block(1, timeout=0.05)

    broker.remove_listener()
    broker.remove_listener()
    time.sleep(0.08)
    blocks.put(b"e")
    assert idle_boundary.wait(0.5)
    baseline = broker.latest_seq()

    broker.add_listener()
    allow_idle_exit.set()
    assert restarted.wait(0.5)
    blocks.put(b"f")
    seq, block = broker.wait_for_block(baseline, timeout=0.5)
    assert seq > baseline
    assert block == b"f"

    broker.remove_listener()
    broker.close()


def _write_wav(path: Path, seconds: float = 0.25) -> None:
    rate = 48_000
    frames = int(rate * seconds)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(b"\x00\x00" * frames)


def test_talk_player_decodes_plays_and_deletes_temp_files() -> None:
    seen_paths: list[Path] = []
    played: list[list[str]] = []
    timeouts: list[float] = []

    def fake_run(command, **kwargs):
        timeouts.append(kwargs["timeout"])
        if command[0] == "ffmpeg":
            in_path = Path(command[command.index("-i") + 1])
            out_path = Path(command[-1])
            assert command[command.index("-t") + 1] == "20.5"
            seen_paths.extend([in_path, out_path])
            _write_wav(out_path, seconds=0.25)
            return subprocess.CompletedProcess(command, 0)
        played.append(command)
        return subprocess.CompletedProcess(command, 0)

    player = TalkPlayer(
        run=fake_run,
        which=lambda name: f"/usr/bin/{name}",
        playback_commands=lambda path: [["pw-play", str(path)]],
    )

    result = player.play(b"webm", "audio/webm;codecs=opus")

    assert result.seconds == pytest.approx(0.25)
    assert played and played[0][0] == "pw-play"
    assert timeouts == [20.0, 35.0]
    assert player.playing() is False
    assert seen_paths and all(not path.exists() for path in seen_paths)


def test_talk_player_ffmpeg_failure_cleans_temp_files() -> None:
    seen_paths: list[Path] = []

    def fake_run(command, **_kwargs):
        in_path = Path(command[command.index("-i") + 1])
        out_path = Path(command[-1])
        seen_paths.extend([in_path, out_path])
        return subprocess.CompletedProcess(command, 1)

    player = TalkPlayer(
        run=fake_run,
        which=lambda _name: "/usr/bin/pw-play",
        playback_commands=lambda path: [["pw-play", str(path)]],
    )

    with pytest.raises(TalkPlaybackError):
        player.play(b"bad", "audio/webm")

    assert seen_paths
    assert all(not path.exists() for path in seen_paths)
    assert all(not path.parent.exists() for path in seen_paths)
    assert player.playing() is False


@pytest.mark.parametrize("timeout_on", ["decode", "playback"])
def test_talk_player_subprocess_timeout_cleans_temp_files(
    timeout_on: str,
) -> None:
    seen_paths: list[Path] = []

    def fake_run(command, **kwargs):
        if command[0] == "ffmpeg":
            in_path = Path(command[command.index("-i") + 1])
            out_path = Path(command[-1])
            seen_paths.extend([in_path, out_path])
            if timeout_on == "decode":
                raise subprocess.TimeoutExpired(command, kwargs["timeout"])
            _write_wav(out_path, seconds=0.25)
            return subprocess.CompletedProcess(command, 0)
        if timeout_on == "playback":
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return subprocess.CompletedProcess(command, 0)

    player = TalkPlayer(
        run=fake_run,
        which=lambda _name: "/usr/bin/pw-play",
        playback_commands=lambda path: [["pw-play", str(path)]],
    )

    with pytest.raises(TalkPlaybackError):
        player.play(b"webm", "audio/webm")

    assert seen_paths
    assert all(not path.exists() for path in seen_paths)
    assert all(not path.parent.exists() for path in seen_paths)
    assert player.playing() is False
