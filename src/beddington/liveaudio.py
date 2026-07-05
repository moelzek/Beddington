from __future__ import annotations

import inspect
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import wave
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from .audio import SAMPLE_RATE
from .soothe import _playback_volume, _single_playback_commands

TALK_MAX_BYTES = 2_500_000
_DEFAULT_AUDIO_BLOCK_SECONDS = 0.1


class AudioUnavailable(RuntimeError):
    """Raised when live microphone capture cannot start or has failed."""


class AudioClientTooSlow(RuntimeError):
    """Raised when a listener's cursor has fallen behind the audio ring."""


class TalkBusy(RuntimeError):
    """Raised when a talk clip is already decoding or playing."""


class TalkRejected(ValueError):
    """Raised when an uploaded talk clip violates configured limits."""


class TalkPlaybackError(RuntimeError):
    """Raised when a talk clip cannot be decoded or played."""


@dataclass(frozen=True)
class TalkResult:
    seconds: float


AudioBlockSource = Callable[[threading.Event], Iterable[bytes]]


class AudioBroker:
    """Lazy fan-out for live 16 kHz mono signed-16 PCM microphone blocks."""

    def __init__(
        self,
        *,
        device: str | int | None = None,
        max_listeners: int = 3,
        max_blocks: int = 128,
        idle_timeout_s: float = 10.0,
        source: AudioBlockSource | Callable[[], Iterable[bytes]] | None = None,
    ) -> None:
        if max_listeners < 1:
            raise ValueError("max_listeners must be at least 1")
        if max_blocks < 2:
            raise ValueError("max_blocks must be at least 2")
        self.device = device
        self.max_listeners = max_listeners
        self._source = source or (
            lambda stop: _sounddevice_pcm_blocks(
                stop,
                device=device,
                block_seconds=_DEFAULT_AUDIO_BLOCK_SECONDS,
            )
        )
        self._blocks: deque[tuple[int, bytes]] = deque(maxlen=max_blocks)
        self._seq = 0
        self._listeners = 0
        self._last_listener_left_at: float | None = None
        self._closed = False
        self._error: BaseException | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._cond = threading.Condition()
        self._idle_timeout_s = idle_timeout_s

    def add_listener(self) -> None:
        with self._cond:
            if self._closed:
                raise AudioUnavailable("audio broker is closed")
            self._listeners += 1
            self._last_listener_left_at = None
            self._ensure_started_locked()

    def remove_listener(self) -> None:
        with self._cond:
            self._listeners = max(0, self._listeners - 1)
            if self._listeners == 0:
                self._last_listener_left_at = time.monotonic()
            self._cond.notify_all()

    @property
    def listener_count(self) -> int:
        with self._cond:
            return self._listeners

    @property
    def running(self) -> bool:
        with self._cond:
            return self._thread is not None and self._thread.is_alive()

    @property
    def last_error(self) -> BaseException | None:
        with self._cond:
            return self._error

    def latest_seq(self) -> int:
        with self._cond:
            return self._seq

    def wait_for_block(
        self,
        last_seq: int,
        timeout: float = 2.0,
    ) -> tuple[int, bytes | None]:
        """Wait for the next block after ``last_seq``.

        A new listener should pass ``0`` and receives the newest buffered block
        if one exists. A listener that falls behind the bounded ring raises
        :class:`AudioClientTooSlow` so the HTTP handler can drop it.
        """
        with self._cond:
            deadline = time.monotonic() + timeout
            while True:
                if self._error is not None:
                    raise AudioUnavailable(str(self._error)) from self._error
                if self._closed:
                    return self._seq, None
                if self._blocks:
                    if last_seq == 0:
                        return self._blocks[-1]
                    oldest_seq = self._blocks[0][0]
                    if last_seq < oldest_seq - 1:
                        raise AudioClientTooSlow("audio listener fell behind")
                    for seq, block in self._blocks:
                        if seq > last_seq:
                            return seq, block
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return self._seq, None
                self._cond.wait(remaining)

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._stop.set()
            self._cond.notify_all()

    def _ensure_started_locked(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._error = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _capture_loop(self) -> None:
        try:
            for block in _call_source(self._source, self._stop):
                if self._stop.is_set():
                    break
                if not isinstance(block, (bytes, bytearray)):
                    raise AudioUnavailable("audio source yielded a non-bytes block")
                self._publish(bytes(block))
                if self._idle_expired():
                    break
        except Exception as exc:
            with self._cond:
                if not self._closed:
                    self._error = exc
                self._cond.notify_all()
        finally:
            with self._cond:
                self._stop.set()
                self._thread = None
                if (
                    self._listeners > 0
                    and not self._closed
                    and self._error is None
                ):
                    self._ensure_started_locked()
                self._cond.notify_all()

    def _publish(self, block: bytes) -> None:
        with self._cond:
            self._seq += 1
            self._blocks.append((self._seq, block))
            self._cond.notify_all()

    def _idle_expired(self) -> bool:
        with self._cond:
            if self._listeners > 0:
                return False
            if self._last_listener_left_at is None:
                self._last_listener_left_at = time.monotonic()
                return False
            return time.monotonic() - self._last_listener_left_at >= self._idle_timeout_s


def _call_source(
    source: AudioBlockSource | Callable[[], Iterable[bytes]],
    stop: threading.Event,
) -> Iterable[bytes]:
    try:
        parameter_count = len(inspect.signature(source).parameters)
    except (TypeError, ValueError):
        parameter_count = 1
    if parameter_count == 0:
        return source()  # type: ignore[misc]
    return source(stop)  # type: ignore[misc]


def _sounddevice_pcm_blocks(
    stop: threading.Event,
    *,
    device: str | int | None,
    block_seconds: float,
) -> Iterable[bytes]:
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise AudioUnavailable("sounddevice is not installed") from exc

    block_frames = max(1, round(SAMPLE_RATE * block_seconds))
    blocks: queue.Queue[bytes] = queue.Queue(maxsize=8)

    def callback(
        indata: bytes,
        frames: int,
        time_info: object,
        status: object,
    ) -> None:
        del frames, time_info
        if status:
            # Keep capture alive. The browser stream can tolerate a dropped block.
            pass
        try:
            blocks.put_nowait(bytes(indata))
            return
        except queue.Full:
            pass
        try:
            blocks.get_nowait()
        except queue.Empty:
            pass
        try:
            blocks.put_nowait(bytes(indata))
        except queue.Full:
            pass

    with sd.RawInputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
        blocksize=block_frames,
        device=device,
        callback=callback,
    ):
        while not stop.is_set():
            try:
                yield blocks.get(timeout=0.25)
            except queue.Empty:
                continue


