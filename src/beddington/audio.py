from __future__ import annotations

import queue
import time
import wave
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

import numpy as np

from .models import AudioWindow

SAMPLE_RATE = 16_000
WINDOW_SAMPLES = 15_600
HOP_SAMPLES = 7_800
WINDOW_SECONDS = WINDOW_SAMPLES / SAMPLE_RATE
HOP_SECONDS = HOP_SAMPLES / SAMPLE_RATE


def _put_drop_oldest(target: queue.Queue, item: object) -> None:
    try:
        target.put_nowait(item)
        return
    except queue.Full:
        pass
    try:
        target.get_nowait()
    except queue.Empty:
        pass
    try:
        target.put_nowait(item)
    except queue.Full:
        pass


class AudioSource(Protocol):
    name: str

    def windows(self) -> Iterator[AudioWindow]: ...

    @property
    def duration_seconds(self) -> float: ...


class WavFileAudioSource:
    def __init__(self, path: Path):
        self.path = path
        self.name = str(path)
        self._waveform = read_wav(path)

    @property
    def duration_seconds(self) -> float:
        return len(self._waveform) / SAMPLE_RATE

    def windows(self) -> Iterator[AudioWindow]:
        yield from iter_windows(self._waveform)


class RealtimeWavFileAudioSource:
    """Plays a WAV through the pipeline at real-time (wall-clock) pace.

    Same windows as :class:`WavFileAudioSource`, but each window is held back
    until its real-time offset. This lets soothe playback and quiet-check
    windows run for their real duration without relying on the live microphone
    capture path. Useful for deterministic, repeatable live-style demos.
    """

    def __init__(self, path: Path):
        self.path = path
        self.name = f"realtime:{path}"
        self._waveform = read_wav(path)

    @property
    def duration_seconds(self) -> float:
        return len(self._waveform) / SAMPLE_RATE

    def windows(self) -> Iterator[AudioWindow]:
        started_at = time.monotonic()
        for window in iter_windows(self._waveform):
            delay = (started_at + window.offset_seconds) - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            yield window


class MicrophoneAudioSource:
    """Real-time 16 kHz mono microphone windows using optional sounddevice."""

    def __init__(self, seconds: float, device: str | int | None = None):
        if seconds <= 0:
            raise ValueError("Microphone duration must be greater than zero")
        self.seconds = seconds
        self.device = device
        self.name = f"microphone:{device if device is not None else 'default'}"

    @property
    def duration_seconds(self) -> float:
        return self.seconds

    def windows(self) -> Iterator[AudioWindow]:
        try:
            import sounddevice as sd
        except ImportError as exc:
            raise RuntimeError(
                'Microphone support is optional. Install it with: pip install -e ".[mic]"'
            ) from exc

        input_sample_rate = _choose_input_sample_rate(sd, self.device)
        input_block_samples = max(1, round(HOP_SECONDS * input_sample_rate))
        blocks: queue.Queue[np.ndarray] = queue.Queue(
            maxsize=max(4, round(3.0 / HOP_SECONDS))
        )

        def callback(indata: np.ndarray, frames: int, time_info: object, status: object) -> None:
            # Keep the audio thread light: just copy + enqueue the raw block.
            # Resampling happens on the consumer thread to avoid input overflow.
            del frames, time_info
            if status:
                print(f"Microphone warning: {status}")
            _put_drop_oldest(blocks, indata[:, 0].astype(np.float32, copy=True))

        buffer = np.empty(0, dtype=np.float32)
        offset = 0.0
        deadline = time.monotonic() + self.seconds

        def add_block(block: np.ndarray) -> Iterator[AudioWindow]:
            nonlocal buffer, offset
            if input_sample_rate != SAMPLE_RATE:
                block = _resample(block, input_sample_rate, SAMPLE_RATE)
            buffer = np.concatenate((buffer, block))
            while len(buffer) >= WINDOW_SAMPLES:
                yield AudioWindow(offset, buffer[:WINDOW_SAMPLES].copy())
                buffer = buffer[HOP_SAMPLES:]
                offset += HOP_SECONDS

        with sd.InputStream(
            samplerate=input_sample_rate,
            channels=1,
            dtype="float32",
            blocksize=input_block_samples,
            device=self.device,
            latency="high",
            callback=callback,
        ):
            while time.monotonic() < deadline:
                timeout = max(0.1, min(1.0, deadline - time.monotonic() + 0.5))
                try:
                    block = blocks.get(timeout=timeout)
                except queue.Empty:
                    if time.monotonic() >= deadline:
                        break
                    continue
                yield from add_block(block)

        while not blocks.empty():
            yield from add_block(blocks.get_nowait())


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frame_count = wav.getnframes()
        raw = wav.readframes(frame_count)

    waveform = _decode_pcm(raw, sample_width)
    if channels > 1:
        waveform = waveform.reshape(-1, channels).mean(axis=1)
    if sample_rate != SAMPLE_RATE:
        waveform = _resample(waveform, sample_rate, SAMPLE_RATE)
    return np.clip(waveform.astype(np.float32), -1.0, 1.0)


def iter_windows(waveform: np.ndarray) -> Iterator[AudioWindow]:
    if len(waveform) <= WINDOW_SAMPLES:
        padded = np.pad(waveform, (0, max(0, WINDOW_SAMPLES - len(waveform))))
        yield AudioWindow(0.0, padded.astype(np.float32, copy=False))
        return

    last_start = len(waveform) - WINDOW_SAMPLES
    for start in range(0, last_start + 1, HOP_SAMPLES):
        yield AudioWindow(start / SAMPLE_RATE, waveform[start : start + WINDOW_SAMPLES])


def _decode_pcm(raw: bytes, sample_width: int) -> np.ndarray:
    if sample_width == 1:
        return (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    if sample_width == 2:
        return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if sample_width == 3:
        bytes_ = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3)
        values = (
            bytes_[:, 0].astype(np.int32)
            | (bytes_[:, 1].astype(np.int32) << 8)
            | (bytes_[:, 2].astype(np.int32) << 16)
        )
        values = np.where(values & 0x800000, values - 0x1000000, values)
        return values.astype(np.float32) / 8_388_608.0
    if sample_width == 4:
        return np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2_147_483_648.0
    raise ValueError(f"Unsupported WAV sample width: {sample_width} bytes")


def _choose_input_sample_rate(sounddevice: object, device: str | int | None) -> int:
    try:
        sounddevice.check_input_settings(
            device=device,
            channels=1,
            samplerate=SAMPLE_RATE,
            dtype="float32",
        )
        return SAMPLE_RATE
    except Exception:
        info = sounddevice.query_devices(device, "input")
        return round(float(info["default_samplerate"]))


def _resample(waveform: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    target_length = max(1, round(len(waveform) * target_rate / source_rate))
    source_positions = np.arange(len(waveform), dtype=np.float64)
    target_positions = np.linspace(0, max(0, len(waveform) - 1), target_length)
    return np.interp(target_positions, source_positions, waveform).astype(np.float32)
