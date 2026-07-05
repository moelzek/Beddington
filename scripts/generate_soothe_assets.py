from __future__ import annotations

import wave
from pathlib import Path

import numpy as np


SAMPLE_RATE = 16_000
ASSET_DIR = Path(__file__).resolve().parents[1] / "assets" / "soothe"


def main() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    _write_wav(ASSET_DIR / "chime.wav", _chime(seconds=0.3))


def _chime(seconds: float) -> np.ndarray:
    t = _time(seconds)
    samples = np.zeros_like(t)
    for start, duration, frequency, gain in (
        (0.00, 0.18, 523.25, 0.75),
        (0.12, 0.18, 659.25, 0.65),
    ):
        end = min(seconds, start + duration)
        mask = (t >= start) & (t < end)
        local = t[mask] - start
        envelope = _attack_release(
            local,
            duration=end - start,
            attack=0.012,
            release=0.09,
        )
        tone = np.sin(2 * np.pi * frequency * local)
        tone += 0.2 * np.sin(2 * np.pi * frequency * 2.0 * local)
        samples[mask] += gain * envelope * tone
    samples = _fade(samples, seconds=0.015)
    return _normalise(samples, peak=0.12)


def _sample_count(seconds: float) -> int:
    return round(seconds * SAMPLE_RATE)


def _time(seconds: float) -> np.ndarray:
    return np.arange(_sample_count(seconds), dtype=np.float64) / SAMPLE_RATE


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