class TalkPlayer:
    """Decode a browser-recorded clip to WAV and play it through the Pi speaker."""

    def __init__(
        self,
        *,
        max_bytes: int = TALK_MAX_BYTES,
        max_seconds: float = 20.0,
        run: Callable[..., subprocess.CompletedProcess[object]] = subprocess.run,
        which: Callable[[str], str | None] = shutil.which,
        playback_commands: Callable[[Path], Iterable[list[str]]] | None = None,
        ffmpeg_binary: str = "ffmpeg",
    ) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if max_seconds <= 0:
            raise ValueError("max_seconds must be positive")
        self.max_bytes = max_bytes
        self.max_seconds = max_seconds
        self._run = run
        self._which = which
        self._playback_commands = playback_commands or _talk_playback_commands
        self._ffmpeg_binary = ffmpeg_binary
        self._lock = threading.Lock()

    def playing(self) -> bool:
        return self._lock.locked()

    def play(self, data: bytes, content_type: str) -> TalkResult:
        if len(data) > self.max_bytes:
            raise TalkRejected("clip is too large")
        if not data:
            raise TalkRejected("clip is empty")
        if not self._lock.acquire(blocking=False):
            raise TalkBusy("another talk clip is already playing")
        try:
            return self._play_locked(data, content_type)
        finally:
            self._lock.release()

    def _play_locked(self, data: bytes, content_type: str) -> TalkResult:
        suffix = _suffix_for_content_type(content_type)
        with tempfile.TemporaryDirectory(prefix="beddington-talk-") as directory:
            in_path = Path(directory) / f"talk{suffix}"
            out_path = Path(directory) / "talk.wav"
            in_path.write_bytes(data)
            try:
                decode = self._run(
                    [
                        self._ffmpeg_binary,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-i",
                        str(in_path),
                        "-ar",
                        "48000",
                        "-ac",
                        "1",
                        "-t",
                        str(self.max_seconds + 0.5),
                        str(out_path),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    check=False,
                    timeout=20.0,
                )
            except subprocess.TimeoutExpired as exc:
                raise TalkPlaybackError("talk subprocess timed out") from exc
            if getattr(decode, "returncode", 1) != 0:
                raise TalkPlaybackError("ffmpeg failed to decode talk clip")
            seconds = _wav_duration_seconds(out_path)
            if seconds > self.max_seconds:
                raise TalkRejected("clip is too long")
            command = self._playback_command(out_path)
            if command is None:
                raise TalkPlaybackError("no audio playback command is available")
            try:
                played = self._run(
                    command,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=self.max_seconds + 15.0,
                )
            except subprocess.TimeoutExpired as exc:
                raise TalkPlaybackError("talk subprocess timed out") from exc
            if getattr(played, "returncode", 1) != 0:
                raise TalkPlaybackError("audio playback command failed")
            return TalkResult(seconds=seconds)

    def _playback_command(self, path: Path) -> list[str] | None:
        for command in self._playback_commands(path):
            if self._which(command[0]):
                return command
        return None


def _suffix_for_content_type(content_type: str) -> str:
    base = content_type.split(";", 1)[0].strip().lower()
    if base == "audio/mp4":
        return ".m4a"
    if base == "audio/ogg":
        return ".ogg"
    return ".webm"


def _talk_playback_commands(path: Path) -> Iterable[list[str]]:
    yield from _single_playback_commands(path)
    yield [
        "ffplay",
        "-nodisp",
        "-autoexit",
        "-loglevel",
        "quiet",
        "-volume",
        str(round(float(_playback_volume()) * 100)),
        str(path),
    ]


def _wav_duration_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as wav:
        rate = wav.getframerate()
        if rate <= 0:
            raise TalkPlaybackError("decoded WAV has no sample rate")
        return wav.getnframes() / rate
