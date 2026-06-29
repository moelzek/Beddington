"""Pure preset selection from recorded soothe outcomes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

Outcome = tuple[float, str, bool]


def best_preset(
    outcomes: Iterable[Outcome],
    presets: Mapping[str, object],
    min_samples: int,
    default: str,
) -> str:
    """Choose a preset from outcomes, with sparse data falling back or exploring."""
    names = sorted(presets)
    if not names:
        return default

    attempts = {name: 0 for name in names}
    successes = {name: 0 for name in names}
    total_attempts = 0

    for _timestamp, sound_name, success in outcomes:
        if sound_name not in attempts:
            continue
        attempts[sound_name] += 1
        successes[sound_name] += 1 if success else 0
        total_attempts += 1

    if total_attempts < min_samples:
        return default

    under_sampled = [name for name in names if attempts[name] < min_samples]
    if under_sampled:
        fewest_attempts = min(attempts[name] for name in under_sampled)
        return min(name for name in under_sampled if attempts[name] == fewest_attempts)

    return min(
        names,
        key=lambda name: (-(successes[name] / attempts[name]), name),
    )
