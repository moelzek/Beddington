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
    _write_wav(ASSET_DIR / "pink_noise.wav", _pink_noise(seconds=24.0))
    _write_wav(ASSET_DIR / "rain.wav", _rain(seconds=26.0))
    _write_wav(ASSET_DIR / "ocean_waves.wav", _ocean_waves(seconds=30.0))
    _write_wav(ASSET_DIR / "forest_breeze.wav", _forest_breeze(seconds=28.0))
    _write_wav(ASSET_DIR / "night_sky.wav", _night_sky(seconds=30.0))
    _write_wav(ASSET_DIR / "music_box_lullaby.wav", _music_box_lullaby(seconds=24.0))
    _write_wav(ASSET_DIR / "shushing.wav", _shushing(seconds=24.0))
    _write_wav(ASSET_DIR / "fan_hum.wav", _fan_hum(seconds=24.0))


def _white_noise(seconds: float) -> np.ndarray:
    rng = np.random.default_rng(seed=20260621)
    samples = rng.normal(0.0, 1.0, _sample_count(seconds))
    samples = _low_pass(samples, smoothing=0.985)
    samples = _fade(samples, seconds=1.5)
    return _normalise(samples, peak=0.12)


def _heartbeat(seconds: float) -> np.ndarray:
    t = _time(seconds)
    samples = np.zeros_like(t)
    beat_interval = 60.0 / 72.0
    for start in np.arange(0.2, seconds, beat_interval):
        # "lub" then "dub": mid-bass thumps (~80-90 Hz) a small speaker can
        # actually reproduce, each with a higher transient so the beat is heard.
        samples += 1.0 * _pulse(t, start, 90.0, width=0.05)
        samples += 0.6 * _pulse(t, start, 190.0, width=0.022)
        samples += 0.7 * _pulse(t, start + 0.20, 80.0, width=0.06)
        samples += 0.4 * _pulse(t, start + 0.20, 170.0, width=0.026)
    samples = _low_pass(samples, smoothing=0.6)
    samples = _fade(samples, seconds=1.0)
    return _normalise(samples, peak=0.6)


def _uterine_whoosh(seconds: float) -> np.ndarray:
    rng = np.random.default_rng(seed=20260622)
    t = _time(seconds)
    noise = rng.normal(0.0, 1.0, len(t))
    # A lighter low-pass keeps mid frequencies so a small speaker actually
    # reproduces the whoosh (the old sub-bass rumble was inaudible on it).
    whoosh = _low_pass(noise, smoothing=0.86)
    swell = 0.5 + 0.35 * np.sin(2 * np.pi * 0.4 * t) + 0.15 * np.sin(
        2 * np.pi * 0.85 * t + 0.8
    )
    samples = whoosh * swell

    beat_interval = 60.0 / 70.0
    for start in np.arange(0.35, seconds, beat_interval):
        samples += 0.5 * _pulse(t, start, 85.0, width=0.06)

    samples = _fade(samples, seconds=2.5)
    return _normalise(samples, peak=0.55)


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


def _pink_noise(seconds: float) -> np.ndarray:
    rng = np.random.default_rng(seed=20260623)
    count = _sample_count(seconds)
    samples = np.zeros(count, dtype=np.float64)
    for weight, smoothing in [
        (0.45, 0.985),
        (0.28, 0.965),
        (0.18, 0.925),
        (0.09, 0.86),
    ]:
        noise = rng.normal(0.0, 1.0, count)
        samples += weight * _low_pass(noise, smoothing=smoothing)
    samples = _fade(samples, seconds=2.0)
    return _normalise(samples, peak=0.12)


def _rain(seconds: float) -> np.ndarray:
    rng = np.random.default_rng(seed=20260624)
    t = _time(seconds)
    bed = rng.normal(0.0, 1.0, len(t))
    samples = 0.55 * _low_pass(bed, smoothing=0.92)
    for start in rng.uniform(0.25, seconds - 0.25, round(seconds * 4.5)):
        frequency = rng.uniform(2200.0, 4200.0)
        width = rng.uniform(0.004, 0.012)
        gain = rng.uniform(0.012, 0.035)
        samples += gain * _pulse(t, start, frequency, width=width)
    samples = _fade(samples, seconds=2.0)
    return _normalise(samples, peak=0.14)


