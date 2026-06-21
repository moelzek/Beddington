from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np


SAMPLE_RATE = 16_000
ASSET_DIR = Path(__file__).resolve().parents[1] / "assets" / "soothe"


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    _write_wav(ASSET_DIR / "white_noise.wav", _white_noise(seconds=20.0))
    _write_wav(ASSET_DIR / "uterine_whoosh.wav", _uterine_whoosh(seconds=30.0))
    _write_wav(ASSET_DIR / "heartbeat.wav", _heartbeat(seconds=20.0))
    _write_wav(ASSET_DIR / "soothing_music.wav", _soothing_music(seconds=24.0))


def _white_noise(seconds: float) -> np.ndarray:
    rng = np.random.default_rng(seed=20260621)
    samples = rng.normal(0.0, 1.0, _sample_count(seconds))
    samples = _low_pass(samples, smoothing=0.985)
    samples = _fade(samples, seconds=1.5)
    return _normalise(samples, peak=0.12)


def _heartbeat(seconds: float) -> np.ndarray:
    t = _time(seconds)
    samples = np.zeros_like(t)
    beat_interval = 60.0 / 78.0
    for start in np.arange(0.2, seconds, beat_interval):
        samples += 0.9 * _pulse(t, start, 36.0, width=0.028)
        samples += 0.55 * _pulse(t, start + 0.18, 48.0, width=0.038)
    samples = _low_pass(samples, smoothing=0.96)
    samples = _fade(samples, seconds=1.0)
    return _normalise(samples, peak=0.16)


def _uterine_whoosh(seconds: float) -> np.ndarray:
    rng = np.random.default_rng(seed=20260622)
    t = _time(seconds)
    noise = rng.normal(0.0, 1.0, len(t))
    deep_noise = _low_pass(noise, smoothing=0.994)
    swell = 0.55 + 0.28 * np.sin(2 * np.pi * 0.42 * t) + 0.17 * np.sin(
        2 * np.pi * 0.86 * t + 0.8
    )
    rumble = 0.55 * np.sin(2 * np.pi * 42.0 * t) + 0.22 * np.sin(
        2 * np.pi * 67.0 * t + 0.4
    )
    samples = 1.25 * deep_noise * swell + 0.22 * rumble

    beat_interval = 60.0 / 72.0
    for start in np.arange(0.35, seconds, beat_interval):
        samples += 0.8 * _pulse(t, start, 32.0, width=0.055)
        samples += 0.35 * _pulse(t, start + 0.16, 44.0, width=0.065)

    samples = _low_pass(samples, smoothing=0.965)
    samples = _fade(samples, seconds=2.5)
    return _normalise(samples, peak=0.22)


def _soothing_music(seconds: float) -> np.ndarray:
    t = _time(seconds)
    notes = [
        261.63,
        329.63,
        392.00,
        329.63,
        293.66,
        349.23,
        440.00,
        349.23,
    ]
    samples = np.zeros_like(t)
    note_seconds = 1.5
    for index, note in enumerate(notes * math.ceil(seconds / (len(notes) * note_seconds))):
        start = index * note_seconds
        if start >= seconds:
            break
        end = min(seconds, start + note_seconds)
        mask = (t >= start) & (t < end)
        local = t[mask] - start
        envelope = _attack_release(local, duration=end - start, attack=0.18, release=0.45)
        fundamental = np.sin(2 * np.pi * note * local)
        overtone = 0.28 * np.sin(2 * np.pi * note * 2.0 * local)
        breath = 0.08 * np.sin(2 * np.pi * 0.35 * t[mask])
        samples[mask] += envelope * (fundamental + overtone) * (1.0 + breath)

    pad = 0.18 * np.sin(2 * np.pi * 130.81 * t) + 0.12 * np.sin(2 * np.pi * 196.00 * t)
    samples += _fade(pad, seconds=2.0)
    samples = _low_pass(samples, smoothing=0.93)
    samples = _fade(samples, seconds=2.0)
    return _normalise(samples, peak=0.14)


def _sample_count(seconds: float) -> int:
    return round(seconds * SAMPLE_RATE)


def _time(seconds: float) -> np.ndarray:
    return np.arange(_sample_count(seconds), dtype=np.float64) / SAMPLE_RATE


def _pulse(t: np.ndarray, start: float, frequency: float, width: float) -> np.ndarray:
    shifted = t - start
    envelope = np.exp(-((shifted / width) ** 2))
    tone = np.sin(2 * np.pi * frequency * shifted)
    return np.where(shifted >= 0, envelope * tone, 0.0)


def _attack_release(
    t: np.ndarray,
    duration: float,
    attack: float,
    release: float,
) -> np.ndarray:
    envelope = np.ones_like(t)
    if attack > 0:
        envelope *= np.clip(t / attack, 0.0, 1.0)
    if release > 0:
        envelope *= np.clip((duration - t) / release, 0.0, 1.0)
    return envelope


def _low_pass(samples: np.ndarray, smoothing: float) -> np.ndarray:
    output = np.empty_like(samples)
    current = 0.0
    for index, sample in enumerate(samples):
        current = smoothing * current + (1.0 - smoothing) * sample
        output[index] = current
    return output


def _fade(samples: np.ndarray, seconds: float) -> np.ndarray:
    count = min(len(samples) // 2, _sample_count(seconds))
    if count == 0:
        return samples
    envelope = np.ones(len(samples), dtype=np.float64)
    fade = np.linspace(0.0, 1.0, count)
    envelope[:count] = fade
    envelope[-count:] = fade[::-1]
    return samples * envelope


def _normalise(samples: np.ndarray, peak: float) -> np.ndarray:
    max_abs = float(np.max(np.abs(samples)))
    if max_abs == 0.0:
        return samples.astype(np.float32)
    return (samples / max_abs * peak).astype(np.float32)


def _write_wav(path: Path, samples: np.ndarray) -> None:
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767).astype("<i2")
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(pcm.tobytes())


if __name__ == "__main__":
    main()