def _ocean_waves(seconds: float) -> np.ndarray:
    rng = np.random.default_rng(seed=20260625)
    t = _time(seconds)
    noise = rng.normal(0.0, 1.0, len(t))
    surf = _low_pass(noise, smoothing=0.965)
    wave = (0.5 + 0.5 * np.sin(2 * np.pi * 0.07 * t - np.pi / 2)) ** 1.8
    smaller_swell = 0.18 * (0.5 + 0.5 * np.sin(2 * np.pi * 0.14 * t + 0.7))
    samples = surf * (0.24 + 0.76 * wave + smaller_swell)
    samples += 0.08 * _low_pass(rng.normal(0.0, 1.0, len(t)), smoothing=0.9)
    samples = _fade(samples, seconds=3.0)
    return _normalise(samples, peak=0.18)


def _forest_breeze(seconds: float) -> np.ndarray:
    rng = np.random.default_rng(seed=20260626)
    t = _time(seconds)
    wind = _low_pass(rng.normal(0.0, 1.0, len(t)), smoothing=0.975)
    gust = 0.45 + 0.25 * np.sin(2 * np.pi * 0.045 * t + 0.2)
    gust += 0.18 * np.sin(2 * np.pi * 0.11 * t + 1.4)
    gust += 0.08 * np.sin(2 * np.pi * 0.21 * t + 2.1)
    samples = wind * np.clip(gust, 0.18, 0.9)
    samples = _fade(samples, seconds=3.0)
    return _normalise(samples, peak=0.13)


def _night_sky(seconds: float) -> np.ndarray:
    t = _time(seconds)
    tremolo = 0.82 + 0.12 * np.sin(2 * np.pi * 0.055 * t)
    tremolo += 0.06 * np.sin(2 * np.pi * 0.09 * t + 1.6)
    samples = np.zeros_like(t)
    for gain, frequency in [
        (0.36, 146.83),
        (0.24, 220.00),
        (0.18, 293.66),
        (0.12, 329.63),
    ]:
        samples += gain * np.sin(2 * np.pi * frequency * t)
        samples += 0.35 * gain * np.sin(2 * np.pi * frequency * 1.006 * t)
    samples *= tremolo
    samples = _low_pass(samples, smoothing=0.82)
    samples = _fade(samples, seconds=3.0)
    return _normalise(samples, peak=0.12)


def _music_box_lullaby(seconds: float) -> np.ndarray:
    t = _time(seconds)
    notes = [
        392.00,
        392.00,
        440.00,
        392.00,
        329.63,
        349.23,
        392.00,
        329.63,
        293.66,
        329.63,
        349.23,
        392.00,
    ]
    samples = np.zeros_like(t)
    note_seconds = 0.8
    repeats = math.ceil(seconds / (len(notes) * note_seconds))
    for index, note in enumerate(notes * repeats):
        start = index * note_seconds
        if start >= seconds:
            break
        end = min(seconds, start + note_seconds * 0.86)
        mask = (t >= start) & (t < end)
        local = t[mask] - start
        envelope = np.exp(-4.6 * local) * np.clip(local / 0.018, 0.0, 1.0)
        bell = np.sin(2 * np.pi * note * local)
        bell += 0.44 * np.sin(2 * np.pi * note * 2.0 * local)
        bell += 0.18 * (2 / np.pi) * np.arcsin(np.sin(2 * np.pi * note * 3.0 * local))
        samples[mask] += envelope * bell
    samples = _low_pass(samples, smoothing=0.72)
    samples = _fade(samples, seconds=1.5)
    return _normalise(samples, peak=0.13)


def _shushing(seconds: float) -> np.ndarray:
    rng = np.random.default_rng(seed=20260627)
    t = _time(seconds)
    noise = rng.normal(0.0, 1.0, len(t))
    bright_noise = noise - _low_pass(noise, smoothing=0.93)
    bright_noise = _low_pass(bright_noise, smoothing=0.32)
    envelope = np.zeros_like(t)
    for start in np.arange(0.25, seconds, 1.05):
        duration = min(0.62, seconds - start)
        mask = (t >= start) & (t < start + duration)
        local = t[mask] - start
        envelope[mask] += _attack_release(
            local,
            duration=duration,
            attack=0.11,
            release=0.24,
        )
    samples = bright_noise * np.clip(envelope, 0.0, 1.0)
    samples = _fade(samples, seconds=1.5)
    return _normalise(samples, peak=0.15)


def _fan_hum(seconds: float) -> np.ndarray:
    rng = np.random.default_rng(seed=20260628)
    t = _time(seconds)
    noise = _low_pass(rng.normal(0.0, 1.0, len(t)), smoothing=0.988)
    tone = 0.5 * np.sin(2 * np.pi * 120.0 * t)
    tone += 0.14 * np.sin(2 * np.pi * 240.0 * t)
    samples = 0.55 * noise + tone
    samples = _low_pass(samples, smoothing=0.7)
    samples = _fade(samples, seconds=2.0)
    return _normalise(samples, peak=0.12)


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
